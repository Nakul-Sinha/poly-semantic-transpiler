# Poly: a Semantic Transpiler

Poly is a **from-scratch cross-language transpiler** with a **bounded LLM assist**.
It compiles a subset of **Python** into a **language-agnostic semantic IR**, then emits
**JavaScript, Python, or C** from that IR. Everything the deterministic compiler cannot
lower on its own becomes a *typed semantic hole* that an LLM fills, and the compiler
validates every fill before it ships.

> **Design slogan:** *the LLM proposes, the compiler disposes.*

This is a Compiler Design course project. The hand-written compiler is the star; the LLM
is a subordinate, validated helper that can be switched off entirely (`--no-llm`).

```
   Python subset ──► [ lexer ▸ parser ▸ semantic analysis ] ──► AST
        AST ──► [ lower ] ──► Semantic IR ──┬──► [ JS  back-end ] ──► app.js
                                            ├──► [ PY  back-end ] ──► app.py
                                            └──► [ C   back-end ] ──► app.c
                                            │
                            [ IR reference interpreter ] = semantic oracle
                                            │
                    [ differential harness ]  CPython src ⇄ IR interp ⇄ target output
```

## Why this is a compiler project (not an LLM wrapper)

| Course topic            | Where it lives                                             |
|-------------------------|-----------------------------------------------------------|
| Lexical analysis        | `poly/lexer.py` (hand-written, incl. INDENT/DEDENT)       |
| Parsing                 | `poly/parser.py` (recursive descent + Pratt expressions)  |
| Semantic analysis       | `poly/semantic.py` (symbol tables, scopes, type inference)|
| Effect analysis         | `poly/semantic.py` (purity, decides hole eligibility)     |
| Intermediate representation | `poly/ir.py` (language-agnostic)                       |
| Code generation         | `poly/codegen/{js,python,c}.py` (three back-ends)         |
| Translation validation  | `poly/differential.py` + `poly/interp.py`                 |

The LLM (`poly/llm/`) only ever sees **one typed hole contract at a time**. It never sees
the whole program, never picks variable names, never chooses where its code goes, and its
output is untrusted until it passes three validation gates.

## Quick start

```bash
python -m pip install -e .
python -m poly examples/gcd.py --target js          # transpile to JavaScript
python -m poly examples/comprehension.py --target py # exercises a semantic hole
python -m poly examples/gcd.py --self-check          # 3-way differential report
python -m poly examples/gcd.py --target js --no-llm  # prove the compiler is complete without the LLM
```

## Web interface

A minimal glassmorphic UI for the transpiler: a movable, resizable dual pane
glass terminal with your Python source on the left and generated code on the
right.

```bash
python web/server.py
```

Open http://127.0.0.1:8765, pick a target (JavaScript, Python, C) and press
Run. Programs that use semantic holes go through the validated LLM layer
(offline mock by default; paste an Anthropic API key into the header field for
live fills, the key stays in memory only). The Check button runs the 3-way
differential self-check right in the output pane.

The page looks for background artwork at `web/static/bg.jpg` (any large image
works; a soft gradient is used if the file is absent).

Note: the self-check executes the submitted program with CPython as the
reference oracle, so keep the server on localhost (the default).

## Repository layout

```
docs/           PRD, architecture, language & IR specs, phase plan, testing strategy
poly/           the compiler (front-end, semantic, IR, interpreter, back-ends, LLM layer, CLI)
web/            local web interface (stdlib HTTP server + glass UI)
examples/       sample Python-subset programs
tests/          pytest suite (unit + golden differential tests)
.github/        CI workflow (python + node + gcc)
```

See [`docs/PRD.md`](docs/PRD.md) for goals and scope, [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the design, and [`docs/PHASES.md`](docs/PHASES.md) for the build plan.
