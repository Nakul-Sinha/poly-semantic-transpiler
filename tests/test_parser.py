import pytest

from helpers import build_ast
from poly import ast_nodes as A
from poly.lexer import tokenize
from poly.parser import parse
from poly.errors import ParseError


def parse_src(src):
    return parse(tokenize(src))


def test_precedence_times_binds_tighter_than_plus():
    m = parse_src("z = 1 + 2 * 3\n")
    add = m.body[0].value
    assert isinstance(add, A.BinOp) and add.op == "+"
    assert isinstance(add.right, A.BinOp) and add.right.op == "*"


def test_power_right_associative():
    m = parse_src("z = 2 ** 3 ** 2\n")
    top = m.body[0].value
    assert top.op == "**" and isinstance(top.right, A.BinOp) and top.right.op == "**"


def test_elif_becomes_nested_if():
    m = parse_src("if a:\n    x = 1\nelif b:\n    x = 2\nelse:\n    x = 3\n")
    # need names declared to parse (parser doesn't check scope) -> fine, parse-only
    node = m.body[0]
    assert isinstance(node, A.If)
    assert len(node.orelse) == 1 and isinstance(node.orelse[0], A.If)


def test_comprehension_and_slice():
    m = parse_src("ys = [x * x for x in xs if x > 0]\n")
    assert isinstance(m.body[0].value, A.Comprehension)
    m2 = parse_src("z = xs[1:9:2]\n")
    assert isinstance(m2.body[0].value, A.SliceExpr)


def test_type_annotations():
    m = build_ast("def f(a: int, b: list[int]) -> int:\n    return a\n")
    fn = m.body[0]
    assert fn.params[0].type.kind == "int"
    assert fn.params[1].type.kind == "list"
    assert fn.ret_type.kind == "int"


def test_invalid_assignment_target():
    with pytest.raises(ParseError):
        parse_src("1 + 2 = 3\n")
