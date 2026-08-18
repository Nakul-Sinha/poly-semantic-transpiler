"""Small helpers reused across tests."""
from poly.lexer import tokenize
from poly.parser import parse
from poly.semantic import analyze
from poly.lower import lower


def build(src: str):
    """Run the front half of the pipeline: source -> lowered IR module."""
    return lower(analyze(parse(tokenize(src)), src))


def build_ast(src: str):
    return analyze(parse(tokenize(src)), src)
