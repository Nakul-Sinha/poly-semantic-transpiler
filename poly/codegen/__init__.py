"""Code generators: one back-end per target language, all driven by the IR.

    from poly.codegen import generate
    src = generate(ir_module, "js")   # or "py", "c"
"""
from __future__ import annotations

from .. import ir
from .c import CGen
from .javascript import JsGen
from .python import PyGen

_BACKENDS = {"js": JsGen, "py": PyGen, "python": PyGen, "c": CGen}


def generate(module: ir.Module, target: str) -> str:
    if target not in _BACKENDS:
        raise ValueError(f"unknown target {target!r}; choose from js, py, c")
    return _BACKENDS[target](module).generate()
