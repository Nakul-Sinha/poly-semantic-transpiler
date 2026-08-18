"""The three validation gates every hole fill must pass.

Gate A  syntax        — does the fragment parse as valid target code?
Gate B  scope/interface — does it use only allowed names + no forbidden capability?
Gate C  behavioral    — does it compute the same thing as the original Python?

Each gate returns ``(ok: bool, message: str | None)``; on failure the message is
fed back into the LLM re-prompt loop (see client.py).
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

from ..codegen.javascript import RUNTIME as JS_RUNTIME
from ..differential import canon, eval_hole_source, gen_inputs, normalize

_IDENT = re.compile(r"(?<![.\w])([A-Za-z_$][\w$]*)")

# ---- Gate A: syntax ------------------------------------------------------


def gate_a_syntax(contract, body: str, target: str) -> tuple[bool, str | None]:
    params = ", ".join(contract.param_names)
    if target in ("py", "python"):
        indented = "\n".join("    " + ln for ln in body.splitlines())
        try:
            compile(f"def {contract.fn_name}({params}):\n{indented}\n", "<gateA>", "exec")
            return True, None
        except SyntaxError as exc:
            return False, f"Python syntax error: {exc.msg}"
    if target == "js":
        code = f"function {contract.fn_name}({params}) {{\n{body}\n}}\n"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(code)
            path = f.name
        try:
            res = subprocess.run(["node", "--check", path], capture_output=True, text=True)
            return (res.returncode == 0), (None if res.returncode == 0 else res.stderr.strip())
        finally:
            os.unlink(path)
    return False, f"no syntax gate for target {target!r}"


# ---- Gate B: scope / interface ------------------------------------------

_JS = {
    "keywords": {"return", "function", "const", "let", "var", "for", "of", "in", "if",
                 "else", "true", "false", "null", "undefined", "new", "typeof", "this", "while"},
    "builtins": {"poly_truthy", "poly_floordiv", "poly_mod", "poly_pow", "poly_repeat",
                 "poly_slice", "poly_str", "poly_repr", "poly_len", "poly_abs", "poly_range",
                 "poly_int", "poly_float", "poly_and", "poly_or", "Math"},
    "deny": {"require", "import", "fetch", "process", "eval", "Function", "global",
             "globalThis", "window", "XMLHttpRequest", "exec", "open", "child_process",
             "module", "document", "localStorage"},
}
_PY = {
    "keywords": {"return", "for", "in", "if", "else", "and", "or", "not", "True", "False", "None"},
    "builtins": {"range", "len", "abs", "int", "float", "str"},
    "deny": {"__import__", "eval", "exec", "open", "compile", "globals", "locals", "input",
             "__builtins__", "os", "sys", "subprocess", "import", "getattr", "setattr"},
}


def _declared_names(body: str, target: str) -> set[str]:
    names: set[str] = set()
    if target == "js":
        names |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*=>", body))          # single arrow param
        for grp in re.findall(r"\(([^)]*)\)\s*=>", body):                     # (a, b) => ...
            names |= {p.strip() for p in grp.split(",") if p.strip()}
        names |= set(re.findall(r"(?:let|const|var)\s+([A-Za-z_$][\w$]*)", body))
    else:
        names |= set(re.findall(r"for\s+([A-Za-z_]\w*)\s+in", body))          # comprehension var
    return names


def gate_b_scope(contract, body: str, target: str) -> tuple[bool, str | None]:
    spec = _JS if target == "js" else _PY
    allowed = set(contract.param_names) | spec["keywords"] | spec["builtins"] | _declared_names(body, target)
    for ident in _IDENT.findall(body):
        if ident in spec["deny"]:
            return False, f"uses forbidden capability {ident!r}"
        if ident in allowed:
            continue
        if ident.isdigit():
            continue
        return False, f"uses name {ident!r} not in scope (allowed: {sorted(contract.param_names)})"
    return True, None


# ---- Gate C: behavioral (differential) ----------------------------------


def gate_c_behavioral(contract, body: str, target: str) -> tuple[bool, str | None]:
    vectors = gen_inputs(contract.free_vars)
    expected = [canon(eval_hole_source(contract.source, vec)) for vec in vectors]
    if target in ("py", "python"):
        got = _run_py_helper(contract, body, vectors)
    elif target == "js":
        got = _run_js_helper(contract, body, vectors)
    else:
        return False, f"no behavioral gate for target {target!r}"
    for vec, exp, act in zip(vectors, expected, got):
        if normalize(exp) != normalize(act):
            return False, (f"on input {vec}: Python gives {exp!r} but {target} gives {act!r}")
    return True, None


def _run_py_helper(contract, body: str, vectors: list[dict]) -> list[str]:
    params = ", ".join(contract.param_names)
    indented = "\n".join("    " + ln for ln in body.splitlines())
    glb = {"__builtins__": {}, "range": range, "len": len, "abs": abs,
           "int": int, "float": float, "str": str}
    exec(compile(f"def {contract.fn_name}({params}):\n{indented}\n", "<gateC>", "exec"), glb)
    fn = glb[contract.fn_name]
    out = []
    for vec in vectors:
        out.append(canon(fn(*[vec[n] for n in contract.param_names])))
    return out


def _run_js_helper(contract, body: str, vectors: list[dict]) -> list[str]:
    params = ", ".join(contract.param_names)
    cases = ", ".join(
        "[" + ", ".join(_to_js_literal(vec[n]) for n in contract.param_names) + "]"
        for vec in vectors
    )
    program = (
        JS_RUNTIME + "\n"
        + f"function {contract.fn_name}({params}) {{\n{body}\n}}\n"
        + f"const _cases = [{cases}];\n"
        + f"for (const c of _cases) {{ console.log(poly_str({contract.fn_name}.apply(null, c))); }}\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(program)
        path = f.name
    try:
        res = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(res.stderr)
        return res.stdout.splitlines()
    finally:
        os.unlink(path)


def _to_js_literal(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, str):
        import json
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(_to_js_literal(e) for e in v) + "]"
    return repr(v)


ALL_GATES = (("A syntax", gate_a_syntax), ("B scope", gate_b_scope), ("C behavioral", gate_c_behavioral))
