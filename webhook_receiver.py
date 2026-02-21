#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PORT = int(os.getenv("WEBHOOK_PORT", "8753"))
VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "lucia-whatsapp-verify")
LOG_PATH = Path(os.getenv("WEBHOOK_LOG_PATH", "whatsapp-assistant/webhook_events.ndjson"))


def append_event(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "WhatsAppWebhookReceiver/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Keep terminal output concise and deterministic.
        print(f"[{datetime.now(timezone.utc).isoformat()}] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        mode = qs.get("hub.mode", [None])[0]
        token = qs.get("hub.verify_token", [None])[0]
        challenge = qs.get("hub.challenge", [None])[0]

        if mode == "subscribe" and token == VERIFY_TOKEN and challenge is not None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(challenge.encode("utf-8"))
            return

        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"error":"verification_failed"}')

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        text = raw.decode("utf-8", errors="replace")
        parsed = None
        try:
            parsed = json.loads(text) if text else None
        except json.JSONDecodeError:
            parsed = None

        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body_raw": text,
            "body_json": parsed,
        }
        append_event(record)

        statuses = []
        if isinstance(parsed, dict):
            for entry in parsed.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for status in value.get("statuses", []):
                        statuses.append(
                            {
                                "id": status.get("id"),
                                "status": status.get("status"),
                                "recipient_id": status.get("recipient_id"),
                                "errors": status.get("errors"),
                            }
                        )

        if statuses:
            print(f"Status update(s): {json.dumps(statuses, ensure_ascii=True)}")
        else:
            print("Webhook received (no status objects).")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Webhook receiver listening on 0.0.0.0:{PORT}")
    print(f"Verify token: {VERIFY_TOKEN}")
    print(f"Log file: {LOG_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
