"""Differential codegen tests: each target's output must equal CPython's.

Parametrized over every example file x every target. Targets whose toolchain is
missing are skipped (not failed). Hole-bearing programs skip the C target (holes
are unsupported for C in v1).
"""
import pytest

import conftest
from helpers import build
from poly.codegen import generate
from poly.codegen.base import iter_holes
from poly.llm import HoleFiller
from poly.differential import (
    TARGET_TOOL, have, outputs_match, run_cpython_source, run_target,
)

EXAMPLES = sorted(conftest.EXAMPLES.glob("*.py"))
TARGETS = ["js", "py", "c"]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.name)
@pytest.mark.parametrize("target", TARGETS)
def test_example_matches_cpython(example, target):
    src = example.read_text(encoding="utf-8")
    module = build(src)
    has_holes = bool(iter_holes(module))

    if has_holes and target == "c":
        pytest.skip("holes are not supported for the C target (v1)")
    if not have(TARGET_TOOL[target]):
        pytest.skip(f"{TARGET_TOOL[target]} not installed")

    if has_holes and target in ("js", "py"):
        HoleFiller(mode="mock").fill_for_target(module, target)

    ref = run_cpython_source(src)
    out = run_target(module, target)
    assert outputs_match(out, ref), f"{example.name} [{target}]\nout: {out!r}\nref: {ref!r}"


def test_generate_rejects_unknown_target():
    with pytest.raises(ValueError):
        generate(build("print(1)\n"), "rust")
