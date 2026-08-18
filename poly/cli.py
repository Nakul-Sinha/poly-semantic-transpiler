"""Command-line driver for Poly.

    python -m poly prog.py --target js            # transpile to JavaScript (stdout)
    python -m poly prog.py -t c -o prog.c         # transpile to C, write a file
    python -m poly prog.py --dump ast             # inspect a pipeline stage
    python -m poly prog.py --self-check           # 3-way differential report
    python -m poly prog.py -t js --no-llm         # prove the compiler is complete w/o the LLM
"""
from __future__ import annotations

import argparse
import sys

from . import ir
from .codegen import generate
from .codegen.base import iter_holes
from .differential import self_check
from .errors import PolyError
from .lexer import tokenize
from .lower import lower
from .parser import parse
from .semantic import analyze


def _build(source: str):
    """Front-half of the pipeline: source -> (tokens, ast, ir module)."""
    tokens = tokenize(source)
    ast = analyze(parse(tokens), source)
    module = lower(ast)
    return tokens, ast, module


def _pretty(node, indent: int = 0) -> str:
    from . import types as T
    pad = "  " * indent
    if not hasattr(node, "__dataclass_fields__"):
        return f"{pad}{node!r}"
    out = [f"{pad}{type(node).__name__}"]
    for name, value in vars(node).items():
        if name == "span":
            continue
        if isinstance(value, T.Type):
            out.append(f"{pad}  {name}={value}")
        elif isinstance(value, list):
            if value and hasattr(value[0], "__dataclass_fields__"):
                out.append(f"{pad}  {name}:")
                for v in value:
                    out.append(_pretty(v, indent + 2))
            else:
                out.append(f"{pad}  {name}={value!r}")
        elif hasattr(value, "__dataclass_fields__"):
            out.append(f"{pad}  {name}:")
            out.append(_pretty(value, indent + 2))
        else:
            out.append(f"{pad}  {name}={value!r}")
    return "\n".join(out)


def _fill_holes(module, targets, no_llm: bool, quiet: bool) -> None:
    holes = iter_holes(module)
    if not holes or no_llm:
        return
    from .llm import HoleFiller
    filler = HoleFiller()
    for tgt in targets:
        if tgt in ("js", "py", "python"):
            filler.fill_for_target(module, tgt)
    if not quiet:
        for r in filler.records:
            print(f"  hole {r.hole_id} -> {r.target}: filled via {r.source_via} "
                  f"({r.attempts} attempt(s), gates A/B/C passed)", file=sys.stderr)


def _run_self_check(source: str, module, no_llm: bool) -> int:
    _fill_holes(module, ("js", "py"), no_llm, quiet=True)
    report = self_check(source, module)
    label = {"pass": "PASS", "FAIL": "FAIL", "skipped": "SKIP", "ERROR": "ERR "}
    print("3-way differential self-check (CPython source vs IR interpreter vs targets)\n")
    for row in report["rows"]:
        status = label.get(row["status"], row["status"])
        print(f"  [{status}] {row['name']}")
        if row["status"] in ("FAIL", "ERROR"):
            print(f"         {row['output'].strip()[:400]}")
    print()
    print("RESULT:", "all consistent" if report["ok"] else "DIVERGENCE DETECTED")
    return 0 if report["ok"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="poly", description="Poly semantic transpiler")
    ap.add_argument("source", help="path to a Python-subset source file")
    ap.add_argument("-t", "--target", default="js", choices=["js", "py", "python", "c"],
                    help="target language (default: js)")
    ap.add_argument("-o", "--output", help="write result to a file instead of stdout")
    ap.add_argument("--no-llm", action="store_true",
                    help="disable the LLM layer; holes become marked stubs")
    ap.add_argument("--dump", choices=["tokens", "ast", "ir"], help="print a pipeline stage and exit")
    ap.add_argument("--self-check", action="store_true",
                    help="run the 3-way differential self-check and exit")
    args = ap.parse_args(argv)

    try:
        with open(args.source, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        print(f"cannot read {args.source}: {exc}", file=sys.stderr)
        return 2

    try:
        if args.dump == "tokens":
            for t in tokenize(source):
                print(t)
            return 0
        tokens, ast, module = _build(source)
        if args.dump == "ast":
            print(_pretty(ast))
            return 0
        if args.dump == "ir":
            print(_pretty(module))
            return 0
        if args.self_check:
            return _run_self_check(source, module, args.no_llm)

        _fill_holes(module, (args.target,), args.no_llm, quiet=False)
        code = generate(module, args.target)
    except PolyError as exc:
        print(exc.render(source), file=sys.stderr)
        return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(code)
    return 0
