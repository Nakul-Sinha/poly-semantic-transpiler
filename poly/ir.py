"""The language-agnostic Semantic IR.

Smaller and more normalized than the AST: augmented assignment, chained
comparison, and the two Python ``for`` forms have all been desugared during
lowering, so every back-end and the interpreter see the same simple tree.

A :class:`Hole` stands in for an unsupported-but-pure subtree; it carries a
:class:`HoleContract` (compiler-derived facts) and, once the LLM layer has run,
``filled[target]`` holds the validated helper-function body.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import types as T

# --- statements -----------------------------------------------------------


@dataclass
class Module:
    body: list       # top-level statements (run as `main`)
    funcs: list       # list[Function]


@dataclass
class Param:
    name: str
    type: T.Type
    default: object   # Expr | None


@dataclass
class Function:
    name: str
    params: list
    body: list
    ret: T.Type


@dataclass
class Assign:
    target: object    # Name | Index
    value: object


@dataclass
class ExprStmt:
    value: object


@dataclass
class If:
    test: object
    body: list
    orelse: list


@dataclass
class While:
    test: object
    body: list


@dataclass
class For:
    var: str
    iterable: object  # Range | list-typed Expr
    body: list


@dataclass
class Return:
    value: object     # Expr | None


@dataclass
class Break:
    pass


@dataclass
class Continue:
    pass


@dataclass
class Pass:
    pass


# --- expressions ----------------------------------------------------------


@dataclass
class Const:
    value: object
    type: T.Type


@dataclass
class Name:
    id: str
    type: T.Type


@dataclass
class ListLit:
    elems: list
    type: T.Type


@dataclass
class BinOp:
    op: str
    left: object
    right: object
    type: T.Type


@dataclass
class UnaryOp:
    op: str
    operand: object
    type: T.Type


@dataclass
class BoolOp:
    op: str           # 'and' | 'or'
    values: list
    type: T.Type


@dataclass
class Compare:
    op: str           # single comparison; chains are desugared to BoolOp(and, ...)
    left: object
    right: object
    type: T.Type


@dataclass
class Call:
    func: str         # builtin or user-function name
    args: list
    type: T.Type


@dataclass
class MethodCall:
    obj: object
    method: str       # 'append'
    args: list
    type: T.Type


@dataclass
class Index:
    obj: object
    index: object
    type: T.Type


@dataclass
class Range:
    start: object
    stop: object
    step: object
    type: T.Type = field(default_factory=lambda: T.list_of(T.INT))


# --- holes ----------------------------------------------------------------


@dataclass
class VarInfo:
    name: str
    type: T.Type


@dataclass
class HoleContract:
    hole_id: str
    kind: str              # 'list_comprehension' | 'slice'
    source: str            # original Python text of the subtree
    free_vars: list        # list[VarInfo] the fragment may read
    result_type: T.Type
    fn_name: str           # compiler-allocated helper name
    param_names: list      # == [v.name for v in free_vars]

    def signature(self) -> str:
        ps = ", ".join(f"{v.name}: {v.type}" for v in self.free_vars)
        return f"{self.fn_name}({ps}) -> {self.result_type}"


@dataclass
class Hole:
    hole_id: str
    contract: HoleContract
    type: T.Type
    filled: dict = field(default_factory=dict)   # target -> helper body source
