"""Differential testing harness — the correctness backbone.

Two jobs:
  * whole-program 3-way self-check: CPython(source) vs IR interpreter vs each
    target's compiled/run output (validates lowering, interpretation, and codegen);
  * primitives reused by the LLM Gate C: type-directed input generation, runners
    for node/python/gcc, numeric-normalized comparison, and a Python-matching
    canonical string form.

Cross-language *numeric normalization*: every number in an output is canonicalized
to ``repr(float(n))`` before comparison, so ``3`` and ``3.0`` compare equal across
languages while a real value bug (``3`` vs ``3.5``) still differs. This is documented
high-confidence QA — sampling, not a proof.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from . import ir, types as T
from .codegen import generate
from .errors import CompileError
from .interp import interpret

_NUM = re.compile(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?|[-+]?\d+(?:[eE][-+]?\d+)?")
_SAFE_EVAL = {"len": len, "abs": abs, "int": int, "float": float, "str": str,
              "range": range, "True": True, "False": False, "None": None}


# ---- comparison ----------------------------------------------------------
def normalize(text: str) -> str:
    """Canonicalize numbers so integer/float display differences don't matter."""
    return _NUM.sub(lambda m: repr(float(m.group())), text.strip())


def outputs_match(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)


def canon(v) -> str:
    """Render a value exactly as the target runtimes' poly_str does (== Python str)."""
    if v is True:
        return "True"
    if v is False:
        return "False"
    if v is None:
        return "None"
    if isinstance(v, list):
        return "[" + ", ".join(_canon_repr(e) for e in v) + "]"
    return str(v)


def _canon_repr(v) -> str:
    return "'" + v + "'" if isinstance(v, str) else canon(v)


# ---- tool availability ---------------------------------------------------
def have(tool: str) -> bool:
    return shutil.which(tool) is not None


TARGET_TOOL = {"js": "node", "py": "python", "python": "python", "c": "gcc"}


# ---- runners -------------------------------------------------------------
def run_cpython_source(src: str) -> str:
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(src, "<source>", "exec"), {})   # noqa: S102 (running the user's own program)
    return buf.getvalue()


def run_js(code: str) -> str:
    return _run_temp(code, ".js", lambda p: ["node", p])


def run_py(code: str) -> str:
    return _run_temp(code, ".py", lambda p: ["python", p])


def run_c(code: str) -> str:
    d = tempfile.mkdtemp(prefix="poly_c_")
    cpath = os.path.join(d, "prog.c")
    exe = os.path.join(d, "prog.exe")
    try:
        with open(cpath, "w") as f:
            f.write(code)
        comp = subprocess.run(["gcc", "-std=c99", "-O2", cpath, "-o", exe, "-lm"],
                              capture_output=True, text=True)
        if comp.returncode != 0:
            raise RuntimeError(f"C compilation failed:\n{comp.stderr}")
        run = subprocess.run([exe], capture_output=True, text=True, timeout=30)
        return run.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _run_temp(code: str, suffix: str, cmd) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as f:
        f.write(code)
        path = f.name
    try:
        res = subprocess.run(cmd(path), capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(res.stderr)
        return res.stdout
    finally:
        os.unlink(path)


_RUNNER = {"js": run_js, "py": run_py, "python": run_py, "c": run_c}


def run_target(module: ir.Module, target: str) -> str:
    return _RUNNER[target](generate(module, target))


# ---- type-directed input generation (for Gate C) -------------------------
_SAMPLES = {
    "int": [0, 1, -1, 2, 7, -4, 100],
    "float": [0.0, 1.5, -2.5, 3.0, 10.0],
    "bool": [True, False],
    "str": ["", "a", "abc", "Hello"],
}


def _samples_for(t: T.Type) -> list:
    if t.kind in _SAMPLES:
        return list(_SAMPLES[t.kind])
    if t.kind == "list":
        return [[], [0], [1, 2, 3], [5, 4, 3, 2, 1], [-1, -2, 3], [2, 2, 2, 2]]
    return [0]


def gen_inputs(free_vars: list) -> list[dict]:
    """A handful of type-directed test vectors over the hole's free variables."""
    if not free_vars:
        return [{}]
    columns = {v.name: _samples_for(v.type) for v in free_vars}
    k = max(len(c) for c in columns.values())
    vectors = []
    for i in range(k):
        vectors.append({name: vals[i % len(vals)] for name, vals in columns.items()})
    return vectors


def eval_hole_source(source: str, env: dict):
    return eval(compile(source, "<hole>", "eval"), {"__builtins__": {}, **_SAFE_EVAL}, dict(env))


# ---- whole-program 3-way self-check --------------------------------------
def self_check(src: str, module: ir.Module, targets=("js", "py", "c")) -> dict:
    """Compare CPython(source) vs IR interpreter vs each target. `module` must be
    lowered and (if it has holes) already filled."""
    reference = run_cpython_source(src)
    rows = []

    ir_out = interpret(module)
    rows.append({"name": "IR interpreter", "status": "pass" if outputs_match(ir_out, reference)
                 else "FAIL", "output": ir_out})

    for tgt in targets:
        tool = TARGET_TOOL[tgt]
        if not have(tool):
            rows.append({"name": f"{tgt} target", "status": "skipped",
                         "output": f"({tool} not found)"})
            continue
        try:
            out = run_target(module, tgt)
            status = "pass" if outputs_match(out, reference) else "FAIL"
            rows.append({"name": f"{tgt} target", "status": status, "output": out})
        except CompileError as exc:   # unsupported feature for this target -> skip, don't fail
            rows.append({"name": f"{tgt} target", "status": "skipped", "output": str(exc)})
        except Exception as exc:      # genuine compile/run error
            rows.append({"name": f"{tgt} target", "status": "ERROR", "output": str(exc)})

    ok = all(r["status"] in ("pass", "skipped") for r in rows)
    return {"reference": reference, "rows": rows, "ok": ok}
