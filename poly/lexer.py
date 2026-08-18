"""Hand-written lexer for the Python subset.

Responsibilities that make this more than a regex split:
  * significant indentation via an indent stack -> INDENT / DEDENT tokens
  * bracket-aware implicit line joining (newlines inside (), [] are whitespace)
  * comments and blank lines that do not disturb indentation
  * longest-match operators, numbers (int/float), and escaped string literals
"""
from __future__ import annotations

from .errors import LexError, Span
from .tokens import KEYWORDS, OPERATORS, Tok, Token


class Lexer:
    def __init__(self, source: str):
        self.src = source
        self.n = len(source)
        self.i = 0
        self.line = 1
        self.col = 0
        self.indents: list[int] = [0]
        self.bracket_depth = 0
        self.at_line_start = True
        self.out: list[Token] = []
        self.emitted_real_token_on_line = False

    # ---- low-level cursor -------------------------------------------------
    def _peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.src[j] if j < self.n else ""

    def _advance(self) -> str:
        ch = self.src[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
            self.col = 0
        else:
            self.col += 1
        return ch

    def _here(self) -> Span:
        return Span(self.line, self.col)

    def _emit(self, kind: Tok, value: object, span: Span) -> None:
        self.out.append(Token(kind, value, span))

    # ---- main loop --------------------------------------------------------
    def tokenize(self) -> list[Token]:
        while self.i < self.n:
            if self.at_line_start and self.bracket_depth == 0:
                self._handle_line_start()
                if self.i >= self.n:
                    break
                continue
            ch = self._peek()
            if ch == "\n":
                self._advance()
                if self.bracket_depth == 0 and self.emitted_real_token_on_line:
                    self._emit(Tok.NEWLINE, None, self._here())
                    self.emitted_real_token_on_line = False
                    self.at_line_start = True
                continue
            if ch in " \t":
                self._advance()
                continue
            if ch == "#":
                self._skip_comment()
                continue
            self._scan_token()

        # end of file: close the last logical line and all open blocks
        if self.emitted_real_token_on_line:
            self._emit(Tok.NEWLINE, None, self._here())
        while len(self.indents) > 1:
            self.indents.pop()
            self._emit(Tok.DEDENT, None, self._here())
        self._emit(Tok.EOF, None, self._here())
        return self.out

    # ---- indentation ------------------------------------------------------
    def _handle_line_start(self) -> None:
        start_i = self.i
        width = 0
        while self._peek() in " \t":
            if self._peek() == "\t":
                raise LexError("tabs are not allowed for indentation; use spaces", self._here())
            self._advance()
            width += 1
        ch = self._peek()
        if ch == "" or ch == "\n" or ch == "#":
            # blank or comment-only line: does not affect indentation
            if ch == "#":
                self._skip_comment()
            if self._peek() == "\n":
                self._advance()
            return
        self.at_line_start = False
        top = self.indents[-1]
        if width > top:
            self.indents.append(width)
            self._emit(Tok.INDENT, None, Span(self.line, 0))
        elif width < top:
            while self.indents and width < self.indents[-1]:
                self.indents.pop()
                self._emit(Tok.DEDENT, None, Span(self.line, 0))
            if not self.indents or self.indents[-1] != width:
                raise LexError("inconsistent indentation", Span(self.line, 0))
        _ = start_i  # (kept for readability; width is what matters)

    def _skip_comment(self) -> None:
        while self._peek() not in ("", "\n"):
            self._advance()

    # ---- token scanners ---------------------------------------------------
    def _scan_token(self) -> None:
        self.emitted_real_token_on_line = True
        ch = self._peek()
        if ch.isdigit() or (ch == "." and self._peek(1).isdigit()):
            self._scan_number()
        elif ch.isalpha() or ch == "_":
            self._scan_name()
        elif ch in "\"'":
            self._scan_string()
        else:
            self._scan_operator()

    def _scan_number(self) -> None:
        span = self._here()
        text = ""
        is_float = False
        while self._peek().isdigit():
            text += self._advance()
        if self._peek() == ".":
            is_float = True
            text += self._advance()
            while self._peek().isdigit():
                text += self._advance()
        if self._peek() in "eE":
            is_float = True
            text += self._advance()
            if self._peek() in "+-":
                text += self._advance()
            if not self._peek().isdigit():
                raise LexError("malformed exponent in number", self._here())
            while self._peek().isdigit():
                text += self._advance()
        value: object = float(text) if is_float else int(text)
        self._emit(Tok.NUMBER, value, span)

    def _scan_name(self) -> None:
        span = self._here()
        # guard: f-strings are future work, not silently mis-lexed
        if self._peek() in "fF" and self._peek(1) in "\"'":
            raise LexError("f-strings are not supported in this subset (future work)", span)
        text = ""
        while self._peek().isalnum() or self._peek() == "_":
            text += self._advance()
        kind = Tok.KEYWORD if text in KEYWORDS else Tok.NAME
        self._emit(kind, text, span)

    def _scan_string(self) -> None:
        span = self._here()
        quote = self._advance()
        chars: list[str] = []
        while True:
            ch = self._peek()
            if ch == "":
                raise LexError("unterminated string literal", span)
            if ch == "\n":
                raise LexError("unterminated string literal (newline in string)", span)
            self._advance()
            if ch == quote:
                break
            if ch == "\\":
                esc = self._advance()
                chars.append({"n": "\n", "t": "\t", "\\": "\\",
                              '"': '"', "'": "'", "r": "\r", "0": "\0"}.get(esc, esc))
            else:
                chars.append(ch)
        self._emit(Tok.STRING, "".join(chars), span)

    def _scan_operator(self) -> None:
        span = self._here()
        for op in OPERATORS:
            if self.src.startswith(op, self.i):
                for _ in op:
                    self._advance()
                if op in "([":
                    self.bracket_depth += 1
                elif op in ")]":
                    self.bracket_depth = max(0, self.bracket_depth - 1)
                self._emit(Tok.OP, op, span)
                return
        raise LexError(f"unexpected character {self._peek()!r}", span)


def tokenize(source: str) -> list[Token]:
    return Lexer(source).tokenize()
