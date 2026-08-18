"""Turn an AST expression back into Python source text.

Used to capture the exact original source of a semantic hole (for the interpreter
oracle and for Gate C differential testing). Fully parenthesized so precedence is
never ambiguous.
"""
from __future__ import annotations

from . import ast_nodes as A


def unparse_expr(n) -> str:
    if isinstance(n, A.Num):
        return repr(n.value)
    if isinstance(n, A.Str):
        return repr(n.value)
    if isinstance(n, A.Const):
        return repr(n.value)  # True / False / None
    if isinstance(n, A.Name):
        return n.id
    if isinstance(n, A.ListExpr):
        return "[" + ", ".join(unparse_expr(e) for e in n.elems) + "]"
    if isinstance(n, A.BinOp):
        return f"({unparse_expr(n.left)} {n.op} {unparse_expr(n.right)})"
    if isinstance(n, A.UnaryOp):
        if n.op == "not":
            return f"(not {unparse_expr(n.operand)})"
        return f"({n.op}{unparse_expr(n.operand)})"
    if isinstance(n, A.BoolOp):
        return "(" + f" {n.op} ".join(unparse_expr(v) for v in n.values) + ")"
    if isinstance(n, A.Compare):
        out = unparse_expr(n.left)
        for op, comp in zip(n.ops, n.comparators):
            out += f" {op} {unparse_expr(comp)}"
        return "(" + out + ")"
    if isinstance(n, A.Call):
        return unparse_expr(n.func) + "(" + ", ".join(unparse_expr(a) for a in n.args) + ")"
    if isinstance(n, A.Attribute):
        return unparse_expr(n.obj) + "." + n.attr
    if isinstance(n, A.Subscript):
        return f"{unparse_expr(n.obj)}[{unparse_expr(n.index)}]"
    if isinstance(n, A.SliceExpr):
        lo = unparse_expr(n.lower) if n.lower is not None else ""
        hi = unparse_expr(n.upper) if n.upper is not None else ""
        if n.step is not None:
            return f"{unparse_expr(n.obj)}[{lo}:{hi}:{unparse_expr(n.step)}]"
        return f"{unparse_expr(n.obj)}[{lo}:{hi}]"
    if isinstance(n, A.Comprehension):
        base = f"[{unparse_expr(n.element)} for {n.var} in {unparse_expr(n.iter)}"
        if n.cond is not None:
            base += f" if {unparse_expr(n.cond)}"
        return base + "]"
    raise TypeError(f"cannot unparse {type(n).__name__}")
