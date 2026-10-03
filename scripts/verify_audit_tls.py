"""Operator-only wrong-certificate and lost-response replay against private collector."""

import argparse
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which("docker")
BASE = "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"


def run(report):
    if (ROOT / ".local").resolve() not in report.resolve().parents or report.exists():
        raise ValueError("Fresh private report required")
    wrong = ROOT / ".local/audit-wrong-certificate"
    wrong.mkdir(mode=0o700, exist_ok=True)
    if not (wrong / "client.crt").exists():
        subprocess.run(  # noqa: S603 - fixed synthetic certificate generator
            [
                shutil.which("openssl"),
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-subj",
                "/CN=untrusted-synthetic-client",
                "-keyout",
                str(wrong / "client.key"),
                "-out",
                str(wrong / "client.crt"),
                "-days",
                "1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (wrong / "client.key").chmod(0o600)
    event_id = str(uuid.uuid4())
    code = """import ssl,json,time,urllib.request,urllib.error
event={'schema_version':2,'component':'gateway','timestamp':time.time(),'event':'delivery_verification','outcome':'allowed','verdict':'synthetic','event_id':EVENT_ID,'request_id':REQUEST_ID}
request=urllib.request.Request('https://audit-collector:8443/events',data=json.dumps(event).encode(),headers={'Content-Type':'application/json'})
c=ssl.create_default_context(cafile='/certs/ca.crt')
c.load_cert_chain('/wrong/client.crt','/wrong/client.key')
wrong=False;reason='not_rejected'
try: urllib.request.urlopen(request,context=c,timeout=5)
except urllib.error.HTTPError: reason='http_error_not_tls_proof'
except urllib.error.URLError as e:
    reason=getattr(e.reason,'reason','transport_error_not_tls_proof')
    wrong=(isinstance(e.reason,ssl.SSLError)
           and reason in {'TLSV1_ALERT_UNKNOWN_CA','SSLV3_ALERT_BAD_CERTIFICATE','TLSV1_ALERT_BAD_CERTIFICATE'})
except ssl.SSLError as e:
    reason=e.reason
    wrong=reason in {'TLSV1_ALERT_UNKNOWN_CA','SSLV3_ALERT_BAD_CERTIFICATE','TLSV1_ALERT_BAD_CERTIFICATE'}
except OSError: reason='transport_error_not_tls_proof'
c=ssl.create_default_context(cafile='/certs/ca.crt');c.load_cert_chain('/certs/shipper.crt','/certs/shipper.key')
r=urllib.request.urlopen(request,context=c,timeout=5)
first=r.status;r.close() # deliberately discard acknowledgement body
with urllib.request.urlopen(request,context=c,timeout=5) as r: ack=json.load(r)
print(json.dumps({'wrong_certificate_rejected':wrong,'wrong_certificate_reason':reason,'discarded_ack_response':first,'retry_durable':ack=={'event_id':EVENT_ID,'durable':True}}))
""".replace("EVENT_ID", repr(event_id)).replace("REQUEST_ID", repr(str(uuid.uuid4())))
    args = [
        DOCKER,
        "run",
        "--rm",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--network",
        "secure-llm-platform-reference_audit-delivery",
    ]
    for filename in ("ca.crt", "shipper.crt", "shipper.key"):
        args += [
            "--mount",
            f"type=bind,src={ROOT / '.local/audit-certs' / filename},dst=/certs/{filename},readonly",
        ]
    args += ["--mount", f"type=bind,src={wrong},dst=/wrong,readonly", BASE, "python", "-c", code]
    observed = json.loads(subprocess.check_output(args, text=True))  # noqa: S603 - fixed private network
    query = (
        "import sqlite3,sys;print(sqlite3.connect('/data/events.sqlite3').execute("
        "'SELECT COUNT(*) FROM events WHERE event_id=?',(sys.argv[1],)).fetchone()[0])"
    )
    count = int(
        subprocess.check_output(  # noqa: S603 - owned private collector; SQL parameter binding
            [
                DOCKER,
                "exec",
                "secure-llm-platform-reference-audit-collector-1",
                "python",
                "-c",
                query,
                event_id,
            ],
            text=True,
        )
    )
    result = {
        "checks": observed,
        "deduplicated_rows": count,
        "accepted": observed["wrong_certificate_rejected"]
        and observed["retry_durable"]
        and observed["discarded_ack_response"] == 200
        and count == 1,
    }
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["accepted"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    raise SystemExit(0 if run(parser.parse_args().report) else 1)
