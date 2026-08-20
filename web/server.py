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

from poly import ast_nodes as A                   # noqa: E402
from poly.cli import _pretty                      # noqa: E402
from poly.codegen import generate                 # noqa: E402
from poly.codegen.base import iter_holes          # noqa: E402
from poly.differential import self_check          # noqa: E402
from poly.errors import CompileError, PolyError   # noqa: E402
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


# ---- pipeline visualizer -------------------------------------------------

def _cap(text: str, max_lines: int) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines]) + f"\n... (+{len(lines) - max_lines} more lines)"


def _semantic_summary(ast_mod) -> str:
    """A human-readable digest of what semantic analysis concluded."""
    lines: list[str] = []
    eligible = 0

    def count_pure(node) -> None:
        nonlocal eligible
        if isinstance(node, (A.Comprehension, A.SliceExpr)) and getattr(node, "pure", False):
            eligible += 1
        for f, v in vars(node).items():
            if f == "span":
                continue
            if isinstance(v, list):
                for x in v:
                    if hasattr(x, "__dataclass_fields__"):
                        count_pure(x)
            elif hasattr(v, "__dataclass_fields__"):
                count_pure(v)

    for stmt in ast_mod.body:
        if isinstance(stmt, A.FunctionDef):
            params = ", ".join(f"{p.name}: {getattr(p, 'type', '?')}" for p in stmt.params)
            lines.append(f"def {stmt.name}({params}) -> {getattr(stmt, 'ret_type', '?')}")
        elif isinstance(stmt, A.Assign) and isinstance(stmt.target, A.Name):
            lines.append(f"{stmt.target.id}: {getattr(stmt.value, 'type', '?')}")
    count_pure(ast_mod)
    lines.append("")
    lines.append("scopes resolved: module + one per function")
    lines.append(f"pure hole-eligible constructs found: {eligible}")
    return "\n".join(lines)


def _narrate(stages: list[dict], source: str, api_key: str) -> list[str] | None:
    """One Claude call producing a one-sentence note per stage. None on any failure."""
    try:
        import anthropic
        digest = "\n".join(
            f"Stage {i + 1} {s['name']} [{s['status']}]:\n{s['detail'][:350]}\n"
            for i, s in enumerate(stages)
        )
        prompt = (
            "You annotate one run of a small educational compiler (Python subset to JS/Python/C) "
            "for a live demo.\nSource program:\n" + source[:1800] + "\n\n"
            "Per-stage artifacts (truncated):\n" + digest + "\n"
            f"Return ONLY a JSON array of exactly {len(stages)} strings. String i is ONE concise "
            "sentence (max 22 words) saying what stage i did for THIS program, citing one concrete "
            "detail from its artifact. No markdown."
        )
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=os.environ.get("POLY_LLM_MODEL", "claude-sonnet-5"),
            max_tokens=600, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if text.startswith("```"):
            text = "\n".join(text.splitlines()[1:-1])
        notes = json.loads(text)
        if isinstance(notes, list) and len(notes) >= len(stages):
            return [str(n) for n in notes[:len(stages)]]
    except Exception:
        pass
    return None


def api_pipeline(payload: dict) -> dict:
    source = payload.get("source", "")
    target = payload.get("target", "js")
    api_key = (payload.get("api_key") or "").strip()
    t0 = time.perf_counter()
    stages: list[dict] = []

    def stage(name: str, fn):
        """Run one stage; append its record. Returns (value, ok)."""
        s0 = time.perf_counter()
        try:
            value, detail = fn()
            stages.append({"name": name, "status": "ok", "detail": detail,
                           "ms": round((time.perf_counter() - s0) * 1000)})
            return value, True
        except PolyError as exc:
            stages.append({"name": name, "status": "error", "detail": exc.render(source),
                           "ms": round((time.perf_counter() - s0) * 1000)})
            return None, False

    def blocked(*names: str) -> None:
        for n in names:
            stages.append({"name": n, "status": "blocked",
                           "detail": "not reached: an earlier stage failed", "ms": 0})

    def lex_stage():
        toks = tokenize(source)
        detail = _cap("\n".join(repr(t) for t in toks), 48) + f"\n\ntotal: {len(toks)} tokens"
        return toks, detail

    def parse_stage():
        m = parse(tokens)
        return m, _cap(_pretty(m), 60)

    def semantic_stage():
        analyze(ast_mod, source)
        return None, _semantic_summary(ast_mod)

    def lower_stage():
        m = lower(ast_mod)
        detail = _cap(_pretty(m), 52) + "".join(
            f"\n\nhole contract: {h.contract.signature()}\n  source: {h.contract.source}"
            for h in iter_holes(m))
        return m, detail

    def codegen_stage():
        code = generate(module, target)
        return code, _cap(code, 60)

    with _LOCK:
        tokens, ok = stage("Lexical analysis", lex_stage)
        if not ok:
            blocked("Parsing", "Semantic analysis", "IR lowering", "LLM hole filling", "Code generation")
            return {"ok": True, "stages": stages, "narrated": False,
                    "ms": round((time.perf_counter() - t0) * 1000)}

        ast_mod, ok = stage("Parsing", parse_stage)
        if not ok:
            blocked("Semantic analysis", "IR lowering", "LLM hole filling", "Code generation")
            return {"ok": True, "stages": stages, "narrated": False,
                    "ms": round((time.perf_counter() - t0) * 1000)}

        _, ok = stage("Semantic analysis", semantic_stage)
        if not ok:
            blocked("IR lowering", "LLM hole filling", "Code generation")
            return {"ok": True, "stages": stages, "narrated": False,
                    "ms": round((time.perf_counter() - t0) * 1000)}

        module, ok = stage("IR lowering", lower_stage)
        if not ok:
            blocked("LLM hole filling", "Code generation")
            return {"ok": True, "stages": stages, "narrated": False,
                    "ms": round((time.perf_counter() - t0) * 1000)}

        holes = iter_holes(module)

        def fill_stage():
            if not holes:
                return None, "no semantic holes: the whole program lowered deterministically"
            if target == "c":
                raise CompileError("semantic holes (comprehensions/slices) are not supported "
                                   "for the C target in v1")
            records = _fill(module, [target], api_key, no_llm=False)
            lines = []
            for h in holes:
                rec = next((r for r in records if r["hole"] == h.hole_id), None)
                via = rec["via"] if rec else "?"
                tries = rec["attempts"] if rec else "?"
                lines.append(f"{h.contract.signature()}")
                lines.append(f"  filled via {via}, {tries} attempt(s), gates A/B/C passed")
            return None, "\n".join(lines)

        _, ok = stage("LLM hole filling", fill_stage)
        if not ok:
            blocked("Code generation")
        else:
            stage("Code generation", codegen_stage)

    narrated = False
    if api_key:
        notes = _narrate(stages, source, api_key)
        if notes:
            for s, note in zip(stages, notes):
                s["note"] = note
            narrated = True

    return {"ok": True, "stages": stages, "narrated": narrated,
            "ms": round((time.perf_counter() - t0) * 1000)}


_ROUTES = {"/api/transpile": api_transpile, "/api/selfcheck": api_selfcheck,
           "/api/pipeline": api_pipeline}


class Handler(BaseHTTPRequestHandler):
    # ---- static files -----------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/bg":            # background artwork under any common name
            for ext in ("jpg", "jpeg", "png", "webp"):
                file = STATIC / f"bg.{ext}"
                if file.is_file():
                    self._send(200, file.read_bytes(), MIME[f".{ext}"])
                    return
            self._send(404, b"drop the artwork at web/static/bg.jpg", "text/plain")
            return
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
