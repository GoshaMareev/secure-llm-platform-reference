"""At-least-once delivery, deduplicated by event ID; checkpoint outside the spool."""

import json
import os
import ssl
import time
from pathlib import Path
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from secure_rag.native_audit import fsync_directory, validate_event


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Shipper:
    def __init__(self, spool, checkpoint, cert_dir, url="https://audit-collector:8443/events"):
        if url != "https://audit-collector:8443/events":
            raise ValueError("collector_endpoint_not_allowed")
        self.spool, self.checkpoint = Path(spool), Path(checkpoint)
        cert_dir = Path(cert_dir)
        context = ssl.create_default_context(cafile=cert_dir / "ca.crt")
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert_dir / "shipper.crt", cert_dir / "shipper.key")
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
        self.url = url
        self.state = json.loads(self.checkpoint.read_text()) if self.checkpoint.exists() else {"segments": {}}

    def save(self):
        self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(self.state, file)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.checkpoint)
        fsync_directory(self.checkpoint.parent)

    def deliver(self, event):
        request = Request(  # noqa: S310 - fixed, validated HTTPS collector; redirects disabled
            self.url, data=validate_event(event), headers={"Content-Type": "application/json"}, method="POST"
        )
        with self.opener.open(request, timeout=5) as response:
            acknowledgement = json.loads(response.read(1024))
        if acknowledgement != {"event_id": event["event_id"], "durable": True}:
            raise ValueError("invalid_acknowledgement")

    def once(self):
        # Rotation may rename a segment: replay is safe because event IDs persist.
        delivered = 0
        for path in sorted(self.spool.glob("*.jsonl")):
            state = self.state["segments"].setdefault(path.name, {"offset": 0})
            inode = path.stat().st_ino
            if state.get("inode") != inode:
                state.update(offset=0, inode=inode)
            with path.open("rb") as file:
                file.seek(state["offset"])
                while line := file.readline():
                    if not line.endswith(b"\n"):
                        break  # writer has not committed the complete event yet
                    event = json.loads(line)
                    if event.get("schema_version") == 2:
                        self.deliver(event)
                        delivered += 1
                    # Legacy events remain readable and local; never ship prompt fields.
                    state.update(offset=file.tell(), acked_at=time.time())
                    self.save()
        return delivered


def main():
    shipper = Shipper("/spool", "/state/checkpoint.json", "/run/certs")
    delay = 1
    while True:
        try:
            shipper.once()
            delay = 1
        except (OSError, ValueError, KeyError):
            delay = min(30, delay * 2)
        time.sleep(delay)


if __name__ == "__main__":
    main()
