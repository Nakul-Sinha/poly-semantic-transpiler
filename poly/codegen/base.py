"""Shared code-generation utilities: an indentation-aware emitter and an IR walk."""
from __future__ import annotations

from .. import ir


class Emitter:
    """Accumulates indented lines of target source."""

    def __init__(self, unit: str = "  "):
        self.lines: list[str] = []
        self.level = 0
        self.unit = unit

    def line(self, text: str = "") -> None:
        self.lines.append((self.unit * self.level + text) if text else "")

    def raw(self, text: str) -> None:
        self.lines.append(text)

    def indent(self) -> None:
        self.level += 1

    def dedent(self) -> None:
        self.level -= 1

    def code(self) -> str:
        return "\n".join(self.lines) + "\n"


def iter_holes(module: ir.Module) -> list[ir.Hole]:
    """Every Hole in the module, in a stable order (for emitting helper defs)."""
    holes: list[ir.Hole] = []
    seen: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, ir.Hole):
            if node.hole_id not in seen:
                seen.add(node.hole_id)
                holes.append(node)
            return
        for _, v in vars(node).items():
            if isinstance(v, list):
                for x in v:
                    if hasattr(x, "__dataclass_fields__"):
                        walk(x)
            elif hasattr(v, "__dataclass_fields__"):
                walk(v)

    for fn in module.funcs:
        for s in fn.body:
            walk(s)
    for s in module.body:
        walk(s)
    return holes
