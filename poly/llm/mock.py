"""Offline mock filler — a deterministic *test double* for the LLM.

Its only purpose is to let CI and graders run the full hole pipeline (contract ->
candidate -> gates A/B/C -> splice) without an API key. It is NOT "the product":
in live mode the Claude API fills holes instead. Whatever fills a hole, the result
is accepted only after passing all three gates.

The mock reparses the hole's original Python source and translates it, reusing a
small Python-expression -> JS translator for the in-subset parts (arithmetic,
comparisons, etc.), so only the construct *shape* (comprehension / slice) is what
gets "delegated".
"""
from __future__ import annotations

import json

from .. import ast_nodes as A
from ..lexer import tokenize
from ..parser import parse

_CMP = {"==": "===", "!=": "!==", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
_JS_BUILTIN = {"len": "poly_len", "abs": "poly_abs", "int": "poly_int",
               "float": "poly_float", "str": "poly_str", "range": "poly_range"}


def _parse_expr(source: str):
    module = parse(tokenize("__hole__ = " + source + "\n"))
    return module.body[0].value


def propose(contract, target: str) -> str:
    """Return the *body* of the helper function for this hole and target."""
    node = _parse_expr(contract.source)
    if target in ("py", "python"):
        return f"return {contract.source}"
    if target == "js":
        if isinstance(node, A.Comprehension):
            return _js_comprehension(node)
        if isinstance(node, A.SliceExpr):
            return _js_slice(node)
        raise ValueError(f"mock: unsupported hole kind for source {contract.source!r}")
    raise ValueError(f"mock: no offline translation for target {target!r}")


def _js_comprehension(node: A.Comprehension) -> str:
    it = _to_js(node.iter)
    elem = _to_js(node.element)
    if node.cond is not None:
        cond = _to_js(node.cond)
        return f"return {it}.filter({node.var} => poly_truthy({cond})).map({node.var} => {elem});"
    return f"return {it}.map({node.var} => {elem});"


def _js_slice(node: A.SliceExpr) -> str:
    obj = _to_js(node.obj)
    lo = _to_js(node.lower) if node.lower is not None else "null"
    hi = _to_js(node.upper) if node.upper is not None else "null"
    step = _to_js(node.step) if node.step is not None else "null"
    return f"return poly_slice({obj}, {lo}, {hi}, {step});"


def _to_js(n) -> str:
    """Type-agnostic Python-expression -> JS translator for the in-subset parts."""
    if isinstance(n, A.Num):
        return repr(n.value)
    if isinstance(n, A.Str):
        return json.dumps(n.value)
    if isinstance(n, A.Const):
        return {True: "true", False: "false", None: "null"}[n.value]
    if isinstance(n, A.Name):
        return n.id
    if isinstance(n, A.BinOp):
        l, r = _to_js(n.left), _to_js(n.right)
        if n.op == "//":
            return f"poly_floordiv({l}, {r})"
        if n.op == "%":
            return f"poly_mod({l}, {r})"
        if n.op == "**":
            return f"poly_pow({l}, {r})"
        return f"({l} {n.op} {r})"
    if isinstance(n, A.UnaryOp):
        o = _to_js(n.operand)
        return f"(!poly_truthy({o}))" if n.op == "not" else f"({n.op}{o})"
    if isinstance(n, A.BoolOp):
        fn = "poly_and" if n.op == "and" else "poly_or"
        parts = [_to_js(v) for v in n.values]

        def fold(items):
            return items[0] if len(items) == 1 else f"{fn}(() => {items[0]}, () => {fold(items[1:])})"

        return fold(parts)
    if isinstance(n, A.Compare):
        out = _to_js(n.left)
        for op, comp in zip(n.ops, n.comparators):
            out = f"({out} {_CMP[op]} {_to_js(comp)})"
        return out
    if isinstance(n, A.Call) and isinstance(n.func, A.Name):
        fn = _JS_BUILTIN.get(n.func.id, n.func.id)
        return f"{fn}(" + ", ".join(_to_js(a) for a in n.args) + ")"
    if isinstance(n, A.Subscript):
        return f"{_to_js(n.obj)}[{_to_js(n.index)}]"
    raise ValueError(f"mock: cannot translate {type(n).__name__} to JS")
