"""The web server's API functions drive the real pipeline (no sockets needed)."""
import sys

import conftest

sys.path.insert(0, str(conftest.ROOT / "web"))
import server  # noqa: E402


def test_transpile_hole_free_js():
    r = server.api_transpile({"source": "print(1 + 2)\n", "target": "js"})
    assert r["ok"] and "poly_print" in r["code"] and r["records"] == []


def test_transpile_error_is_rendered():
    r = server.api_transpile({"source": "y = x + 1\n", "target": "js"})
    assert not r["ok"]
    assert "undeclared name 'x'" in r["error"]["message"]
    assert "^" in r["error"]["rendered"]


def test_transpile_hole_via_mock():
    src = "xs = [1, 2, 3, 4]\nys = [x * x for x in xs if x % 2 == 0]\nprint(ys)\n"
    r = server.api_transpile({"source": src, "target": "py"})
    assert r["ok"] and r["records"]
    assert r["records"][0]["via"] in ("mock", "cache")
    assert "def hole_0(xs):" in r["code"]


def test_transpile_c_with_holes_fails_cleanly():
    r = server.api_transpile({"source": "xs = [1]\nys = [x for x in xs]\n", "target": "c"})
    assert not r["ok"] and "not supported for the C target" in r["error"]["message"]


def test_selfcheck_reports_rows():
    r = server.api_selfcheck({"source": "print(7 // 2, -7 // 2)\n"})
    assert r["ok"] and r["all_ok"] is True
    names = {row["name"] for row in r["rows"]}
    assert "IR interpreter" in names
