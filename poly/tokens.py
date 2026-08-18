"""Token kinds and the Token record produced by the lexer."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .errors import Span


class Tok(Enum):
    # literals / identifiers
    NAME = auto()
    NUMBER = auto()      # value is int or float
    STRING = auto()      # plain string literal
    FSTRING = auto()     # f-string; value is the raw inner text (no f/quotes)
    # keywords (value holds the keyword text)
    KEYWORD = auto()
    # operators & punctuation (value holds the operator text)
    OP = auto()
    # layout
    NEWLINE = auto()
    INDENT = auto()
    DEDENT = auto()
    EOF = auto()


KEYWORDS = frozenset({
    "def", "return", "if", "elif", "else", "while", "for", "in",
    "and", "or", "not", "True", "False", "None",
    "pass", "break", "continue",
})
# NB: builtins like range/len/print/abs/int/float/str are ordinary NAME tokens,
# resolved during semantic analysis — not keywords.

# Multi-character operators must be tried longest-first.
OPERATORS = [
    "**", "//=", "//", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "->",
    "+", "-", "*", "/", "%", "<", ">", "=", "(", ")", "[", "]", ":", ",", ".",
]


@dataclass
class Token:
    kind: Tok
    value: object
    span: Span

    def __repr__(self) -> str:  # compact, useful in --dump-tokens
        v = self.value
        return f"{self.kind.name}({v!r})" if v is not None else self.kind.name
