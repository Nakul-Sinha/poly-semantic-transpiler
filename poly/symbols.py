"""Scoped symbol table.

One module scope plus one scope per function. Names assigned anywhere inside a
function are locals of that function (Python semantics), collected in a pre-pass so
forward references within a function do not trip the undeclared-name check.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import types as T


@dataclass
class Symbol:
    name: str
    type: T.Type
    kind: str  # 'var' | 'param' | 'func' | 'builtin'


# Builtins the subset recognizes. Return types marked UNKNOWN are refined by the
# analyzer at each call site (e.g. abs preserves its argument's numeric type).
BUILTIN_SIGNATURES: dict[str, T.Type] = {
    "print": T.func((T.UNKNOWN,), T.NONE),
    "len": T.func((T.UNKNOWN,), T.INT),
    "range": T.func((T.INT,), T.list_of(T.INT)),
    "abs": T.func((T.UNKNOWN,), T.UNKNOWN),
    "int": T.func((T.UNKNOWN,), T.INT),
    "float": T.func((T.UNKNOWN,), T.FLOAT),
    "str": T.func((T.UNKNOWN,), T.STR),
}


class Scope:
    def __init__(self, kind: str, parent: "Scope | None" = None):
        self.kind = kind          # 'module' | 'function'
        self.parent = parent
        self.symbols: dict[str, Symbol] = {}

    def define(self, sym: Symbol) -> None:
        self.symbols[sym.name] = sym

    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    def lookup(self, name: str) -> Symbol | None:
        scope: Scope | None = self
        while scope is not None:
            hit = scope.symbols.get(name)
            if hit is not None:
                return hit
            scope = scope.parent
        return None


def new_module_scope() -> Scope:
    scope = Scope("module")
    for name, sig in BUILTIN_SIGNATURES.items():
        scope.define(Symbol(name, sig, "builtin"))
    return scope
