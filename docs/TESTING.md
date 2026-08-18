# Testing & CI Strategy

## 1. Layers of testing

| Layer | What it checks | Files |
|-------|----------------|-------|
| **Unit** | each stage in isolation | `tests/test_lexer.py`, `test_parser.py`, `test_semantic.py`, `test_ir.py` |
| **Interpreter** | IR semantics = CPython semantics | `tests/test_interp.py` |
| **Codegen (differential)** | each target's output = CPython output | `tests/test_codegen.py` (parametrized over examples × targets) |
| **Self-check** | 3-way differential catches a planted codegen bug | `tests/test_selfcheck.py` |
| **LLM gates** | filled hole passes A/B/C; broken fill rejected; `--no-llm` works | `tests/test_holes.py` |

## 2. Differential testing (the core method)

For a program `P` and target `T`:

```
ref   = run P with CPython            (reference output)
irout = interpret lower(parse(P))     (IR interpreter output)
tout  = run codegen_T(lower(parse(P))) with node/python/gcc
assert ref == irout == tout           (normalized)
```

Inputs for hole-level Gate C are **type-directed**: for each free var type we generate
edge cases — empty list, `0`, negatives, duplicates, boundary ints, plus random fuzzing.
This is **high-confidence QA, not a proof** (documented in `LLM-LAYER.md`).

## 3. Determinism in CI

- No network, no API key. The LLM client uses the committed golden cache first, then the
  offline mock double. Gates A/B/C still run for real against the fragment.
- `node` and `gcc` are provided by the CI image; if a tool is missing locally, the relevant
  differential tests **skip** (not fail) with a clear message.

## 4. Running locally

```bash
python -m pip install -e ".[dev]"
pytest -q                      # full suite
python -m poly examples/gcd.py --self-check    # human-readable 3-way report
make test                      # lint + pytest (see Makefile)
```

## 5. CI (`.github/workflows/ci.yml`)

Matrix on Ubuntu with Python 3.11/3.12, Node 20, gcc. Steps: install → `pytest` →
transpile every example to all targets and execute → run `--self-check` on all examples.
Fails if any target diverges from CPython. Runs entirely offline.
