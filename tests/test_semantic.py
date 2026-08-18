import pytest

from helpers import build_ast
from poly import ast_nodes as A
from poly.errors import SemanticError


def first(node, cls):
    found = []

    def rec(n):
        if isinstance(n, cls):
            found.append(n)
        for f, v in vars(n).items():
            if f == "span":
                continue
            if isinstance(v, list):
                for x in v:
                    if hasattr(x, "__dataclass_fields__"):
                        rec(x)
            elif hasattr(v, "__dataclass_fields__"):
                rec(v)

    rec(node)
    return found[0]


def test_infers_types():
    m = build_ast("a = 1\nb = 2.0\nc = a + b\nd = a < b\n")
    types = {s.target.id: s.value.type.kind for s in m.body}
    assert types["a"] == "int"
    assert types["b"] == "float"
    assert types["c"] == "float"   # int + float -> float
    assert types["d"] == "bool"


def test_comprehension_pure_slice_pure():
    m = build_ast("xs = [1,2,3]\nys = [x*x for x in xs if x > 0]\nz = xs[::2]\n")
    comp = first(m, A.Comprehension)
    sl = first(m, A.SliceExpr)
    assert comp.pure is True
    assert sl.pure is True


def test_print_and_append_are_impure():
    m = build_ast("xs = [1]\nxs.append(2)\nprint(xs)\n")
    call = first(m, A.Call)
    assert call.pure is False


def test_undeclared_name():
    with pytest.raises(SemanticError):
        build_ast("y = x + 1\n")


def test_return_outside_function():
    with pytest.raises(SemanticError):
        build_ast("return 1\n")


def test_break_outside_loop():
    with pytest.raises(SemanticError):
        build_ast("break\n")


def test_unknown_type_annotation():
    with pytest.raises(SemanticError):
        build_ast("def f(x: Widget) -> int:\n    return 1\n")
