"""Local Pit Boss server. Secrets stay in the environment."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from domains.routes.router import append_observation, route

WEB = ROOT / "apps" / "web"
PUBLIC = WEB / "public"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/route":
            query = parse_qs(parsed.query)
            result = route(
                query.get("origin", ["msc"])[0],
                query.get("dest", ["northgate"])[0],
                query.get("mode", ["walk"])[0],
            )
            self._send(200, json.dumps(result).encode(), "application/json")
            return
        if parsed.path == "/api/databricks":
            from integrations.databricks.client import status
            payload = status()
            payload.pop("host", None)
            self._send(200, json.dumps({"ok": payload.get("ok"), "error": payload.get("error")}).encode(), "application/json")
            return
        relative = "index.html" if parsed.path in {"/", "/index.html"} else parsed.path.lstrip("/")
        candidate = (PUBLIC / relative) if relative.endswith(".json") else (WEB / relative)
        if candidate.is_file():
            kind = "application/json" if candidate.suffix == ".json" else "text/html"
            self._send(200, candidate.read_bytes(), kind)
            return
        self._send(404, b"missing", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/observations":
            self._send(404, b"missing", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if payload.get("consent") != "yes":
            self._send(400, b'{"ok": false, "error": "consent is required"}', "application/json")
            return
        append_observation(payload)
        self._send(200, b'{"ok": true}', "application/json")

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()


if __name__ == "__main__":
    main()
