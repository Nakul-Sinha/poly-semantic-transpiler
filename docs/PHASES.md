# Build Phases

Each phase ends with a **working, demoable artifact** and green tests — nothing is big-bang.

| Phase | Deliverable | Modules | Demo / test |
|-------|-------------|---------|-------------|
| **P1** | Front-end | `tokens`, `errors`, `lexer`, `ast_nodes`, `parser` | `--dump-tokens`, `--dump-ast`; parser round-trips examples |
| **P2** | Semantic analysis | `symbols`, `types`, `semantic` | scope/type/purity annotations; error on undeclared name |
| **P3** | IR + interpreter | `ir`, `lower`, `interp` | run a program **through the IR** and get correct output (before any codegen) |
| **P4** | JS back-end + harness | `codegen/base`, `codegen/js`, `differential` | first end-to-end transpile; 3-way differential green |
| **P5** | Python & C back-ends | `codegen/python`, `codegen/c` | same programs run identically on all three targets |
| **P6** | LLM hole layer | `llm/holes`, `llm/client`, `llm/gates`, cache | comprehension example fills + passes gates; broken fill rejected & repaired |
| **P7** | CLI, examples, CI | `cli`, `examples/`, `.github/workflows/ci.yml`, tests | `--self-check`, `--no-llm`, planted-bug demo; CI green offline |

## Definition of done (per PRD success criteria)

- **P3** satisfies the backbone: correctness exists at the IR level before codegen.
- **P4–P5** satisfy **SC1** (all targets match CPython) and **SC2** (self-check catches a
  planted `//`→`/` bug).
- **P6** satisfies **SC3** (holes filled & validated; broken fill repaired) and **SC4**
  (`--no-llm` completeness).
- **P7** satisfies **SC5** (CI green with python+node+gcc, no API key).

## Stretch / future work (documented, not built in v1)

- Second front-end (e.g. a small Lua/C subset) to demonstrate multi-source on the same IR.
- LLM holes for the C target (needs the list runtime extended to comprehension helpers).
- Dicts, tuples, classes, exceptions; front-end phrase-level error recovery via the same
  propose-then-revalidate discipline as holes.
