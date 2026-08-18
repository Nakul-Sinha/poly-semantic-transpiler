"""C (C99) back-end — the dynamic->static showpiece.

Uses the IR's inferred types to give every variable a concrete C type, and a small
runtime for the parts C lacks: a growable int list (``PolyList``), Python floor
division / modulo, integer power, and Python-style printing. Holes (comprehensions,
slices) are **not** supported for C in v1 and raise a clear diagnostic — documented
as future work, not a silent gap.

Type mapping:  int->long, float->double, bool->int, str->const char*,
               list[int]->PolyList, none->void.
"""
from __future__ import annotations

from .. import ir
from .. import types as T
from ..errors import CompileError
from .base import Emitter, iter_holes

RUNTIME = r"""#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef struct { long* data; long len; long cap; } PolyList;

static PolyList poly_list_new(void){ PolyList l; l.data=NULL; l.len=0; l.cap=0; return l; }
static void poly_list_append(PolyList* l, long v){
    if(l->len==l->cap){ l->cap = l->cap ? l->cap*2 : 4; l->data=(long*)realloc(l->data, l->cap*sizeof(long)); }
    l->data[l->len++]=v;
}
static PolyList poly_list_lit(long* arr, long n){ PolyList l=poly_list_new(); for(long i=0;i<n;i++) poly_list_append(&l, arr[i]); return l; }
static PolyList poly_list_concat(PolyList a, PolyList b){ PolyList l=poly_list_new(); for(long i=0;i<a.len;i++) poly_list_append(&l,a.data[i]); for(long i=0;i<b.len;i++) poly_list_append(&l,b.data[i]); return l; }
static long poly_floordiv_int(long a,long b){ long q=a/b; if((a%b!=0)&&((a<0)!=(b<0))) q--; return q; }
static double poly_floordiv_float(double a,double b){ return floor(a/b); }
static long poly_mod_int(long a,long b){ long r=a%b; if(r!=0 && ((r<0)!=(b<0))) r+=b; return r; }
static double poly_mod_float(double a,double b){ double r=fmod(a,b); if(r!=0 && ((r<0)!=(b<0))) r+=b; return r; }
static long poly_ipow(long a,long b){ long r=1; for(long i=0;i<b;i++) r*=a; return r; }
static long poly_iabs(long x){ return x<0?-x:x; }
static int poly_truthy_str(const char* s){ return s!=NULL && s[0]!='\0'; }
static void poly_print_int(long x){ printf("%ld", x); }
static void poly_print_float(double x){ printf("%g", x); }
static void poly_print_bool(int x){ printf("%s", x ? "True" : "False"); }
static void poly_print_str(const char* x){ printf("%s", x); }
static void poly_print_list(PolyList x){ printf("["); for(long i=0;i<x.len;i++){ if(i) printf(", "); printf("%ld", x.data[i]); } printf("]"); }
"""


def _ctype(t: T.Type) -> str:
    m = {"int": "long", "float": "double", "bool": "int", "str": "const char*", "none": "void"}
    if t.kind in m:
        return m[t.kind]
    if t.kind == "list":
        if t.elem is None or t.elem.kind != "int":
            raise CompileError("C target supports only list[int] in v1")
        return "PolyList"
    raise CompileError(f"C target cannot represent type {t} (add a type annotation?)")


class CGen:
    def __init__(self, module: ir.Module):
        self.module = module
        self.e = Emitter("    ")

    def generate(self) -> str:
        if iter_holes(self.module):
            raise CompileError("semantic holes (comprehensions/slices) are not supported "
                               "for the C target in v1 (future work)")
        self.e.raw(RUNTIME.rstrip("\n"))
        self.e.line()
        # prototypes
        for fn in self.module.funcs:
            self.e.line(self._signature(fn) + ";")
        self.e.line()
        # bodies
        for fn in self.module.funcs:
            self._function(fn)
        # main
        self.e.line("int main(void) {")
        self.e.indent()
        self._declare_locals(self.module.body, set())
        for s in self.module.body:
            self._stmt(s)
        self.e.line("return 0;")
        self.e.dedent()
        self.e.line("}")
        return self.e.code()

    # ---- functions --------------------------------------------------------
    def _signature(self, fn: ir.Function) -> str:
        params = ", ".join(f"{_ctype(p.type)} {p.name}" for p in fn.params)
        return f"{_ctype(fn.ret)} {fn.name}({params or 'void'})"

    def _function(self, fn: ir.Function) -> None:
        self.e.line(self._signature(fn) + " {")
        self.e.indent()
        self._declare_locals(fn.body, {p.name for p in fn.params})
        for s in fn.body:
            self._stmt(s)
        self.e.dedent()
        self.e.line("}")
        self.e.line()

    def _declare_locals(self, stmts: list, skip: set) -> None:
        decls: dict[str, str] = {}

        def visit(ss: list) -> None:
            for s in ss:
                k = type(s).__name__
                if k == "Assign" and isinstance(s.target, ir.Name):
                    name = s.target.id
                    if name not in skip and name not in decls:
                        decls[name] = _ctype(s.target.type)
                elif k == "If":
                    visit(s.body)
                    visit(s.orelse)
                elif k in ("While", "For"):
                    visit(s.body)

        visit(stmts)
        for name, cty in decls.items():
            self.e.line(f"{cty} {name};")

    # ---- statements -------------------------------------------------------
    def _stmt(self, node) -> None:
        k = type(node).__name__
        if k == "Assign":
            if isinstance(node.target, ir.Index):
                obj = self._expr(node.target.obj)
                idx = self._expr(node.target.index)
                self.e.line(f"{obj}.data[{idx}] = {self._expr(node.value)};")
            else:
                self.e.line(f"{node.target.id} = {self._expr(node.value)};")
        elif k == "ExprStmt":
            self._expr_stmt(node.value)
        elif k == "If":
            self._if(node)
        elif k == "While":
            self.e.line(f"while ({self._truthy(node.test)}) {{")
            self._block(node.body)
            self.e.line("}")
        elif k == "For":
            self._for(node)
        elif k == "Return":
            self.e.line("return;" if node.value is None else f"return {self._expr(node.value)};")
        elif k == "Pass":
            self.e.line(";")
        elif k == "Break":
            self.e.line("break;")
        elif k == "Continue":
            self.e.line("continue;")
        else:
            raise CompileError(f"C backend: cannot emit {k}")

    def _expr_stmt(self, value) -> None:
        k = type(value).__name__
        if k == "Call" and value.func == "print":
            self._print(value.args)
            return
        if k == "MethodCall" and value.method == "append":
            self.e.line(f"poly_list_append(&{self._expr(value.obj)}, {self._expr(value.args[0])});")
            return
        self.e.line(self._expr(value) + ";")

    def _print(self, args: list) -> None:
        self.e.line("{")
        self.e.indent()
        helper = {"int": "poly_print_int", "float": "poly_print_float", "bool": "poly_print_bool",
                  "str": "poly_print_str", "list": "poly_print_list"}
        for i, a in enumerate(args):
            if i:
                self.e.line('printf(" ");')
            kind = a.type.kind
            if kind not in helper:
                raise CompileError(f"C backend: cannot print value of type {a.type}")
            self.e.line(f"{helper[kind]}({self._expr(a)});")
        self.e.line(r'printf("\n");')
        self.e.dedent()
        self.e.line("}")

    def _if(self, node) -> None:
        self.e.line(f"if ({self._truthy(node.test)}) {{")
        self._block(node.body)
        orelse = node.orelse
        while len(orelse) == 1 and type(orelse[0]).__name__ == "If":
            nxt = orelse[0]
            self.e.line(f"}} else if ({self._truthy(nxt.test)}) {{")
            self._block(nxt.body)
            orelse = nxt.orelse
        if orelse:
            self.e.line("} else {")
            self._block(orelse)
        self.e.line("}")

    def _for(self, node) -> None:
        if isinstance(node.iterable, ir.Range):
            v = node.var
            start = self._expr(node.iterable.start)
            stop = self._expr(node.iterable.stop)
            step = self._expr(node.iterable.step)
            self.e.line(f"for (long {v} = {start}; "
                        f"(({step}) > 0 ? {v} < {stop} : {v} > {stop}); {v} += {step}) {{")
            self._block(node.body)
            self.e.line("}")
        else:
            lst = self._expr(node.iterable)
            self.e.line(f"{{ PolyList _it = {lst};")
            self.e.indent()
            self.e.line(f"for (long _i = 0; _i < _it.len; _i++) {{")
            self.e.indent()
            self.e.line(f"long {node.var} = _it.data[_i];")
            for s in node.body:
                self._stmt(s)
            self.e.dedent()
            self.e.line("}")
            self.e.dedent()
            self.e.line("}")

    def _block(self, stmts: list) -> None:
        self.e.indent()
        for s in stmts:
            self._stmt(s)
        self.e.dedent()

    # ---- expressions ------------------------------------------------------
    def _truthy(self, node) -> str:
        c = self._expr(node)
        kind = getattr(node, "type", T.UNKNOWN).kind
        if kind == "str":
            return f"poly_truthy_str({c})"
        if kind == "list":
            return f"(({c}).len != 0)"
        return f"(({c}) != 0)"

    def _expr(self, node) -> str:
        k = type(node).__name__
        if k == "Const":
            return self._const(node.value)
        if k == "Name":
            return node.id
        if k == "ListLit":
            if not node.elems:
                return "poly_list_lit(NULL, 0)"
            elems = ", ".join(self._expr(e) for e in node.elems)
            return f"poly_list_lit((long[]){{{elems}}}, {len(node.elems)})"
        if k == "BinOp":
            return self._binop(node)
        if k == "UnaryOp":
            o = self._expr(node.operand)
            if node.op == "not":
                return f"(!{self._truthy(node.operand)})"
            return f"({node.op}{o})"
        if k == "BoolOp":
            joiner = " && " if node.op == "and" else " || "
            return "(" + joiner.join(self._truthy(v) for v in node.values) + ")"
        if k == "Compare":
            l, r = self._expr(node.left), self._expr(node.right)
            if node.left.type.kind == "str" and node.op in ("==", "!="):
                return f"(strcmp({l}, {r}) {node.op} 0)"
            return f"({l} {node.op} {r})"
        if k == "Call":
            return self._call(node)
        if k == "MethodCall":
            raise CompileError("C backend: method calls are only supported as statements")
        if k == "Index":
            if node.obj.type.kind == "list":
                return f"{self._expr(node.obj)}.data[{self._expr(node.index)}]"
            raise CompileError("C backend: only list indexing is supported")
        if k == "Hole":
            raise CompileError("C backend: holes are not supported (v1)")
        raise CompileError(f"C backend: cannot emit {k}")

    def _const(self, v) -> str:
        if v is True:
            return "1"
        if v is False:
            return "0"
        if v is None:
            raise CompileError("C backend: None literal is not supported")
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, str):
            return self._c_string(v)
        if isinstance(v, float):
            return repr(v)
        return f"{v}L"

    @staticmethod
    def _c_string(s: str) -> str:
        out = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{out}"'

    def _call(self, node: ir.Call) -> str:
        name = node.func
        if name == "len":
            arg = node.args[0]
            if arg.type.kind == "list":
                return f"({self._expr(arg)}).len"
            if arg.type.kind == "str":
                return f"((long)strlen({self._expr(arg)}))"
            raise CompileError("C backend: len() needs a list or str")
        if name == "abs":
            arg = node.args[0]
            if arg.type.kind == "float":
                return f"fabs({self._expr(arg)})"
            return f"poly_iabs({self._expr(arg)})"
        if name == "int":
            return f"((long)({self._expr(node.args[0])}))"
        if name == "float":
            return f"((double)({self._expr(node.args[0])}))"
        if name in ("str", "range", "print"):
            raise CompileError(f"C backend: {name}() is not supported here (v1)")
        # user function
        return f"{name}(" + ", ".join(self._expr(a) for a in node.args) + ")"

    def _binop(self, node) -> str:
        l, r = self._expr(node.left), self._expr(node.right)
        op, kind = node.op, node.type.kind
        if op == "+":
            if kind == "list":
                return f"poly_list_concat({l}, {r})"
            if kind == "str":
                raise CompileError("C backend: string concatenation is future work")
            return f"({l} + {r})"
        if op == "*":
            if kind in ("list", "str"):
                raise CompileError("C backend: list/str repetition is future work")
            return f"({l} * {r})"
        if op == "-":
            return f"({l} - {r})"
        if op == "/":
            return f"((double)({l}) / (double)({r}))"
        if op == "//":
            if kind == "float":
                return f"poly_floordiv_float((double)({l}), (double)({r}))"
            return f"poly_floordiv_int({l}, {r})"
        if op == "%":
            if kind == "float":
                return f"poly_mod_float((double)({l}), (double)({r}))"
            return f"poly_mod_int({l}, {r})"
        if op == "**":
            if kind == "float":
                return f"pow((double)({l}), (double)({r}))"
            return f"poly_ipow({l}, {r})"
        return f"({l} {op} {r})"
