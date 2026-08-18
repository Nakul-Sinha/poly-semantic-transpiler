# Architecture

## 1. The pivot design (why it scales)

Poly never writes a transpiler *per language pair*. Front-ends and back-ends meet at one
shared, language-agnostic **semantic IR**:

```
   Python ─┐                                   ┌─► JavaScript
           ├─► [ front-end ] ─► AST ─► [ lower ] ─► Semantic IR ─┼─► Python
  (future) ─┘                                   └─► C
```

*N* source languages + *M* target languages = *N×M* transpilers, but only *N+M* components
to write. Everything valuable lives at the IR layer and is therefore shared by every pair:
the **reference interpreter**, the **LLM hole filler**, and the **differential harness**.
Adding a language = one front-end *or* one back-end; it inherits all three for free.

v1 ships **1 front-end (Python) × 3 back-ends (JS, Python, C)** to demonstrate the property.

## 2. Pipeline stages & module map

| # | Stage | Module | Input → Output |
|---|-------|--------|----------------|
| 1 | Lex | `poly/lexer.py`, `poly/tokens.py` | source text → `Token[]` (with spans, INDENT/DEDENT) |
| 2 | Parse | `poly/parser.py`, `poly/ast_nodes.py` | tokens → AST |
| 3 | Resolve & type | `poly/semantic.py`, `poly/symbols.py`, `poly/types.py` | AST → annotated AST (scopes, types) |
| 4 | Effects | `poly/semantic.py` | annotated AST → purity flags per node |
| 5 | Lower | `poly/lower.py`, `poly/ir.py` | AST → IR (supported ⇒ IR node, pure+unsupported ⇒ `Hole`, impure+unsupported ⇒ error) |
| 6 | Interpret | `poly/interp.py` | IR → runtime values (the semantic oracle) |
| 7 | Fill holes | `poly/llm/` | `Hole` + contract → validated target fragment |
| 8 | Codegen | `poly/codegen/{base,js,python,c}.py` | IR (+ hole fragments) → target source |
| 9 | Verify | `poly/differential.py` | CPython src ⇄ IR interp ⇄ target output |
| — | Drive | `poly/cli.py`, `poly/errors.py` | orchestration, diagnostics |

## 3. Data flow & contracts

- **Token** (`tokens.py`): `kind`, `value`, `Span(line, col, end_line, end_col)`.
- **AST** (`ast_nodes.py`): dataclasses, every node carries a `span`. Semantic analysis adds
  `.type` (a `types.Type`) and `.pure` (bool) attributes in place.
- **IR** (`ir.py`): a smaller, normalized tree. Python-specific sugar is desugared here
  (augmented assignment → assign+binop; chained comparison → boolean-and of pairs;
  `for`-over-`range` and `for`-over-list → a single `For(var, iterable, body)`).
- **Hole** (`ir.py`): an IR node standing in for an unsupported-but-pure subtree. Carries a
  `HoleContract` (see `LLM-LAYER.md`): the original Python source of the subtree, its free
  variables with inferred types, and the result type. Compiler-owned; the LLM only reads it.

The AST↔IR boundary is the key contract: back-ends and the interpreter depend **only** on IR,
never on the AST or the source language. This is what makes back-ends pluggable.

## 4. The LLM boundary (what keeps this a compiler)

```
                 built by the compiler          returned by the LLM (untrusted)
 Hole ──► HoleContract{source, free_vars,  ──►  target-language function body
          result_type, target, fn_name,          │
          param_names}                            ▼
                                          Gate A  parses?            (node --check / compile())
                                          Gate B  only allowed names? (hand-written scan)
                                          Gate C  same output as CPython on typed inputs?
                                   pass ─► cache + emit    fail ─► re-prompt w/ counterexample (≤N)
                                                           exhausted ─► hard compile error
```

Authority the **compiler** keeps: which nodes become holes (purity analysis), the contract,
variable names, splice location, all three gates, the retry budget, caching, and the final
go/no-go. The LLM's worst case is a clean compile error — never silently wrong output.

## 5. Determinism & offline operation

- LLM calls run at **temperature 0**; each validated fragment is stored in a
  **contract-hash → fragment** golden cache (`poly/llm/cache/`), committed to the repo.
- After first fill, rebuilds make **zero** model calls and are byte-identical.
- With no API key, the client uses an **offline mock double** that only knows the demo holes,
  so CI and graders run with no network and no secrets. The mock's output still passes gates
  A/B/C for real.
- `--no-llm` bypasses the LLM entirely; holes become marked `/* UNSUPPORTED */` stubs and the
  rest of the pipeline runs to completion.

## 6. Cross-language semantics notes (handled in codegen)

| Python | JavaScript | C |
|--------|------------|---|
| `a // b` (floor) | `Math.floor(a / b)` | `poly_floordiv(a, b)` runtime helper |
| truthiness of `[]`, `0`, `""` | explicit `poly_truthy(x)` helper | `poly_truthy(x)` helper |
| `print(x)` | `console.log(poly_str(x))` | `poly_print(x)` runtime |
| `len(x)` | `x.length` | `poly_len(x)` runtime |
| arbitrary-precision int | Number (documented limitation) | `long` (documented limitation) |

Known numeric-width and precision differences are documented, and the differential harness
uses inputs within the safe range so results are comparable.
