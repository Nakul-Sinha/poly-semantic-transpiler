# Poly: 10-language Transpiler

Translate between **Python, JavaScript, C, C++, Java, C#, Go, Rust, Ruby, and PHP**.
Every language can be selected as input or output (100 combinations, including same-language passthrough).

The fastest way to start:

```bash
python web/server.py
```

Open **http://127.0.0.1:8765**. Choose the source and target languages, paste a program or
load an **example**, and click **Run**. **Swap** moves the generated code to the input side;
**download** saves the generated source. Drafts are remembered separately for each language.

For AI translation, use either:

- **Claude Code login:** install [Claude Code](https://code.claude.com/docs/en/setup), run
  `claude auth login`, then leave the API key field empty. Your existing login is used by
  the local CLI. No authentication tokens are copied into the app.
- **Anthropic API:** enter your API key in the header, or configure `ANTHROPIC_API_KEY` in
  the server environment. Settings lets you select the service and override the model.
  Keys entered in the page are kept in memory, never saved in browser storage or files.

Supported Python-subset programs targeting Python, JavaScript or C still use the original
handwritten compiler offline. Other programs/pairs use whole-program AI translation.
The CLI supports the same ten languages, inferring the input language from the extension:

```bash
python -m poly program.java --target rust
python -m poly program.rb --from ruby --target cpp -o translated.cpp
python -m poly examples/gcd.py --target java --self-check
python -m poly examples/gcd.py --target js --no-llm
```

**Validation:** Run checks the output with the target compiler/interpreter when installed,
and retries once with compiler diagnostics if it fails. An unavailable compiler is explicitly
reported as **not checked**. Translation never automatically executes the generated program.
**Check** executes the source and translation locally and compares stdout on that run;
it reuses the current generated code when possible. A missing runtime is reported as an
incomplete check, never a pass. Matching one run is not a proof of semantic equivalence.

Local compiler tools: Python, Node.js, GCC, G++, JDK (`javac` + `java`), .NET **SDK**,
Go, Rust, Ruby, and PHP. You only need tools for languages you want to validate/run;
translation works even when a target toolchain is unavailable. Only standard-library,
single-file programs are requested; framework/project migrations and arbitrary dependency
installation are outside this mode's scope.

The web server is a **localhost development tool**. Check runs your code with time limits
and removes credential-like environment variables, but is not a security sandbox.
Use trusted programs and keep the server bound to localhost.

## Original handwritten compiler

Poly includes a **from-scratch cross-language transpiler** with a **bounded LLM assist**.
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

In the original compiler path, the LLM (`poly/llm/`) only ever sees **one typed hole contract at a time**. It never sees
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

The stages button in the top left corner splits the screen: the terminal slides
to the left half and a pipeline panel opens beside it, showing all six compiler
stages run on the code currently in the editor, with the real artifacts of each
stage (tokens, AST, inferred types, IR and hole contracts, gate records,
generated code). With an API key in the header field, the LLM adds a one
sentence narration per stage about that specific program.

The page looks for background artwork at `web/static/bg.jpg` (also accepts
.png, .jpeg or .webp under the name `bg`); a soft gradient is used until the
file exists.

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
Those documents describe the original Python-subset compiler. Ten-language routing and
examples live in `poly/languages.py`, AI translation in `poly/translate.py`, and local
compiler/execution checks in `poly/validation.py`.
