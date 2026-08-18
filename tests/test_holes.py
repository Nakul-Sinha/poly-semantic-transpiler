"""The LLM hole layer: mock fills pass the gates, bad fills are rejected, a broken
fill is repaired by the re-prompt loop, and --no-llm degrades to a stub."""
import pytest

from helpers import build
from poly.codegen import generate
from poly.codegen.base import iter_holes
from poly.llm import HoleFiller, gates
from poly.differential import have, outputs_match, run_cpython_source, run_target


def one_hole(src):
    module = build(src)
    return module, iter_holes(module)[0]


def test_mock_fill_passes_and_runs(tmp_path):
    src = "xs = [1,2,3,4,5,6]\nys = [x*x for x in xs if x % 2 == 0]\nprint(ys)\n"
    module = build(src)
    HoleFiller(mode="mock", cache_dir=str(tmp_path)).fill_for_target(module, "py")
    assert module and iter_holes(module)[0].filled.get("py")
    if have("python"):
        assert outputs_match(run_target(module, "py"), run_cpython_source(src))


def test_gate_b_rejects_forbidden_capability(tmp_path):
    _, hole = one_hole("xs=[1,2,3]\nys=[x for x in xs]\n")
    ok, msg = gates.gate_b_scope(hole.contract, 'return require("fs");', "js")
    assert not ok and "require" in msg


def test_gate_b_rejects_out_of_scope_name(tmp_path):
    _, hole = one_hole("xs=[1,2,3]\nys=[x for x in xs]\n")
    ok, msg = gates.gate_b_scope(hole.contract, "return zzz.map(x => x);", "js")
    assert not ok and "zzz" in msg


@pytest.mark.skipif(not have("node"), reason="node not installed")
def test_gate_c_rejects_wrong_behavior():
    _, hole = one_hole("xs=[1,2,3,4]\nys=[x*x for x in xs if x % 2 == 0]\n")
    ok, msg = gates.gate_c_behavioral(hole.contract, "return xs.map(x => x);", "js")
    assert not ok and "Python gives" in msg


@pytest.mark.skipif(not have("node"), reason="node not installed")
def test_broken_fill_is_rejected_then_repaired(tmp_path):
    module = build("xs=[1,2,3,4]\nys=[x*2 for x in xs]\n")
    hole = iter_holes(module)[0]

    class Scripted(HoleFiller):
        def __init__(self):
            super().__init__(mode="mock", cache_dir=str(tmp_path))
            self.scripts = ["return zzz.map(x => x);",       # gate B: out of scope
                            "return xs.map(x => (x * 2));"]   # correct
            self.i = 0

        def _propose(self, contract, target, feedback):
            body = self.scripts[min(self.i, len(self.scripts) - 1)]
            self.i += 1
            return body

    filler = Scripted()
    body = filler.fill(hole, "js")
    assert body == "return xs.map(x => (x * 2));"
    rec = filler.records[-1]
    assert rec.attempts == 2 and rec.gate_failures    # first attempt was rejected


def test_no_llm_leaves_marked_stub():
    module = build("xs=[1,2,3]\nys=[x for x in xs]\n")
    js = generate(module, "js")            # holes never filled
    assert "UNSUPPORTED" in js
