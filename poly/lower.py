"""Lower the annotated AST to the Semantic IR.

Desugarings performed here (so back-ends never see Python-only sugar):
  * ``t op= e``            -> ``t = (t op e)``
  * ``a < b < c``          -> ``(a < b) and (b < c)``
  * ``for x in range(...)``-> ``For(x, Range(...), body)``
  * ``for x in <list>``    -> ``For(x, <list>, body)``

Unsupported-but-pure subtrees (comprehensions, slices) become :class:`ir.Hole`
nodes carrying a compiler-derived contract. Unsupported-and-impure subtrees raise
``CompileError`` — the LLM is never handed anything impure.
"""
from __future__ import annotations

from . import ast_nodes as A
from . import ir
from . import types as T
from .errors import CompileError
from .unparse import unparse_expr

BUILTINS = {"print", "len", "range", "abs", "int", "float", "str"}


class Lowerer:
    def __init__(self) -> None:
        self.hole_counter = 0

    def lower_module(self, module: A.Module) -> ir.Module:
        funcs: list = []
        body: list = []
        for stmt in module.body:
            if isinstance(stmt, A.FunctionDef):
                funcs.append(self._function(stmt))
            else:
                body.append(self._stmt(stmt))
        return ir.Module(body, funcs)

    def _function(self, fn: A.FunctionDef) -> ir.Function:
        params = [
            ir.Param(p.name, getattr(p, "type", T.UNKNOWN),
                     self._expr(p.default) if p.default is not None else None)
            for p in fn.params
        ]
        ret = getattr(fn, "ret_type", T.UNKNOWN)
        body = [self._stmt(s) for s in fn.body]
        return ir.Function(fn.name, params, body, ret)

    # ---- statements -------------------------------------------------------
    def _stmt(self, node):
        if isinstance(node, A.Assign):
            return ir.Assign(self._expr(node.target), self._expr(node.value))
        if isinstance(node, A.AugAssign):
            target = self._expr(node.target)
            value = self._expr(node.value)
            combined = ir.BinOp(node.op, target, value, getattr(target, "type", T.UNKNOWN))
            return ir.Assign(target, combined)
        if isinstance(node, A.ExprStmt):
            return ir.ExprStmt(self._expr(node.value))
        if isinstance(node, A.If):
            return ir.If(self._expr(node.test),
                         [self._stmt(s) for s in node.body],
                         [self._stmt(s) for s in node.orelse])
        if isinstance(node, A.While):
            return ir.While(self._expr(node.test), [self._stmt(s) for s in node.body])
        if isinstance(node, A.For):
            return ir.For(node.var, self._iterable(node.iter),
                          [self._stmt(s) for s in node.body])
        if isinstance(node, A.Return):
            return ir.Return(self._expr(node.value) if node.value is not None else None)
        if isinstance(node, A.Pass):
            return ir.Pass()
        if isinstance(node, A.Break):
            return ir.Break()
        if isinstance(node, A.Continue):
            return ir.Continue()
        raise CompileError(f"cannot lower statement {type(node).__name__}", getattr(node, "span", None))

    def _iterable(self, node):
        if isinstance(node, A.Call) and isinstance(node.func, A.Name) and node.func.id == "range":
            args = node.args
            zero = ir.Const(0, T.INT)
            one = ir.Const(1, T.INT)
            if len(args) == 1:
                return ir.Range(zero, self._expr(args[0]), one)
            if len(args) == 2:
                return ir.Range(self._expr(args[0]), self._expr(args[1]), one)
            if len(args) == 3:
                return ir.Range(self._expr(args[0]), self._expr(args[1]), self._expr(args[2]))
            raise CompileError("range() takes 1 to 3 arguments", node.span)
        return self._expr(node)

    # ---- expressions ------------------------------------------------------
    def _expr(self, node):
        if isinstance(node, A.Num):
            return ir.Const(node.value, node.type)
        if isinstance(node, A.Str):
            return ir.Const(node.value, T.STR)
        if isinstance(node, A.Const):
            return ir.Const(node.value, node.type)
        if isinstance(node, A.Name):
            return ir.Name(node.id, getattr(node, "type", T.UNKNOWN))
        if isinstance(node, A.ListExpr):
            return ir.ListLit([self._expr(e) for e in node.elems], node.type)
        if isinstance(node, A.BinOp):
            return ir.BinOp(node.op, self._expr(node.left), self._expr(node.right), node.type)
        if isinstance(node, A.UnaryOp):
            return ir.UnaryOp(node.op, self._expr(node.operand), node.type)
        if isinstance(node, A.BoolOp):
            return ir.BoolOp(node.op, [self._expr(v) for v in node.values], node.type)
        if isinstance(node, A.Compare):
            return self._compare(node)
        if isinstance(node, A.Call):
            return self._call(node)
        if isinstance(node, A.Subscript):
            return ir.Index(self._expr(node.obj), self._expr(node.index), node.type)
        if isinstance(node, A.SliceExpr):
            return self._hole(node, "slice")
        if isinstance(node, A.Comprehension):
            return self._hole(node, "list_comprehension")
        raise CompileError(f"cannot lower expression {type(node).__name__}", getattr(node, "span", None))

    def _compare(self, node: A.Compare):
        operands = [self._expr(node.left)] + [self._expr(c) for c in node.comparators]
        pairs = [ir.Compare(node.ops[i], operands[i], operands[i + 1], T.BOOL)
                 for i in range(len(node.ops))]
        if len(pairs) == 1:
            return pairs[0]
        return ir.BoolOp("and", pairs, T.BOOL)

    def _call(self, node: A.Call):
        if isinstance(node.func, A.Attribute):
            return ir.MethodCall(self._expr(node.func.obj), node.func.attr,
                                 [self._expr(a) for a in node.args], node.type)
        assert isinstance(node.func, A.Name)
        return ir.Call(node.func.id, [self._expr(a) for a in node.args], node.type)

    # ---- holes ------------------------------------------------------------
    def _hole(self, node, kind: str) -> ir.Hole:
        if not getattr(node, "pure", False):
            raise CompileError(f"{kind} here is impure and cannot be delegated to the LLM",
                               getattr(node, "span", None))
        found: dict[str, T.Type] = {}
        self._collect_free(node, set(), found)
        free = [ir.VarInfo(name, t) for name, t in found.items()]
        hid = f"hole_{self.hole_counter}"
        self.hole_counter += 1
        result_type = getattr(node, "type", T.UNKNOWN)
        contract = ir.HoleContract(
            hole_id=hid,
            kind=kind,
            source=unparse_expr(node),
            free_vars=free,
            result_type=result_type,
            fn_name=hid,
            param_names=[v.name for v in free],
        )
        return ir.Hole(hid, contract, result_type, {})

    def _collect_free(self, node, bound: set, found: dict) -> None:
        if isinstance(node, A.Name):
            if node.id not in bound and node.id not in BUILTINS:
                found.setdefault(node.id, getattr(node, "type", T.UNKNOWN))
            return
        if isinstance(node, A.Comprehension):
            self._collect_free(node.iter, bound, found)
            inner = bound | {node.var}
            self._collect_free(node.element, inner, found)
            if node.cond is not None:
                self._collect_free(node.cond, inner, found)
            return
        if isinstance(node, A.Attribute):
            self._collect_free(node.obj, bound, found)
            return
        for f, v in vars(node).items():
            if f == "span":
                continue
            if isinstance(v, list):
                for x in v:
                    if hasattr(x, "__dataclass_fields__"):
                        self._collect_free(x, bound, found)
            elif hasattr(v, "__dataclass_fields__"):
                self._collect_free(v, bound, found)


def lower(module: A.Module) -> ir.Module:
    return Lowerer().lower_module(module)
