# LLM Layer — Validated Semantic Holes

The LLM is a **bounded, validated fallback translator**. It fills the pure long-tail
constructs the deterministic compiler deliberately does not lower, and the compiler validates
every fill. This document specifies the contract, the client, and the three gates.

## 1. Lifecycle of a hole

```
lowering ──► Hole + HoleContract ──► client.fill(contract, target)
                                          │  (cache hit? ─► return fragment)
                                          ▼
                                     candidate fragment (LLM / mock)
                                          │
                            ┌─────────────┴─────────────┐
                            ▼                            │ reject + counterexample
                     Gate A  syntax                      │  (re-prompt, ≤ N tries)
                     Gate B  scope/interface   ──────────┘
                     Gate C  differential vs CPython
                            │ all pass
                            ▼
                     cache[contract_hash] = fragment ─► codegen splices it
```

On exhausting the retry budget, the compiler raises a clean `CompileError` — it never emits
an unvalidated fragment.

## 2. What the LLM sees (and does not)

**Sees:** one `HoleContract` — the original Python snippet, the free variables with inferred
types, the required result type, and the pre-allocated helper name + params.

**Never sees:** the rest of the program, the symbol table, the IR, or any other hole.
**Never decides:** which nodes are holes, variable names, splice location, or whether its
output is accepted.

The prompt asks for **only the body** of `fn_name(param_names) -> result_type` in the target
language, pure, no imports, no I/O. Output is treated as untrusted data.

## 3. The three gates

| Gate | Question | Implementation |
|------|----------|----------------|
| **A — syntax** | Does the fragment parse as valid target code? | JS: `node --check` on the helper; Python: `compile()`. |
| **B — scope/interface** | Does it use only allowed names, and no forbidden capabilities? | Hand-written identifier scan (`poly/llm/gates.py`): every free identifier must be a param, a locally-declared name, or a whitelisted builtin; a denylist (`require`, `import`, `fetch`, `process`, `eval`, `Function`, `open`, …) fails it. |
| **C — behavioral** | Does it compute the same thing as the original Python? | `poly/differential.py` generates typed inputs from `free_vars`, runs the original Python `source` under CPython and the target helper under `node`/`python`, and compares outputs over N inputs including edge cases. |

Gate B is intentionally hand-written (not delegated to a parser library) because it is the
pedagogically interesting capability check and it is where hallucinated/out-of-scope names are
caught.

## 4. Client, determinism, and offline mode

`poly/llm/client.py` resolves a hole in this order:

1. **Cache** — `contract_hash` (sha256 of the canonicalized contract + target) hits the
   committed golden cache in `poly/llm/cache/`. Zero network, byte-identical rebuilds.
2. **Offline mock** — if there is no `ANTHROPIC_API_KEY` or `POLY_LLM_MODE=mock`, a small
   deterministic **test double** fills the known demo holes (list comprehension, slice). It
   exists so CI and graders run without secrets; its output still goes through gates A/B/C.
3. **Live LLM** — otherwise call the Claude API at **temperature 0** with the contract prompt.

Whatever source fills the hole, the fragment is cached only **after** passing all three gates.

## 5. `--no-llm` mode

Disables the client entirely. Holes are emitted as a marked stub
(`/* UNSUPPORTED: list_comprehension */` and a thrown error / `None`) so the surrounding
program still compiles. This proves the deterministic compiler is complete on its own subset
and that the LLM is removable.

## 6. Prompt (shape)

```
You are translating ONE pure Python expression into <TARGET>.
Write ONLY the body of:
    function <fn_name>(<params>) { ... }         // JS
    def <fn_name>(<params>):    ...              # Python
It must be pure: no imports, no I/O, no globals. Use only the parameters.
Python source:
    <source>
Parameter types: <free_vars>
Return type: <result_type>
Return the target-language code for the function only.
```

## 7. Threat model / honesty notes

- Differential testing **samples** equivalence; it is high-confidence QA, not a proof. The
  report says so, and Gate C uses type-directed edge cases plus random fuzzing.
- The offline mock is a **test double**, not "the product." Its only job is to let the suite
  run without an API key; the real path is the Claude API. The compiler's correctness claims
  rest on the deterministic core + gates, not on the model.
