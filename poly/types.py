"""A tiny type lattice used by inference, the C back-end, and hole contracts.

Kinds: int, float, bool, str, none, list[elem], func(params)->ret, unknown.
Inference is best-effort and flow-insensitive — good enough to build hole
contracts and to give the C back-end concrete types (it errors on `unknown`).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Type:
    kind: str
    elem: "Type | None" = None          # for list
    params: tuple = field(default=())    # for func
    ret: "Type | None" = None            # for func

    def __str__(self) -> str:
        if self.kind == "list":
            return f"list[{self.elem or UNKNOWN}]"
        if self.kind == "func":
            ps = ", ".join(str(p) for p in self.params)
            return f"({ps}) -> {self.ret or UNKNOWN}"
        return self.kind


INT = Type("int")
FLOAT = Type("float")
BOOL = Type("bool")
STR = Type("str")
NONE = Type("none")
UNKNOWN = Type("unknown")


def list_of(elem: Type) -> Type:
    return Type("list", elem=elem)


def func(params: tuple[Type, ...], ret: Type) -> Type:
    return Type("func", params=tuple(params), ret=ret)


def is_numeric(t: Type) -> bool:
    return t.kind in ("int", "float", "bool")


def is_unknown(t: Type | None) -> bool:
    return t is None or t.kind == "unknown"


def numeric_result(a: Type, b: Type, op: str) -> Type:
    """Result type of an arithmetic op on two numeric operands."""
    if op == "/":
        return FLOAT                       # Python true division always yields float
    if a.kind == "float" or b.kind == "float":
        return FLOAT
    return INT                             # int/bool combinations collapse to int


def join(a: Type | None, b: Type | None) -> Type:
    """Least-surprising common type for two branches / list elements."""
    if a is None or is_unknown(a):
        return b or UNKNOWN
    if b is None or is_unknown(b):
        return a
    if a == b:
        return a
    if is_numeric(a) and is_numeric(b):
        return FLOAT if (a.kind == "float" or b.kind == "float") else INT
    return UNKNOWN
