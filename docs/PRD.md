# PRD — Poly Semantic Transpiler

## 1. Problem

Rule-based transpilers translate syntax well but break at the semantic edges of a language:
constructs that exist in one language but not another, and the long tail of idioms that would
need dozens of special-case rules. Writing every rule by hand makes the codebase large and
brittle — bad for a course project that must stay explainable.

## 2. Goal

Build a **cross-language transpiler from first principles** (own lexer, parser, semantic
analyzer, IR, and code generators) that stays **small and explainable**, using a **bounded,
validated LLM layer** to cover the pure long tail instead of hand-writing rules for it.

## 3. Users

- **The student** — must be able to explain every module to the professor.
- **The professor / grader** — must be able to run the project offline, without API keys,
  and see the compiler working and self-verifying.

## 4. Hard constraints

1. The hand-written compiler pipeline is the graded core and must work **without** the LLM.
2. Codebase stays modest (~3.5–3.8k LOC) and every concept is explainable.
3. The LLM is architecturally **subordinate**: it cannot run without the compiler's type
   information, cannot choose names or splice points, and cannot emit unvalidated code.
4. Reproducible and offline-runnable: `--no-llm` and a committed golden cache mean the whole
   test suite runs with no network and no secrets.

## 5. Scope (v1)

**Source:** a curated Python 3 subset (see `LANGUAGE-SPEC.md`).
**Targets:** JavaScript (ES2020), Python 3, and C (C99).
**Implemented in:** Python 3.

### In scope — deterministic core
Literals (int/float/bool/str/None/list), variables, assignment & augmented assignment,
arithmetic/comparison/boolean/unary operators (with correct Python→target semantics for `//`
and truthiness), `if/elif/else`, `while`, `for`-over-`range`, `for`-over-list, `break`/`continue`,
function definitions & calls, `return`, `pass`, and a small builtin set
(`print`, `len`, `range`, `abs`, `int`, `float`, `str`, and `list.append`).

### In scope — LLM semantic holes
Pure constructs deliberately left out of the deterministic core, filled by the validated LLM
layer: **list comprehensions** (flagship) and **stepped slices** (`a[::2]`). Targets JS and
Python; for C these raise a clear "feature unsupported for target" diagnostic (see Non-goals).

### Non-goals (v1)
Classes, exceptions/`try`, generators, decorators, `import` of third-party libraries,
dictionaries and tuples, string formatting beyond simple f-strings, and LLM holes for the C
target. All are documented as future work, not silent gaps.

## 6. Success criteria

- **SC1** — `python -m poly <prog> --target {js,py,c}` produces code that compiles/runs and
  matches CPython output on the deterministic core across every example.
- **SC2** — the 3-way differential self-check (`--self-check`) passes for all examples and
  **catches a deliberately planted codegen bug** (e.g. `//` emitted as `/`).
- **SC3** — a program with a list comprehension transpiles to JS and Python via the LLM layer,
  and **every** filled hole passes gates A/B/C; a deliberately broken fill is rejected with a
  concrete counterexample and repaired by the re-prompt loop.
- **SC4** — `--no-llm` still lexes, parses, analyzes, interprets, and emits the full
  deterministic pipeline; holes degrade to a marked stub.
- **SC5** — CI is green on Linux with python+node+gcc, **without** any API key.

## 7. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Differential testing samples equivalence, doesn't prove it | type-directed edge cases + fuzzing; documented as high-confidence QA, not a proof |
| LLM nondeterminism / no network in CI | temperature 0 + committed contract-hash golden cache + offline mock double; `--no-llm` for grading |
| Python↔target core-semantics mismatch (`//`, truthiness) | reference interpreter + 3-way differential surfaces them; explicit lowerings (`Math.floor`) |
| Scope creep in holes | holes are leaf-level, pure-gated by a static whitelist; impure ⇒ hard compile error |
