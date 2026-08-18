"""The 3-way differential self-check must catch a real codegen bug."""
import pytest

import poly.codegen.javascript as jsmod
from helpers import build
from poly.differential import have, self_check


def test_selfcheck_passes_on_correct_codegen():
    src = "print(-7 // 2, 7 % 3, 2 ** 5)\n"
    report = self_check(src, build(src))
    assert report["ok"], report


@pytest.mark.skipif(not have("node"), reason="node not installed")
def test_selfcheck_catches_planted_floordiv_bug(monkeypatch):
    # plant a bug: emit Python `//` as JavaScript `/` (truncation vs floor)
    original = jsmod.JsGen._binop

    def buggy(self, node):
        if node.op == "//":
            return f"({self._expr(node.left)} / {self._expr(node.right)})"
        return original(self, node)

    monkeypatch.setattr(jsmod.JsGen, "_binop", buggy)

    src = "print(-7 // 2)\n"          # CPython: -4 ; buggy JS: -3.5
    report = self_check(src, build(src), targets=("js",))
    js_row = next(r for r in report["rows"] if r["name"] == "js target")
    assert js_row["status"] == "FAIL"
    assert not report["ok"]
