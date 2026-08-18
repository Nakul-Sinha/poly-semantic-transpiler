"""The IR interpreter must agree with CPython on the supported subset."""
import pytest

from helpers import build
from poly.interp import interpret
from poly.differential import run_cpython_source, outputs_match

PROGRAMS = [
    "print(7 // 2, -7 // 2, 7 % 3, -7 % 3, 2 ** 8, 10 / 4)\n",
    "print(1 + 2 * 3 - 4)\n",
    "s = 0\nfor i in range(1, 6):\n    s = s + i\nprint(s)\n",
    "def fib(n: int) -> int:\n    a = 0\n    b = 1\n    for i in range(n):\n        t = a + b\n        a = b\n        b = t\n    return a\nprint(fib(10))\n",
    "xs = [3, 1, 2]\nxs.append(9)\nprint(xs, len(xs), xs[0], xs[3])\n",
    "print(True and False, True or False, not True)\n",
    "n = 5\nif n > 3 and n < 10:\n    print('mid')\nelse:\n    print('other')\n",
    "i = 0\nwhile i < 10:\n    i = i + 1\n    if i == 5:\n        break\nprint(i)\n",
    "ys = [x * x for x in [1,2,3,4] if x % 2 == 0]\nprint(ys)\n",  # hole via CPython eval
    "print([1,2] + [3,4], 'ab' * 3, [0] * 4)\n",
]


@pytest.mark.parametrize("src", PROGRAMS)
def test_interp_matches_cpython(src):
    got = interpret(build(src))
    ref = run_cpython_source(src)
    assert outputs_match(got, ref), f"\nIR : {got!r}\nref: {ref!r}"
