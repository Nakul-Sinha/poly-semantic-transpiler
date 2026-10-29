"""Exact-match, bundled reference programs for an offline demonstration.

These are prepared examples, not a general-purpose translation engine. Any change
inside a source program falls through to the ordinary compiler/AI path.
"""
from functools import lru_cache
from importlib.resources import files
import json


def _normalize(source):
    return source.replace("\r\n", "\n").strip()


@lru_cache(maxsize=1)
def demo_catalog():
    return json.loads(files("poly").joinpath("demo_programs.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _index():
    index = {}
    for demo in demo_catalog():
        for lang, code in demo["code"].items():
            key = (lang, _normalize(code))
            if key in index:
                raise ValueError("Duplicate demo source")
            index[key] = demo
    return index


def prepared_translation(source, source_lang, target):
    demo = _index().get((source_lang, _normalize(source)))
    if demo is None or target not in demo["code"]:
        return None
    return {"code": demo["code"][target], "engine": "prepared-demo", "demo_id": demo["id"],
            "cached": True, "attempts": 0, "timings": {"translation_ms": 0, "validation_ms": 0},
            "validation": {"status": "not_run", "detail": "Bundled reference example. Use Check to execute it locally."}}
