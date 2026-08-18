"""Semantic analysis: scope resolution, type inference, and purity.

Walks the AST and, in place, sets ``node.type`` (a types.Type) and ``node.pure``
(bool) on every expression. It also:
  * reports undeclared names, returns outside functions, break/continue outside
    loops, unsupported methods, and unknown type annotations;
  * infers function return types when they are not annotated.

Inference is flow-insensitive and best-effort — ``unknown`` is a valid answer that
the JS/Python back-ends tolerate and the C back-end rejects with a clear message.
"""
from __future__ import annotations

from . import ast_nodes as A
from . import types as T
from .errors import SemanticError
from .symbols import Scope, Symbol, new_module_scope

PURE_BUILTINS = {"len", "abs", "int", "float", "str", "range"}
SUPPORTED_METHODS = {"append"}  # list.append(x) -> None, impure (mutation)


class Analyzer:
    def __init__(self, module: A.Module, source: str = ""):
        self.module = module
        self.source = source
        self.module_scope = new_module_scope()
        self.func_return: dict[str, T.Type] = {}
        self._returns_seen: list[T.Type] = []
        self.in_function = False
        self.loop_depth = 0

    # ---- public entry -----------------------------------------------------
    def analyze(self) -> A.Module:
        # pass 1: register all top-level functions (so calls resolve regardless of order)
        for stmt in self.module.body:
            if isinstance(stmt, A.FunctionDef):
                ptypes = []
                for p in stmt.params:
                    p.type = self._resolve_annotation(p.annotation) or T.UNKNOWN
                    ptypes.append(p.type)
                ret = self._resolve_annotation(stmt.returns) or T.UNKNOWN
                stmt.ret_type = ret
                self.module_scope.define(Symbol(stmt.name, T.func(tuple(ptypes), ret), "func"))
                self.func_return[stmt.name] = ret
        # pass 2: analyze module-level statements (defines module vars)
        for stmt in self.module.body:
            if not isinstance(stmt, A.FunctionDef):
                self._stmt(stmt, self.module_scope)
        # pass 3: analyze function bodies (now all module names are visible)
        for stmt in self.module.body:
            if isinstance(stmt, A.FunctionDef):
                self._function(stmt)
        return self.module

    # ---- annotations ------------------------------------------------------
    def _resolve_annotation(self, node) -> T.Type | None:
        if node is None:
            return None
        prims = {"int": T.INT, "float": T.FLOAT, "bool": T.BOOL, "str": T.STR}
        if isinstance(node, A.Name):
            if node.id in prims:
                return prims[node.id]
            if node.id == "list":
                return T.list_of(T.UNKNOWN)
            raise SemanticError(f"unknown type annotation {node.id!r}", node.span)
        if isinstance(node, A.Subscript) and isinstance(node.obj, A.Name) and node.obj.id == "list":
            elem = self._resolve_annotation(node.index) or T.UNKNOWN
            return T.list_of(elem)
        raise SemanticError("malformed type annotation", node.span)

    # ---- functions --------------------------------------------------------
    def _function(self, fn: A.FunctionDef) -> None:
        scope = Scope("function", parent=self.module_scope)
        for p in fn.params:
            ptype = self._resolve_annotation(p.annotation) or T.UNKNOWN
            scope.define(Symbol(p.name, ptype, "param"))
            if p.default is not None:
                self._expr(p.default, self.module_scope)
        self._collect_locals(fn.body, scope)
        prev_fn, prev_returns = self.in_function, self._returns_seen
        self.in_function, self._returns_seen = True, []
        for s in fn.body:
            self._stmt(s, scope)
        # refine return type from observed returns when it was not annotated
        if self.func_return.get(fn.name, T.UNKNOWN).kind == "unknown" and self._returns_seen:
            inferred = self._returns_seen[0]
            for t in self._returns_seen[1:]:
                inferred = T.join(inferred, t)
            self.func_return[fn.name] = inferred
            fn.ret_type = inferred
            sym = self.module_scope.lookup_local(fn.name)
            if sym is not None:
                sym.type = T.func(sym.type.params, inferred)
        self.in_function, self._returns_seen = prev_fn, prev_returns

    def _collect_locals(self, stmts: list, scope: Scope) -> None:
        """Pre-declare names assigned anywhere in a function body as locals."""
        for s in stmts:
            if isinstance(s, (A.Assign, A.AugAssign)) and isinstance(s.target, A.Name):
                if scope.lookup_local(s.target.id) is None:
                    scope.define(Symbol(s.target.id, T.UNKNOWN, "var"))
            elif isinstance(s, A.For):
                if scope.lookup_local(s.var) is None:
                    scope.define(Symbol(s.var, T.UNKNOWN, "var"))
                self._collect_locals(s.body, scope)
            elif isinstance(s, A.If):
                self._collect_locals(s.body, scope)
                self._collect_locals(s.orelse, scope)
            elif isinstance(s, A.While):
                self._collect_locals(s.body, scope)
            elif isinstance(s, A.FunctionDef):
                raise SemanticError("nested function definitions are not supported", s.span)

    # ---- statements -------------------------------------------------------
    def _stmt(self, node, scope: Scope) -> None:
        if isinstance(node, A.FunctionDef):
            raise SemanticError("nested function definitions are not supported", node.span)
        if isinstance(node, A.Assign):
            vt = self._expr(node.value, scope)
            if isinstance(node.target, A.Name):
                sym = scope.lookup_local(node.target.id)
                if sym is None:
                    sym = Symbol(node.target.id, vt, "var")
                    scope.define(sym)
                else:
                    sym.type = vt if T.is_unknown(sym.type) else T.join(sym.type, vt)
                node.target.type = sym.type
                node.target.pure = True
            else:  # subscript assignment (mutation)
                self._expr(node.target, scope)
            return
        if isinstance(node, A.AugAssign):
            vt = self._expr(node.value, scope)
            tt = self._expr(node.target, scope)
            result = self._binop_type(node.op, tt, vt)
            if isinstance(node.target, A.Name):
                sym = scope.lookup(node.target.id)
                if sym is not None:
                    sym.type = result
                    node.target.type = result
            return
        if isinstance(node, A.ExprStmt):
            self._expr(node.value, scope)
            return
        if isinstance(node, A.If):
            self._expr(node.test, scope)
            for s in node.body:
                self._stmt(s, scope)
            for s in node.orelse:
                self._stmt(s, scope)
            return
        if isinstance(node, A.While):
            self._expr(node.test, scope)
            self.loop_depth += 1
            for s in node.body:
                self._stmt(s, scope)
            self.loop_depth -= 1
            return
        if isinstance(node, A.For):
            it = self._expr(node.iter, scope)
            elem = self._iter_elem_type(node.iter, it)
            sym = scope.lookup_local(node.var)
            if sym is None:
                sym = Symbol(node.var, elem, "var")
                scope.define(sym)
            else:
                sym.type = elem
            self.loop_depth += 1
            for s in node.body:
                self._stmt(s, scope)
            self.loop_depth -= 1
            return
        if isinstance(node, A.Return):
            if not self.in_function:
                raise SemanticError("'return' outside function", node.span)
            rt = self._expr(node.value, scope) if node.value is not None else T.NONE
            self._returns_seen.append(rt)
            return
        if isinstance(node, (A.Break, A.Continue)):
            if self.loop_depth == 0:
                kw = "break" if isinstance(node, A.Break) else "continue"
                raise SemanticError(f"'{kw}' outside loop", node.span)
            return
        if isinstance(node, A.Pass):
            return
        raise SemanticError(f"unsupported statement {type(node).__name__}", getattr(node, "span", None))

    def _iter_elem_type(self, iter_node, iter_type: T.Type) -> T.Type:
        if iter_type.kind == "list":
            return iter_type.elem or T.UNKNOWN
        if iter_type.kind == "str":
            return T.STR
        return T.UNKNOWN

    # ---- expressions ------------------------------------------------------
    def _expr(self, node, scope: Scope) -> T.Type:
        t = self._expr_inner(node, scope)
        node.type = t
        if not hasattr(node, "pure"):
            node.pure = True
        return t

    def _expr_inner(self, node, scope: Scope) -> T.Type:
        if isinstance(node, A.Num):
            node.pure = True
            return T.FLOAT if isinstance(node.value, float) else T.INT
        if isinstance(node, A.Str):
            node.pure = True
            return T.STR
        if isinstance(node, A.Const):
            node.pure = True
            return T.BOOL if isinstance(node.value, bool) else T.NONE
        if isinstance(node, A.Name):
            sym = scope.lookup(node.id)
            if sym is None:
                raise SemanticError(f"undeclared name {node.id!r}", node.span)
            node.pure = True
            return sym.type
        if isinstance(node, A.ListExpr):
            elem: T.Type = T.UNKNOWN
            pure = True
            for e in node.elems:
                et = self._expr(e, scope)
                elem = T.join(elem, et)
                pure = pure and e.pure
            node.pure = pure
            return T.list_of(elem)
        if isinstance(node, A.BinOp):
            lt = self._expr(node.left, scope)
            rt = self._expr(node.right, scope)
            node.pure = node.left.pure and node.right.pure
            return self._binop_type(node.op, lt, rt)
        if isinstance(node, A.UnaryOp):
            ot = self._expr(node.operand, scope)
            node.pure = node.operand.pure
            return T.BOOL if node.op == "not" else ot
        if isinstance(node, A.BoolOp):
            joined: T.Type = T.UNKNOWN
            pure = True
            for v in node.values:
                vt = self._expr(v, scope)
                joined = T.join(joined, vt)
                pure = pure and v.pure
            node.pure = pure
            return joined
        if isinstance(node, A.Compare):
            self._expr(node.left, scope)
            pure = node.left.pure
            for c in node.comparators:
                self._expr(c, scope)
                pure = pure and c.pure
            node.pure = pure
            return T.BOOL
        if isinstance(node, A.Call):
            return self._call(node, scope)
        if isinstance(node, A.Subscript):
            ot = self._expr(node.obj, scope)
            self._expr(node.index, scope)
            node.pure = node.obj.pure and node.index.pure
            if ot.kind == "list":
                return ot.elem or T.UNKNOWN
            if ot.kind == "str":
                return T.STR
            return T.UNKNOWN
        if isinstance(node, A.SliceExpr):
            ot = self._expr(node.obj, scope)
            pure = node.obj.pure
            for part in (node.lower, node.upper, node.step):
                if part is not None:
                    self._expr(part, scope)
                    pure = pure and part.pure
            node.pure = pure
            return ot  # slice of a list is a list; of a str is a str
        if isinstance(node, A.Comprehension):
            it = self._expr(node.iter, scope)
            elem_t = self._iter_elem_type(node.iter, it)
            sub = Scope("comprehension", parent=scope)
            sub.define(Symbol(node.var, elem_t, "var"))
            et = self._expr(node.element, sub)
            pure = node.element.pure and node.iter.pure
            if node.cond is not None:
                self._expr(node.cond, sub)
                pure = pure and node.cond.pure
            node.pure = pure
            return T.list_of(et)
        if isinstance(node, A.Attribute):
            raise SemanticError("attribute access is only supported as a method call", node.span)
        raise SemanticError(f"unsupported expression {type(node).__name__}", getattr(node, "span", None))

    def _call(self, node: A.Call, scope: Scope) -> T.Type:
        # method call: obj.method(args)
        if isinstance(node.func, A.Attribute):
            self._expr(node.func.obj, scope)
            method = node.func.attr
            if method not in SUPPORTED_METHODS:
                raise SemanticError(f"unsupported method {method!r}", node.func.span)
            for a in node.args:
                self._expr(a, scope)
            node.pure = False  # mutation
            return T.NONE
        if not isinstance(node.func, A.Name):
            raise SemanticError("only simple function calls are supported", node.span)
        name = node.func.id
        sym = scope.lookup(name)
        if sym is None:
            raise SemanticError(f"undeclared name {name!r}", node.func.span)
        arg_types = [self._expr(a, scope) for a in node.args]
        args_pure = all(a.pure for a in node.args)
        if sym.kind == "builtin":
            node.pure = args_pure and name in PURE_BUILTINS
            return self._builtin_return(name, arg_types)
        # user function: conservatively impure (v1 holes never call user funcs)
        node.pure = False
        return self.func_return.get(name, T.UNKNOWN)

    def _builtin_return(self, name: str, arg_types: list[T.Type]) -> T.Type:
        if name == "len":
            return T.INT
        if name == "range":
            return T.list_of(T.INT)
        if name == "int":
            return T.INT
        if name == "float":
            return T.FLOAT
        if name == "str":
            return T.STR
        if name == "abs":
            return arg_types[0] if arg_types and T.is_numeric(arg_types[0]) else T.UNKNOWN
        if name == "print":
            return T.NONE
        return T.UNKNOWN

    def _binop_type(self, op: str, lt: T.Type, rt: T.Type) -> T.Type:
        if op in ("+", "-", "*", "/", "//", "%", "**"):
            if op == "+" and lt.kind == "str" and rt.kind == "str":
                return T.STR
            if op == "+" and lt.kind == "list" and rt.kind == "list":
                return T.list_of(T.join(lt.elem, rt.elem))
            if op == "*" and lt.kind == "str" and T.is_numeric(rt):
                return T.STR
            if op == "*" and lt.kind == "list" and T.is_numeric(rt):
                return lt
            if T.is_numeric(lt) and T.is_numeric(rt):
                return T.numeric_result(lt, rt, op)
            return T.UNKNOWN
        return T.UNKNOWN


def analyze(module: A.Module, source: str = "") -> A.Module:
    return Analyzer(module, source).analyze()
