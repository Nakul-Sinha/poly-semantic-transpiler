"""Poly — a semantic cross-language transpiler with a validated LLM fallback.

Pipeline:  source -> lexer -> parser -> semantic -> lower -> IR
           IR -> {js, python, c} codegen  (+ validated LLM holes)
           IR -> reference interpreter (semantic oracle) -> differential harness
"""

__version__ = "0.1.0"
