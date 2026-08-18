"""AST node definitions (dataclasses).

Every node carries a :class:`Span`. Semantic analysis later attaches two dynamic
attributes in place:
    node.type  -> a poly.types.Type   (expressions)
    node.pure  -> bool                (expressions / subtrees; hole eligibility)
These are not declared as fields to keep the constructors focused on syntax.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .errors import Span

# --- statements -----------------------------------------------------------


@dataclass
class Module:
    body: list = field(default_factory=list)
    span: Span = Span(1, 0)


@dataclass
class Param:
    name: str
    annotation: object  # Expr | None  (e.g. Name('int') or Subscript(Name('list'), Name('int')))
    default: object     # Expr | None
    span: Span


@dataclass
class FunctionDef:
    name: str
    params: list
    body: list
    returns: object     # Expr | None  (return-type annotation)
    span: Span


@dataclass
class Assign:
    target: object   # Name | Subscript
    value: object
    span: Span


@dataclass
class AugAssign:
    target: object
    op: str          # '+', '-', '*', '/', '//'
    value: object
    span: Span


@dataclass
class ExprStmt:
    value: object
    span: Span


@dataclass
class If:
    test: object
    body: list
    orelse: list
    span: Span


@dataclass
class While:
    test: object
    body: list
    span: Span


@dataclass
class For:
    var: str
    iter: object     # Call(range,...) | list-typed Expr
    body: list
    span: Span


@dataclass
class Return:
    value: object    # Expr | None
    span: Span


@dataclass
class Pass:
    span: Span


@dataclass
class Break:
    span: Span


@dataclass
class Continue:
    span: Span


# --- expressions ----------------------------------------------------------


@dataclass
class Num:
    value: object    # int | float
    span: Span


@dataclass
class Str:
    value: str
    span: Span


@dataclass
class Const:
    value: object    # True | False | None
    span: Span


@dataclass
class Name:
    id: str
    span: Span


@dataclass
class ListExpr:
    elems: list
    span: Span


@dataclass
class BinOp:
    op: str
    left: object
    right: object
    span: Span


@dataclass
class UnaryOp:
    op: str          # '-' | 'not' | '+'
    operand: object
    span: Span


@dataclass
class BoolOp:
    op: str          # 'and' | 'or'
    values: list
    span: Span


@dataclass
class Compare:
    left: object
    ops: list        # list[str]; chained, e.g. a < b < c
    comparators: list
    span: Span


@dataclass
class Call:
    func: object     # Name | Attribute
    args: list
    span: Span


@dataclass
class Attribute:
    obj: object
    attr: str
    span: Span


@dataclass
class Subscript:
    obj: object
    index: object
    span: Span


@dataclass
class SliceExpr:
    obj: object
    lower: object    # Expr | None
    upper: object    # Expr | None
    step: object     # Expr | None
    span: Span


@dataclass
class Comprehension:
    element: object
    var: str
    iter: object
    cond: object     # Expr | None
    span: Span
