"""Reference interpreter over the Semantic IR — the project's semantic oracle.

Executing the IR with ordinary Python values means IR semantics coincide with
CPython semantics *by construction* for the supported operators. The differential
harness then checks:  CPython(source) == interp(IR) == run(target codegen).
Agreement of the first two validates lowering + interpretation; agreement of the
third validates a back-end. A bug in any single stage shows up as a divergence.

A :class:`ir.Hole` is evaluated by running its original Python ``source`` in a
restricted namespace built from the current values of its free variables (sound
because holes are purity-gated).
"""
from __future__ import annotations

from . import ir

# safe builtins exposed to hole evaluation
_SAFE = {"len": len, "abs": abs, "int": int, "float": float, "str": str,
         "range": range, "True": True, "False": False, "None": None}


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class Interpreter:
    def __init__(self, module: ir.Module):
        self.module = module
        self.funcs = {f.name: f for f in module.funcs}
        self.globals: dict = {}
        self.out: list[str] = []

    def run(self) -> str:
        """Execute the program; return everything it printed to stdout."""
        self.globals = {}
        for stmt in self.module.body:
            self._exec(stmt, self.globals)
        return "".join(self.out)

    # ---- statements -------------------------------------------------------
    def _exec(self, node, env: dict) -> None:
        k = type(node).__name__
        if k == "Assign":
            value = self._eval(node.value, env)
            if isinstance(node.target, ir.Name):
                env[node.target.id] = value
            else:  # ir.Index
                obj = self._eval(node.target.obj, env)
                idx = self._eval(node.target.index, env)
                obj[idx] = value
        elif k == "ExprStmt":
            self._eval(node.value, env)
        elif k == "If":
            if self._truthy(self._eval(node.test, env)):
                self._exec_block(node.body, env)
            else:
                self._exec_block(node.orelse, env)
        elif k == "While":
            while self._truthy(self._eval(node.test, env)):
                try:
                    self._exec_block(node.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif k == "For":
            for value in self._iter(node.iterable, env):
                env[node.var] = value
                try:
                    self._exec_block(node.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif k == "Return":
            raise _Return(self._eval(node.value, env) if node.value is not None else None)
        elif k == "Break":
            raise _Break()
        elif k == "Continue":
            raise _Continue()
        elif k == "Pass":
            pass
        else:
            raise RuntimeError(f"interpreter: cannot execute {k}")

    def _exec_block(self, stmts: list, env: dict) -> None:
        for s in stmts:
            self._exec(s, env)

    def _iter(self, iterable, env):
        if isinstance(iterable, ir.Range):
            start = self._eval(iterable.start, env)
            stop = self._eval(iterable.stop, env)
            step = self._eval(iterable.step, env)
            if step == 0:
                raise RuntimeError("range() step must not be zero")
            return list(range(start, stop, step))
        return self._eval(iterable, env)

    # ---- expressions ------------------------------------------------------
    def _eval(self, node, env: dict):
        k = type(node).__name__
        if k == "Const":
            return node.value
        if k == "Name":
            if node.id in env:
                return env[node.id]
            if node.id in self.globals:
                return self.globals[node.id]
            raise RuntimeError(f"name {node.id!r} is not defined")
        if k == "ListLit":
            return [self._eval(e, env) for e in node.elems]
        if k == "BinOp":
            return self._binop(node.op, self._eval(node.left, env), self._eval(node.right, env))
        if k == "UnaryOp":
            v = self._eval(node.operand, env)
            if node.op == "not":
                return not self._truthy(v)
            return -v if node.op == "-" else +v
        if k == "BoolOp":
            result = None
            for v in node.values:
                result = self._eval(v, env)
                if node.op == "and" and not self._truthy(result):
                    return result
                if node.op == "or" and self._truthy(result):
                    return result
            return result
        if k == "Compare":
            return self._compare(node.op, self._eval(node.left, env), self._eval(node.right, env))
        if k == "Call":
            return self._call(node, env)
        if k == "MethodCall":
            obj = self._eval(node.obj, env)
            if node.method == "append":
                obj.append(self._eval(node.args[0], env))
                return None
            raise RuntimeError(f"unsupported method {node.method!r}")
        if k == "Index":
            return self._eval(node.obj, env)[self._eval(node.index, env)]
        if k == "Range":
            start = self._eval(node.start, env)
            return list(range(start, self._eval(node.stop, env), self._eval(node.step, env)))
        if k == "Hole":
            return self._eval_hole(node, env)
        raise RuntimeError(f"interpreter: cannot evaluate {k}")

    def _call(self, node: ir.Call, env: dict):
        args = [self._eval(a, env) for a in node.args]
        name = node.func
        if name == "print":
            self.out.append(" ".join(self._pystr(a) for a in args) + "\n")
            return None
        if name == "len":
            return len(args[0])
        if name == "abs":
            return abs(args[0])
        if name == "int":
            return int(args[0])
        if name == "float":
            return float(args[0])
        if name == "str":
            return self._pystr(args[0])
        if name == "range":
            return list(range(*args))
        if name in self.funcs:
            return self._call_user(self.funcs[name], args)
        raise RuntimeError(f"unknown function {name!r}")

    def _call_user(self, fn: ir.Function, args: list):
        local: dict = {}
        for i, p in enumerate(fn.params):
            if i < len(args):
                local[p.name] = args[i]
            elif p.default is not None:
                local[p.name] = self._eval(p.default, self.globals)
            else:
                raise RuntimeError(f"{fn.name}() missing argument {p.name!r}")
        try:
            self._exec_block(fn.body, local)
        except _Return as r:
            return r.value
        return None

    def _eval_hole(self, node: ir.Hole, env: dict):
        ns = {}
        for v in node.contract.free_vars:
            ns[v.name] = env[v.name] if v.name in env else self.globals[v.name]
        code = compile(node.contract.source, "<hole>", "eval")
        return eval(code, {"__builtins__": {}, **_SAFE}, ns)  # noqa: S307 (pure, gated)

    # ---- primitive semantics (delegated to Python to match CPython) -------
    @staticmethod
    def _binop(op, a, b):
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b
        if op == "//":
            return a // b
        if op == "%":
            return a % b
        if op == "**":
            return a ** b
        raise RuntimeError(f"unknown operator {op!r}")

    @staticmethod
    def _compare(op, a, b):
        return {"==": a == b, "!=": a != b, "<": a < b,
                "<=": a <= b, ">": a > b, ">=": a >= b}[op]

    @staticmethod
    def _truthy(v) -> bool:
        return bool(v)

    @staticmethod
    def _pystr(v) -> str:
        if v is True:
            return "True"
        if v is False:
            return "False"
        if v is None:
            return "None"
        return str(v)


def interpret(module: ir.Module) -> str:
    return Interpreter(module).run()
