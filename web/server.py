"""Local web interface for the Poly transpiler.

A zero-dependency stdlib HTTP server that serves the glass UI from ./static and
exposes the real compiler pipeline over two JSON endpoints:

    POST /api/transpile   {source, target, api_key?}  -> {ok, code, records, ms}
    POST /api/selfcheck   {source, api_key?}          -> {ok, rows, all_ok, ms}

Security note: this is a LOCAL demo tool. The self-check runs the submitted
program under CPython as the reference oracle, so the server binds to
127.0.0.1 by default and must not be exposed publicly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poly.codegen import generate                 # noqa: E402
from poly.codegen.base import iter_holes          # noqa: E402
from poly.differential import self_check          # noqa: E402
from poly.errors import PolyError                 # noqa: E402
from poly.lexer import tokenize                   # noqa: E402
from poly.lower import lower                      # noqa: E402
from poly.parser import parse                     # noqa: E402
from poly.semantic import analyze                 # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml",
        ".webp": "image/webp", ".ico": "image/x-icon"}

# One compile at a time: protects the ANTHROPIC_API_KEY env round-trip and keeps
# the hole cache writes serial.
_LOCK = threading.Lock()


def _build(source: str):
    return lower(analyze(parse(tokenize(source)), source))


def _fill(module, targets, api_key: str, no_llm: bool) -> list[dict]:
    """Fill holes for the given targets; returns JSON-ready fill records."""
    if no_llm or not iter_holes(module):
        return []
    from poly.llm import HoleFiller
    old = os.environ.get("ANTHROPIC_API_KEY")
    try:
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        # Explicit mode: live only when the user pasted a key, mock otherwise.
        filler = HoleFiller(mode="live" if api_key else "mock")
        for tgt in targets:
            if tgt in ("js", "py", "python"):
                filler.fill_for_target(module, tgt)
        return [{"hole": r.hole_id, "target": r.target, "via": r.source_via,
                 "attempts": r.attempts} for r in filler.records]
    finally:
        if api_key:
            if old is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old


def api_transpile(payload: dict) -> dict:
    source = payload.get("source", "")
    target = payload.get("target", "js")
    api_key = (payload.get("api_key") or "").strip()
    no_llm = bool(payload.get("no_llm"))
    t0 = time.perf_counter()
    try:
        with _LOCK:
            module = _build(source)
            records = _fill(module, [target], api_key, no_llm)
            code = generate(module, target)
        return {"ok": True, "code": code, "records": records,
                "ms": round((time.perf_counter() - t0) * 1000)}
    except PolyError as exc:
        return {"ok": False, "error": {"message": exc.message,
                                       "rendered": exc.render(source)},
                "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": {"message": str(exc),
                                       "rendered": f"internal error: {exc}"},
                "ms": round((time.perf_counter() - t0) * 1000)}


def api_selfcheck(payload: dict) -> dict:
    source = payload.get("source", "")
    api_key = (payload.get("api_key") or "").strip()
    no_llm = bool(payload.get("no_llm"))
    t0 = time.perf_counter()
    try:
        with _LOCK:
            module = _build(source)
            _fill(module, ["js", "py"], api_key, no_llm)
            report = self_check(source, module)
        rows = [{"name": r["name"], "status": r["status"],
                 "output": r["output"].strip()[:500]} for r in report["rows"]]
        return {"ok": True, "rows": rows, "all_ok": report["ok"],
                "ms": round((time.perf_counter() - t0) * 1000)}
    except PolyError as exc:
        return {"ok": False, "error": {"message": exc.message,
                                       "rendered": exc.render(source)},
                "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": {"message": str(exc),
                                       "rendered": f"internal error: {exc}"},
                "ms": round((time.perf_counter() - t0) * 1000)}


_ROUTES = {"/api/transpile": api_transpile, "/api/selfcheck": api_selfcheck}


class Handler(BaseHTTPRequestHandler):
    # ---- static files -----------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        file = (STATIC / name).resolve()
        if not str(file).startswith(str(STATIC)) or not file.is_file():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, file.read_bytes(), MIME.get(file.suffix.lower(), "application/octet-stream"))

    # ---- API --------------------------------------------------------------
    def do_POST(self):
        route = _ROUTES.get(self.path.split("?", 1)[0])
        if route is None:
            self._send(404, b'{"error":"unknown endpoint"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, b'{"error":"bad json"}', "application/json")
            return
        body = json.dumps(route(payload)).encode()
        self._send(200, body, "application/json")

    # ---- plumbing ---------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quiet static chatter, keep API lines
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("poly-web: %s\n" % (args[0],))


def main() -> int:
    ap = argparse.ArgumentParser(description="Poly web interface (local demo tool)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"poly web interface -> http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
