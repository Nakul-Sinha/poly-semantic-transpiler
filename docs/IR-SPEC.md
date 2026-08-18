# IR Spec — Poly Semantic IR

The IR is the **language-agnostic contract** between front-end and back-ends. It is a small,
normalized tree: Python sugar has been desugared, and every node is trivially walkable by the
interpreter and the three code generators. Defined as dataclasses in `poly/ir.py`.

## 1. Design rules

- **Normalized**: augmented assignment, chained comparison, and the two `for` forms are all
  desugared during lowering — back-ends never see Python-only sugar.
- **Explicit**: operators are stored as plain strings (`"+"`, `"//"`, `"=="`, `"and"`).
- **Self-contained**: no node references the AST or the source language, except `Hole`, which
  keeps the original Python source *text* of its subtree (a string) for the interpreter and
  differential harness.
- **Typed where known**: expression nodes carry an optional `type` (from `types.py`).

## 2. Statement nodes

| Node | Fields | Meaning |
|------|--------|---------|
| `Module` | `body: list[Stmt]`, `funcs: list[Function]` | top-level program |
| `Function` | `name, params: list[Param], body: list[Stmt]` | function definition |
| `Param` | `name, type, default: Expr\|None` | parameter |
| `Assign` | `target: Name\|Index, value: Expr` | `target = value` |
| `ExprStmt` | `value: Expr` | expression used as a statement |
| `If` | `test: Expr, body: list[Stmt], orelse: list[Stmt]` | conditional |
| `While` | `test: Expr, body: list[Stmt]` | loop |
| `For` | `var: str, iterable: Expr, body: list[Stmt]` | unified loop over any iterable |
| `Return` | `value: Expr\|None` | function return |
| `Break` / `Continue` | — | loop control |
| `Pass` | — | no-op |

`augassign` `t op= e` is lowered to `Assign(t, BinOp(op, t, e))`.
`for x in range(a,b,c)` lowers to `For(x, Range(a,b,c), body)`.

## 3. Expression nodes

| Node | Fields | Meaning |
|------|--------|---------|
| `Const` | `value, type` | literal int/float/bool/str/None |
| `Name` | `id, type` | variable reference |
| `ListLit` | `elems: list[Expr], type` | `[...]` display |
| `BinOp` | `op: str, left, right, type` | arithmetic / concat |
| `UnaryOp` | `op: str, operand, type` | `-x`, `not x` |
| `BoolOp` | `op: "and"\|"or", values: list[Expr]` | short-circuit boolean |
| `Compare` | `op: str, left, right` | single comparison (chains desugared) |
| `Call` | `func: str, args: list[Expr], type` | builtin or user-function call |
| `MethodCall` | `obj: Expr, method: str, args, type` | e.g. `xs.append(x)` |
| `Index` | `obj: Expr, index: Expr, type` | `xs[i]` |
| `Range` | `start, stop, step: Expr` | iterable produced by `range(...)` |
| `Hole` | `hole_id, contract: HoleContract, filled: dict[str,str]` | unsupported-but-pure subtree |

`Hole.filled` maps a target language name (`"js"`, `"py"`) to the validated fragment once the
LLM layer has run; empty under `--no-llm`.

## 4. The `Hole` node & contract

`Hole` is where the compiler hands off — and stays in control. Its `HoleContract`
(defined in `poly/llm/holes.py`) contains only compiler-derived facts:

```python
HoleContract(
    hole_id: str,               # stable id, e.g. "hole_0"
    kind: str,                  # "list_comprehension" | "slice" | "fstring"
    source: str,                # original Python text of the subtree
    free_vars: list[VarInfo],   # (name, type) the fragment may read — from the symbol table
    result_type: Type,          # inferred type the fragment must produce
    fn_name: str,               # compiler-allocated helper name, e.g. "hole_0"
    param_names: list[str],     # compiler-allocated params (= free_vars names)
)
```

The LLM fills the **body** of a helper function `fn_name(param_names...) -> result_type`.
Codegen emits that helper and splices a call `fn_name(free_vars...)` at the hole site — so the
shape is uniform across targets and the LLM never chooses names or placement.

## 5. Interpreter semantics for `Hole`

The reference interpreter (`interp.py`) evaluates a `Hole` by evaluating its original Python
`source` with CPython, in a **restricted namespace** built from the current values of the
hole's `free_vars` (no builtins beyond a small safe set). This is sound because holes are
purity-gated, and it makes the interpreter the single semantic oracle for both core and holes.

## 6. Invariants (checked in tests)

1. Every IR expression node has a `type` (possibly `Unknown`).
2. No `AugAssign`, chained `Compare`, or Python-specific `for` form survives into IR.
3. A `Hole` exists **iff** the source subtree was pure and whitelisted; impure ⇒ lowering
   raises `CompileError` before any IR is produced.
