"""Recursive-descent parser (statements) + precedence-climbing (expressions).

Grammar is documented in docs/LANGUAGE-SPEC.md. The parser is deliberately small:
statements are parsed by dedicated methods; expressions climb a fixed precedence
ladder (or -> and -> not -> comparison -> +/- -> */// -> unary -> ** -> trailers).
"""
from __future__ import annotations

from . import ast_nodes as A
from .errors import ParseError, Span
from .tokens import Tok, Token

AUG_OPS = {"+=", "-=", "*=", "/=", "//="}
COMPARE_OPS = {"==", "!=", "<", "<=", ">", ">="}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.pos = 0

    # ---- cursor helpers ---------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.toks[self.pos]

    def _advance(self) -> Token:
        t = self.toks[self.pos]
        if t.kind is not Tok.EOF:
            self.pos += 1
        return t

    def _is_op(self, v: str) -> bool:
        return self.cur.kind is Tok.OP and self.cur.value == v

    def _is_kw(self, v: str) -> bool:
        return self.cur.kind is Tok.KEYWORD and self.cur.value == v

    def _expect_op(self, v: str) -> Token:
        if not self._is_op(v):
            raise ParseError(f"expected {v!r}, got {self._describe()}", self.cur.span)
        return self._advance()

    def _expect_kw(self, v: str) -> Token:
        if not self._is_kw(v):
            raise ParseError(f"expected keyword {v!r}, got {self._describe()}", self.cur.span)
        return self._advance()

    def _expect(self, kind: Tok) -> Token:
        if self.cur.kind is not kind:
            raise ParseError(f"expected {kind.name}, got {self._describe()}", self.cur.span)
        return self._advance()

    def _describe(self) -> str:
        t = self.cur
        return t.kind.name if t.value is None else f"{t.kind.name} {t.value!r}"

    # ---- entry ------------------------------------------------------------
    def parse(self) -> A.Module:
        body: list = []
        while self.cur.kind is not Tok.EOF:
            body.append(self._statement())
        span = body[0].span if body else Span(1, 0)
        return A.Module(body, span)

    # ---- statements -------------------------------------------------------
    def _statement(self):
        if self._is_kw("def"):
            return self._func_def()
        if self._is_kw("if"):
            return self._if_stmt()
        if self._is_kw("while"):
            return self._while_stmt()
        if self._is_kw("for"):
            return self._for_stmt()
        node = self._simple_stmt()
        self._expect(Tok.NEWLINE)
        return node

    def _block(self) -> list:
        self._expect(Tok.NEWLINE)
        self._expect(Tok.INDENT)
        stmts: list = []
        while self.cur.kind not in (Tok.DEDENT, Tok.EOF):
            stmts.append(self._statement())
        self._expect(Tok.DEDENT)
        if not stmts:
            raise ParseError("expected an indented block", self.cur.span)
        return stmts

    def _func_def(self):
        start = self._expect_kw("def")
        name = self._expect(Tok.NAME).value
        self._expect_op("(")
        params: list = []
        if not self._is_op(")"):
            params.append(self._param())
            while self._is_op(","):
                self._advance()
                params.append(self._param())
        self._expect_op(")")
        returns = None
        if self._is_op("->"):
            self._advance()
            returns = self._type_annotation()
        self._expect_op(":")
        body = self._block()
        # trailing-defaults-only check
        seen_default = False
        for p in params:
            if p.default is not None:
                seen_default = True
            elif seen_default:
                raise ParseError("non-default parameter follows default parameter", p.span)
        return A.FunctionDef(name, params, body, returns, start.span)

    def _param(self) -> A.Param:
        t = self._expect(Tok.NAME)
        annotation = None
        if self._is_op(":"):
            self._advance()
            annotation = self._type_annotation()
        default = None
        if self._is_op("="):
            self._advance()
            default = self._expr()
        return A.Param(t.value, annotation, default, t.span)

    def _type_annotation(self):
        """A type is a NAME optionally subscripted once, e.g. int, str, list[int]."""
        t = self._expect(Tok.NAME)
        node = A.Name(t.value, t.span)
        if self._is_op("["):
            self._advance()
            elem = self._expect(Tok.NAME)
            self._expect_op("]")
            node = A.Subscript(node, A.Name(elem.value, elem.span), t.span)
        return node

    def _if_stmt(self):
        start = self._expect_kw("if")
        test = self._expr()
        self._expect_op(":")
        body = self._block()
        orelse = self._elif_or_else()
        return A.If(test, body, orelse, start.span)

    def _elif_or_else(self) -> list:
        if self._is_kw("elif"):
            start = self._expect_kw("elif")
            test = self._expr()
            self._expect_op(":")
            body = self._block()
            orelse = self._elif_or_else()
            return [A.If(test, body, orelse, start.span)]
        if self._is_kw("else"):
            self._advance()
            self._expect_op(":")
            return self._block()
        return []

    def _while_stmt(self):
        start = self._expect_kw("while")
        test = self._expr()
        self._expect_op(":")
        body = self._block()
        return A.While(test, body, start.span)

    def _for_stmt(self):
        start = self._expect_kw("for")
        var = self._expect(Tok.NAME).value
        self._expect_kw("in")
        it = self._expr()
        self._expect_op(":")
        body = self._block()
        return A.For(var, it, body, start.span)

    def _simple_stmt(self):
        if self._is_kw("return"):
            start = self._advance()
            value = None if self.cur.kind is Tok.NEWLINE else self._expr()
            return A.Return(value, start.span)
        if self._is_kw("pass"):
            return A.Pass(self._advance().span)
        if self._is_kw("break"):
            return A.Break(self._advance().span)
        if self._is_kw("continue"):
            return A.Continue(self._advance().span)
        expr = self._expr()
        if self._is_op("="):
            self._advance()
            value = self._expr()
            self._check_target(expr)
            return A.Assign(expr, value, expr.span)
        if self.cur.kind is Tok.OP and self.cur.value in AUG_OPS:
            op = self._advance().value[:-1]  # strip '='
            value = self._expr()
            self._check_target(expr)
            return A.AugAssign(expr, op, value, expr.span)
        return A.ExprStmt(expr, expr.span)

    def _check_target(self, node) -> None:
        if not isinstance(node, (A.Name, A.Subscript)):
            raise ParseError("invalid assignment target", node.span)

    # ---- expressions (precedence climbing) --------------------------------
    def _expr(self):
        return self._or_expr()

    def _or_expr(self):
        left = self._and_expr()
        if self._is_kw("or"):
            values = [left]
            while self._is_kw("or"):
                self._advance()
                values.append(self._and_expr())
            return A.BoolOp("or", values, left.span)
        return left

    def _and_expr(self):
        left = self._not_expr()
        if self._is_kw("and"):
            values = [left]
            while self._is_kw("and"):
                self._advance()
                values.append(self._not_expr())
            return A.BoolOp("and", values, left.span)
        return left

    def _not_expr(self):
        if self._is_kw("not"):
            start = self._advance()
            return A.UnaryOp("not", self._not_expr(), start.span)
        return self._comparison()

    def _comparison(self):
        left = self._arith()
        if self.cur.kind is Tok.OP and self.cur.value in COMPARE_OPS:
            ops: list = []
            comps: list = []
            while self.cur.kind is Tok.OP and self.cur.value in COMPARE_OPS:
                ops.append(self._advance().value)
                comps.append(self._arith())
            return A.Compare(left, ops, comps, left.span)
        return left

    def _arith(self):
        left = self._term()
        while self.cur.kind is Tok.OP and self.cur.value in ("+", "-"):
            op = self._advance().value
            right = self._term()
            left = A.BinOp(op, left, right, left.span)
        return left

    def _term(self):
        left = self._factor()
        while self.cur.kind is Tok.OP and self.cur.value in ("*", "/", "//", "%"):
            op = self._advance().value
            right = self._factor()
            left = A.BinOp(op, left, right, left.span)
        return left

    def _factor(self):
        if self.cur.kind is Tok.OP and self.cur.value in ("-", "+"):
            start = self._advance()
            return A.UnaryOp(start.value, self._factor(), start.span)
        return self._power()

    def _power(self):
        base = self._atom_trailer()
        if self._is_op("**"):
            self._advance()
            exp = self._factor()  # right-associative
            return A.BinOp("**", base, exp, base.span)
        return base

    def _atom_trailer(self):
        node = self._atom()
        while True:
            if self._is_op("("):
                node = self._call(node)
            elif self._is_op("["):
                node = self._subscript(node)
            elif self._is_op("."):
                self._advance()
                attr = self._expect(Tok.NAME)
                node = A.Attribute(node, attr.value, node.span)
            else:
                return node

    def _call(self, func):
        self._expect_op("(")
        args: list = []
        if not self._is_op(")"):
            args.append(self._expr())
            while self._is_op(","):
                self._advance()
                if self._is_op(")"):
                    break
                args.append(self._expr())
        self._expect_op(")")
        return A.Call(func, args, func.span)

    def _subscript(self, obj):
        self._expect_op("[")
        lower = None
        if not self._is_op(":"):
            lower = self._expr()
        if self._is_op(":"):
            self._advance()
            upper = None
            step = None
            if not self._is_op(":") and not self._is_op("]"):
                upper = self._expr()
            if self._is_op(":"):
                self._advance()
                if not self._is_op("]"):
                    step = self._expr()
            self._expect_op("]")
            return A.SliceExpr(obj, lower, upper, step, obj.span)
        self._expect_op("]")
        return A.Subscript(obj, lower, obj.span)

    def _atom(self):
        t = self.cur
        if t.kind is Tok.NUMBER:
            self._advance()
            return A.Num(t.value, t.span)
        if t.kind is Tok.STRING:
            self._advance()
            return A.Str(t.value, t.span)
        if self._is_kw("True"):
            self._advance()
            return A.Const(True, t.span)
        if self._is_kw("False"):
            self._advance()
            return A.Const(False, t.span)
        if self._is_kw("None"):
            self._advance()
            return A.Const(None, t.span)
        if t.kind is Tok.NAME:
            self._advance()
            return A.Name(t.value, t.span)
        if self._is_op("("):
            self._advance()
            e = self._expr()
            self._expect_op(")")
            return e
        if self._is_op("["):
            return self._list_or_comprehension()
        raise ParseError(f"unexpected {self._describe()}", t.span)

    def _list_or_comprehension(self):
        start = self._expect_op("[")
        if self._is_op("]"):
            self._advance()
            return A.ListExpr([], start.span)
        first = self._expr()
        if self._is_kw("for"):
            self._advance()
            var = self._expect(Tok.NAME).value
            self._expect_kw("in")
            it = self._expr()
            cond = None
            if self._is_kw("if"):
                self._advance()
                cond = self._expr()
            self._expect_op("]")
            return A.Comprehension(first, var, it, cond, start.span)
        elems = [first]
        while self._is_op(","):
            self._advance()
            if self._is_op("]"):
                break
            elems.append(self._expr())
        self._expect_op("]")
        return A.ListExpr(elems, start.span)


def parse(tokens: list[Token]) -> A.Module:
    return Parser(tokens).parse()
