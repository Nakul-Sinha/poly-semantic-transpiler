import pytest

from poly.lexer import tokenize
from poly.tokens import Tok
from poly.errors import LexError


def kinds(src):
    return [t.kind for t in tokenize(src)]


def test_indent_dedent_balanced():
    src = "def f():\n    x = 1\n    if x:\n        y = 2\nz = 3\n"
    ks = kinds(src)
    assert ks.count(Tok.INDENT) == ks.count(Tok.DEDENT) == 2
    assert ks[-1] is Tok.EOF


def test_numbers_and_operators():
    toks = tokenize("a = 3 + 4.5 * 2\n")
    values = [t.value for t in toks if t.kind in (Tok.NUMBER, Tok.OP, Tok.NAME)]
    assert 3 in values and 4.5 in values and "**" not in values


def test_string_escapes():
    toks = tokenize('s = "a\\nb"\n')
    strs = [t.value for t in toks if t.kind is Tok.STRING]
    assert strs == ["a\nb"]


def test_comments_and_blank_lines_ignored():
    src = "# comment\n\nx = 1\n\n# another\ny = 2\n"
    names = [t.value for t in tokenize(src) if t.kind is Tok.NAME]
    assert names == ["x", "y"]


def test_tabs_rejected():
    with pytest.raises(LexError):
        tokenize("def f():\n\tx = 1\n")


def test_fstring_rejected_clearly():
    with pytest.raises(LexError):
        tokenize('x = f"{y}"\n')


def test_unterminated_string():
    with pytest.raises(LexError):
        tokenize('s = "abc\n')
