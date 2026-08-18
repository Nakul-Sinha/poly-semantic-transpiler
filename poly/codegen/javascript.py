"""JavaScript (ES2020) back-end.

Where Python and JS semantics diverge, the generated code routes through a small
runtime prelude so behaviour matches Python:
  * ``//`` -> poly_floordiv (Math.floor), ``%`` -> poly_mod (sign of divisor),
    ``**`` -> poly_pow;
  * truthiness of ``[]``/``0``/``""``/None via poly_truthy;
  * ``and``/``or`` compiled to thunked helpers to preserve short-circuit + value;
  * ``+``/``*`` on lists/strings via concat / poly_repeat;
  * Python-style printing (True/False/None, ``[1, 2, 3]``) via poly_str.
"""
from __future__ import annotations

from .. import ir
from .base import Emitter, iter_holes

RUNTIME = r"""// ---- poly runtime ----
function poly_floordiv(a, b) { return Math.floor(a / b); }
function poly_mod(a, b) { let r = a % b; if (r !== 0 && ((r < 0) !== (b < 0))) r += b; return r; }
function poly_pow(a, b) { return Math.pow(a, b); }
function poly_truthy(x) {
  if (Array.isArray(x)) return x.length !== 0;
  if (x === null || x === undefined) return false;
  return Boolean(x);
}
function poly_and(fa, fb) { const a = fa(); return poly_truthy(a) ? fb() : a; }
function poly_or(fa, fb) { const a = fa(); return poly_truthy(a) ? a : fb(); }
function poly_len(x) { return x.length; }
function poly_abs(x) { return Math.abs(x); }
function poly_int(x) { return Math.trunc(Number(x)); }
function poly_float(x) { return Number(x); }
function poly_range(start, stop, step) {
  const out = [];
  if (step > 0) { for (let i = start; i < stop; i += step) out.push(i); }
  else if (step < 0) { for (let i = start; i > stop; i += step) out.push(i); }
  return out;
}
function poly_repeat(x, n) {
  if (typeof x === 'string') return x.repeat(Math.max(0, n));
  const out = []; for (let i = 0; i < n; i++) for (const e of x) out.push(e); return out;
}
function poly_slice(x, lo, hi, step) {
  const n = x.length;
  step = (step === null || step === undefined) ? 1 : step;
  const isStr = (typeof x === 'string');
  const arr = isStr ? x.split('') : x;
  const out = [];
  if (step > 0) {
    let start = (lo === null || lo === undefined) ? 0 : (lo < 0 ? Math.max(n + lo, 0) : Math.min(lo, n));
    let stop  = (hi === null || hi === undefined) ? n : (hi < 0 ? Math.max(n + hi, 0) : Math.min(hi, n));
    for (let i = start; i < stop; i += step) out.push(arr[i]);
  } else {
    let start = (lo === null || lo === undefined) ? n - 1 : (lo < 0 ? n + lo : Math.min(lo, n - 1));
    let stop  = (hi === null || hi === undefined) ? -1 : (hi < 0 ? n + hi : hi);
    for (let i = start; i > stop; i += step) out.push(arr[i]);
  }
  return isStr ? out.join('') : out;
}
function poly_repr(x) { if (typeof x === 'string') return "'" + x + "'"; return poly_str(x); }
function poly_str(x) {
  if (x === true) return 'True';
  if (x === false) return 'False';
  if (x === null || x === undefined) return 'None';
  if (Array.isArray(x)) return '[' + x.map(poly_repr).join(', ') + ']';
  return String(x);
}
function poly_print() {
  const args = Array.prototype.slice.call(arguments);
  console.log(args.map(poly_str).join(' '));
}
// ---- end runtime ----"""

BUILTIN_CALL = {"print": "poly_print", "len": "poly_len", "abs": "poly_abs",
                "int": "poly_int", "float": "poly_float", "str": "poly_str",
                "range": "poly_range"}

CMP = {"==": "===", "!=": "!==", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


class JsGen:
    def __init__(self, module: ir.Module):
        self.module = module
        self.e = Emitter("  ")

    def generate(self) -> str:
        self.e.raw(RUNTIME)
        self.e.line()
        for hole in iter_holes(self.module):
            self._hole_def(hole)
        for fn in self.module.funcs:
            self._function(fn)
        # top-level ("main")
        self._declare_locals(self.module.body)
        for stmt in self.module.body:
            self._stmt(stmt)
        return self.e.code()

    # ---- holes ------------------------------------------------------------
    def _hole_def(self, hole: ir.Hole) -> None:
        c = hole.contract
        self.e.line(f"function {c.fn_name}({', '.join(c.param_names)}) {{")
        self.e.indent()
        body = hole.filled.get("js")
        if body:
            for ln in body.strip().splitlines():
                self.e.line(ln)
        else:
            self.e.line(f'throw new Error("UNSUPPORTED: {c.kind}");')
        self.e.dedent()
        self.e.line("}")
        self.e.line()

    # ---- functions --------------------------------------------------------
    def _function(self, fn: ir.Function) -> None:
        params = []
        for p in fn.params:
            params.append(p.name if p.default is None else f"{p.name} = {self._expr(p.default)}")
        self.e.line(f"function {fn.name}({', '.join(params)}) {{")
        self.e.indent()
        pnames = {p.name for p in fn.params}
        self._declare_locals(fn.body, skip=pnames)
        for s in fn.body:
            self._stmt(s)
        self.e.dedent()
        self.e.line("}")
        self.e.line()

    def _declare_locals(self, stmts: list, skip: set | None = None) -> None:
        names: list[str] = []
        seen = set(skip or ())

        def collect(ss: list) -> None:
            for s in ss:
                k = type(s).__name__
                if k == "Assign" and isinstance(s.target, ir.Name):
                    if s.target.id not in seen:
                        seen.add(s.target.id)
                        names.append(s.target.id)
                elif k == "If":
                    collect(s.body)
                    collect(s.orelse)
                elif k in ("While", "For"):
                    collect(s.body)

        collect(stmts)
        if names:
            self.e.line("let " + ", ".join(names) + ";")

    # ---- statements -------------------------------------------------------
    def _stmt(self, node) -> None:
        k = type(node).__name__
        if k == "Assign":
            self.e.line(f"{self._expr(node.target)} = {self._expr(node.value)};")
        elif k == "ExprStmt":
            self.e.line(f"{self._expr(node.value)};")
        elif k == "If":
            self._if(node)
        elif k == "While":
            self.e.line(f"while (poly_truthy({self._expr(node.test)})) {{")
            self._block(node.body)
            self.e.line("}")
        elif k == "For":
            self.e.line(f"for (const {node.var} of {self._iterable(node.iterable)}) {{")
            self._block(node.body)
            self.e.line("}")
        elif k == "Return":
            self.e.line("return;" if node.value is None else f"return {self._expr(node.value)};")
        elif k == "Pass":
            self.e.line("/* pass */")
        elif k == "Break":
            self.e.line("break;")
        elif k == "Continue":
            self.e.line("continue;")
        else:
            raise RuntimeError(f"js backend: cannot emit {k}")

    def _if(self, node) -> None:
        self.e.line(f"if (poly_truthy({self._expr(node.test)})) {{")
        self._block(node.body)
        orelse = node.orelse
        while len(orelse) == 1 and type(orelse[0]).__name__ == "If":
            elif_node = orelse[0]
            self.e.line(f"}} else if (poly_truthy({self._expr(elif_node.test)})) {{")
            self._block(elif_node.body)
            orelse = elif_node.orelse
        if orelse:
            self.e.line("} else {")
            self._block(orelse)
        self.e.line("}")

    def _block(self, stmts: list) -> None:
        self.e.indent()
        for s in stmts:
            self._stmt(s)
        self.e.dedent()

    def _iterable(self, node) -> str:
        if isinstance(node, ir.Range):
            return f"poly_range({self._expr(node.start)}, {self._expr(node.stop)}, {self._expr(node.step)})"
        return self._expr(node)

    # ---- expressions ------------------------------------------------------
    def _expr(self, node) -> str:
        k = type(node).__name__
        if k == "Const":
            return self._const(node.value)
        if k == "Name":
            return node.id
        if k == "ListLit":
            return "[" + ", ".join(self._expr(e) for e in node.elems) + "]"
        if k == "BinOp":
            return self._binop(node)
        if k == "UnaryOp":
            o = self._expr(node.operand)
            if node.op == "not":
                return f"(!poly_truthy({o}))"
            return f"({node.op}{o})"
        if k == "BoolOp":
            return self._boolop(node.op, node.values)
        if k == "Compare":
            return f"({self._expr(node.left)} {CMP[node.op]} {self._expr(node.right)})"
        if k == "Call":
            fn = BUILTIN_CALL.get(node.func, node.func)
            return f"{fn}(" + ", ".join(self._expr(a) for a in node.args) + ")"
        if k == "MethodCall":
            if node.method == "append":
                return f"{self._expr(node.obj)}.push({self._expr(node.args[0])})"
            raise RuntimeError(f"js backend: unsupported method {node.method}")
        if k == "Index":
            return f"{self._expr(node.obj)}[{self._expr(node.index)}]"
        if k == "Range":
            return f"poly_range({self._expr(node.start)}, {self._expr(node.stop)}, {self._expr(node.step)})"
        if k == "Hole":
            return f"{node.contract.fn_name}(" + ", ".join(node.contract.param_names) + ")"
        raise RuntimeError(f"js backend: cannot emit expression {k}")

    def _const(self, v) -> str:
        if v is True:
            return "true"
        if v is False:
            return "false"
        if v is None:
            return "null"
        if isinstance(v, str):
            import json
            return json.dumps(v)
        return repr(v)

    def _binop(self, node) -> str:
        l = self._expr(node.left)
        r = self._expr(node.right)
        op = node.op
        t = node.type.kind
        if op == "+":
            if t == "list":
                return f"{l}.concat({r})"
            return f"({l} + {r})"      # numeric or string concat
        if op == "*":
            if t in ("list", "str"):
                return f"poly_repeat({l}, {r})"
            return f"({l} * {r})"
        if op == "//":
            return f"poly_floordiv({l}, {r})"
        if op == "%":
            return f"poly_mod({l}, {r})"
        if op == "**":
            return f"poly_pow({l}, {r})"
        return f"({l} {op} {r})"       # - and /

    def _boolop(self, op: str, values: list) -> str:
        fn = "poly_and" if op == "and" else "poly_or"
        parts = [self._expr(v) for v in values]

        def fold(items: list[str]) -> str:
            if len(items) == 1:
                return items[0]
            return f"{fn}(() => {items[0]}, () => {fold(items[1:])})"

        return fold(parts)
