"""Local Pit Boss server. Secrets stay in the environment."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from domains.routes.router import route

WEB = ROOT / "apps" / "web"
PUBLIC = WEB / "public"
MAX_BODY = 16_384
_ALLOWED_SUFFIXES = {".html", ".json"}


def _blocked_public_path(path: str) -> bool:
    bare = path.split("?", 1)[0].rstrip("/") or "/"
    return bare == "/api/databricks" or bare.startswith("/api/databricks/")


def public_write_route(path: str) -> bool:
    """Routes observation writes are not an active entry."""
    return False


def safe_static(url_path: str, public: Path = PUBLIC, web: Path = WEB) -> Path | None:
    """Serve one HTML or JSON file that stays inside an approved root."""
    if not isinstance(url_path, str) or "\x00" in url_path:
        return None
    decoded = url_path
    for _ in range(3):
        try:
            nxt = unquote(decoded)
        except ValueError:
            return None
        if nxt == decoded:
            break
        decoded = nxt
    if "\x00" in decoded or "\\" in decoded:
        return None
    parts = [part for part in decoded.split("/") if part not in {"", "."}]
    if any(part == ".." or part.startswith("..") for part in parts):
        return None
    if any(":" in part or "\x00" in part for part in parts):
        return None
    relative = "/".join(parts)
    if relative in {"", "index.html"}:
        root = public
        candidate = public / "index.html"
    else:
        suffix = Path(relative).suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            return None
        root = public if suffix == ".json" else web
        candidate = root / relative
    try:
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError):
        return None
    if not resolved.is_file():
        return None
    if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
        return None
    return resolved


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
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
        if _blocked_public_path(parsed.path):
            self._send(404, b"missing", "text/plain")
            return
        if parsed.path == "/api/investigate":
            self._investigate()
            return
        relative = "index.html" if parsed.path in {"/", "/index.html"} else parsed.path
        candidate = safe_static(relative)
        if candidate is not None:
            kind = "application/json" if candidate.suffix == ".json" else "text/html"
            self._send(200, candidate.read_bytes(), kind)
            return
        self._send(404, b"missing", "text/plain")

    def _read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, b'{"ok": false}', "application/json")
            return None
        if length < 0 or length > MAX_BODY:
            self._send(413, b'{"ok": false, "error": "body too large"}', "application/json")
            return None
        return self.rfile.read(length)

    def _investigate(self) -> None:
        from domains.royale.investigate import investigate

        raw = self._read_body() if self.command == "POST" else b"{}"
        if raw is None:
            return
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, b'{"ok": false, "error": "invalid json"}', "application/json")
            return
        question = payload.get("question", "")
        if not isinstance(question, str):
            self._send(400, b'{"ok": false, "error": "question must be a string"}', "application/json")
            return
        case_path = PUBLIC / "ace_case.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        result = investigate(question, case)
        safe = {
            "ok": result["ok"],
            "answer": result["answer"],
            "metrics": result["metrics"],
            "sources": result["sources"],
            "period": result["period"],
            "limitations": result["limitations"],
            "computed_by": "code",
        }
        if result["ok"] and isinstance(question, str):
            try:
                from integrations.gemini.grounded import explain_case

                spoken = explain_case(question, case)
                if spoken.get("ok"):
                    safe["narrative"] = spoken["answer"]
                    safe["narrative_by"] = "gemini-2.5-flash"
            except Exception:
                pass
        self._send(200, json.dumps(safe).encode(), "application/json")

    def do_POST(self) -> None:
        if _blocked_public_path(self.path):
            self._send(404, b"missing", "text/plain")
            return
        if urlparse(self.path).path == "/api/investigate":
            self._investigate()
            return
        if not public_write_route(self.path):
            self._send(404, b'{"ok": false, "error": "no public write route"}', "application/json")
            return

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()


if __name__ == "__main__":
    main()
