"""Source spans and the Poly error hierarchy.

Every token and AST node carries a :class:`Span`; every diagnostic can render the
offending source line with a caret, which makes the compiler pleasant to demo.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A half-open region of source text (1-based lines, 0-based columns)."""
    line: int
    col: int
    end_line: int = 0
    end_col: int = 0

    def __post_init__(self) -> None:
        if self.end_line == 0:
            object.__setattr__(self, "end_line", self.line)
        if self.end_col == 0:
            object.__setattr__(self, "end_col", self.col + 1)

    def to(self, other: "Span") -> "Span":
        """Span covering from the start of ``self`` to the end of ``other``."""
        return Span(self.line, self.col, other.end_line, other.end_col)


class PolyError(Exception):
    """Base class for all compiler diagnostics."""

    stage = "error"

    def __init__(self, message: str, span: Span | None = None):
        super().__init__(message)
        self.message = message
        self.span = span

    def render(self, source: str | None = None) -> str:
        loc = f" (line {self.span.line}, col {self.span.col + 1})" if self.span else ""
        out = f"{self.stage}: {self.message}{loc}"
        if source and self.span:
            lines = source.splitlines()
            if 1 <= self.span.line <= len(lines):
                src_line = lines[self.span.line - 1]
                caret = " " * self.span.col + "^"
                out += f"\n    {src_line}\n    {caret}"
        return out


class LexError(PolyError):
    stage = "lex error"


class ParseError(PolyError):
    stage = "parse error"


class SemanticError(PolyError):
    stage = "semantic error"


class CompileError(PolyError):
    """Raised when a construct cannot be lowered/emitted (e.g. impure hole, bad target)."""
    stage = "compile error"
