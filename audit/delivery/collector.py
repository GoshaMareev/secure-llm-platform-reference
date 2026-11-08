"""Private mTLS collector demonstrating a durable metadata event contract."""

import json
import os
import sqlite3
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from secure_rag.native_audit import MAX_EVENT_BYTES, fsync_directory, validate_event

DATABASE = Path(os.environ.get("AUDIT_DATABASE", "/data/events.sqlite3"))
LOCK = threading.Lock()


def store(event):
    raw = validate_event(event).decode()
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK, sqlite3.connect(DATABASE) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        prior = db.execute("SELECT payload FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
        if prior and prior[0] != raw:
            raise ValueError("event_id_collision")
        db.execute("INSERT OR IGNORE INTO events VALUES (?,?)", (event["event_id"], raw))
        db.commit()  # Acknowledgement follows durable transaction, including replays.
        fsync_directory(DATABASE.parent)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/events":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_EVENT_BYTES:
                raise ValueError("size_limit")
            event = json.loads(self.rfile.read(length))
            store(event)
            body = json.dumps({"event_id": event["event_id"], "durable": True}).encode()
            self.send_response(200)
        except (ValueError, KeyError, TypeError):
            body = b'{"error":"invalid_event"}'
            self.send_response(400)
        except (OSError, sqlite3.Error):
            body = b'{"error":"storage_unavailable"}'
            self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    certificates = Path(os.environ.get("AUDIT_CERT_DIR", "/run/certs"))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(certificates / "collector.crt", certificates / "collector.key")
    context.load_verify_locations(certificates / "ca.crt")
    server = ThreadingHTTPServer(("0.0.0.0", 8443), Handler)  # noqa: S104 - unpublished internal mTLS container
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
