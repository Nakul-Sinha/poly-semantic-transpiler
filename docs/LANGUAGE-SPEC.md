# Language Spec — the Python subset ("MiniPy")

Poly's source language is a curated subset of Python 3. This document is the **grammar
contract** the lexer and parser implement. Anything outside it is either a `Hole`
(if pure and whitelisted) or a compile error.

## 1. Lexical structure

- **Indentation** is significant. The lexer emits `INDENT`/`DEDENT` tokens using an indent
  stack (spaces only; tabs are rejected with a diagnostic). Blank lines and `# comments`
  are ignored for indentation.
- **Identifiers**: `[A-Za-z_][A-Za-z0-9_]*`. Keywords are recognized from a fixed set.
- **Numbers**: integer (`42`) and float (`3.14`, `1.0`, `.5`, `2e3`). No complex/hex/underscore.
- **Strings**: single/double quoted, with escapes `\n \t \\ \" \'`. f-strings are
  **not supported in v1** — the lexer rejects them with a clear diagnostic (future work).
- **Operators/punctuation**: `+ - * / // % ** == != < <= > >= = += -= *= /= //= ( ) [ ] : , .`
- **Keywords**: `def return if elif else while for in range and or not True False None pass break continue`

## 2. Grammar (EBNF)

```ebnf
program     = { statement } ;
statement   = simple_stmt NEWLINE | compound_stmt ;

simple_stmt = assign | augassign | expr_stmt | return_stmt
            | "pass" | "break" | "continue" ;
assign      = target "=" expr ;
augassign   = target ("+="|"-="|"*="|"/="|"//=") expr ;
expr_stmt   = expr ;
return_stmt = "return" [ expr ] ;
target      = NAME | NAME "[" expr "]" ;                 (* variable or index *)

compound_stmt = if_stmt | while_stmt | for_stmt | func_def ;
if_stmt     = "if" expr ":" block { "elif" expr ":" block } [ "else" ":" block ] ;
while_stmt  = "while" expr ":" block ;
for_stmt    = "for" NAME "in" iter_expr ":" block ;
iter_expr   = call_range | expr ;                        (* range(...) or a list expr *)
func_def    = "def" NAME "(" [ params ] ")" ":" block ;
params      = param { "," param } ;
param       = NAME [ "=" expr ] ;                         (* trailing defaults only *)
block       = NEWLINE INDENT { statement } DEDENT ;

(* expressions, lowest→highest precedence, via Pratt parsing *)
expr        = or_expr ;
or_expr     = and_expr { "or" and_expr } ;
and_expr    = not_expr { "and" not_expr } ;
not_expr    = "not" not_expr | comparison ;
comparison  = arith { ("=="|"!="|"<"|"<="|">"|">=") arith } ;   (* chained ⇒ desugared *)
arith       = term { ("+"|"-") term } ;
term        = factor { ("*"|"/"|"//"|"%") factor } ;
factor      = ("-"|"+") factor | power ;
power       = atom_trailer { "**" factor } ;             (* right-assoc *)
atom_trailer= atom { trailer } ;
trailer     = "(" [ args ] ")" | "[" subscript "]" | "." NAME ;
subscript   = expr | [ expr ] ":" [ expr ] [ ":" [ expr ] ] ;   (* slice ⇒ Hole if step or non-trivial *)
args        = expr { "," expr } ;
atom        = NUMBER | STRING | FSTRING | "True" | "False" | "None"
            | NAME | "(" expr ")" | list_display | comprehension ;
list_display   = "[" [ expr { "," expr } ] "]" ;
comprehension  = "[" expr "for" NAME "in" expr [ "if" expr ] "]" ;   (* ⇒ Hole *)
```

## 3. Deterministic core (lowered by hand-written rules)

- **Literals**: `int`, `float`, `bool`, `str`, `None`, list displays `[1, 2, 3]`.
- **Names / assignment / augmented assignment** (single target or `name[index]`).
- **Operators**: `+ - * / // % **`, comparisons, `and or not`, unary `-`/`not`.
  Chained comparisons `a < b < c` are **desugared** to `(a < b) and (b < c)`.
- **Control flow**: `if/elif/else`, `while`, `for x in range(...)`, `for x in <list>`,
  `break`, `continue`.
- **Functions**: `def` with positional params and trailing defaults, `return`, calls, `pass`.
- **Builtins**: `print`, `len`, `range`, `abs`, `int()`, `float()`, `str()`, and the
  `list.append(x)` method.
- **Indexing**: `xs[i]` (read and assign).

## 4. Semantic holes (pure ⇒ filled by the LLM, validated)

| Construct | Example | Eligible targets |
|-----------|---------|------------------|
| List comprehension | `[x*x for x in xs if x > 0]` | JS, Python |
| Slice (any `:` subscript) | `xs[2:8]`, `xs[1:9:2]`, `xs[::2]` | JS, Python |

A hole is created **only if** its subtree is pure (no I/O, no mutation of outer state, no
nondeterminism) and matches the whitelist above. Otherwise it is a **hard compile error**,
never handed to the LLM.

## 5. Explicitly rejected (hard error)

Impure or nondeterministic constructs are never eligible for a hole: `open`, `input`, file or
network access, `import`, `random`, `time`, global mutation, `try/except`, classes, `lambda`
stored across statements, generators, decorators. Dicts and tuples are out of v1 scope.

## 6. Worked example

```python
def sum_squares(xs):
    total = 0
    for x in xs:
        if x % 2 == 0:
            total += x * x
    return total
```

Lowers entirely to deterministic IR (no holes) and transpiles to JS, Python, and C.
Adding `return [x*x for x in xs]` introduces one list-comprehension **hole** (JS/Python).
