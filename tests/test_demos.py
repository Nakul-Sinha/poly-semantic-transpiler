"""Prepared programs must stay exact, offline, and independent of the LLM cache."""
import importlib
from pathlib import Path
import sys

import pytest

from poly.demos import demo_catalog, prepared_translation
from poly.languages import LANGUAGES
from poly.validation import check_code

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
import server
translation = importlib.import_module("poly.translate")


@pytest.mark.parametrize("demo_index", range(10))
@pytest.mark.parametrize("source_lang", LANGUAGES)
@pytest.mark.parametrize("target", LANGUAGES)
def test_all_1000_demo_routes_are_offline(demo_index, source_lang, target, monkeypatch):
    demo = demo_catalog()[demo_index]
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: pytest.fail("Demo made a model call"))
    monkeypatch.setattr(server, "check_code", lambda *a, **k: pytest.fail("Demo compiled on Run"))
    translation.clear_translation_cache()
    result = server.api_transpile({"source": demo["code"][source_lang], "source_lang": source_lang, "target": target})
    assert result["ok"] and result["engine"] == "prepared-demo"
    assert result["code"] == demo["code"][target]
    assert result["demo_id"] == demo["id"]
    assert result["validation"]["status"] == "not_run"


@pytest.mark.parametrize("demo_index", range(10))
@pytest.mark.parametrize("lang", LANGUAGES)
def test_prepared_program_prints_expected_output(demo_index, lang):
    demo = demo_catalog()[demo_index]
    result = check_code(demo["code"][lang], lang, execute=True)
    if result["status"] == "unavailable":
        pytest.skip(result["detail"])
    assert result["status"] == "passed", result
    assert result["output"].strip() == demo["expected"].strip()


def test_edits_are_not_replaced_with_a_prepared_answer():
    factorial = next(d for d in demo_catalog() if d["id"] == "factorial")
    changed = factorial["code"]["py"].replace("factorial(5)", "factorial(6)")
    assert changed != factorial["code"]["py"]
    assert prepared_translation(changed, "py", "js") is None
    windows = "\n" + factorial["code"]["py"].replace("\n", "\r\n") + "\n"
    assert prepared_translation(windows, "py", "js")["demo_id"] == "factorial"


def test_catalog_has_all_ten_languages_for_each_program():
    catalog = demo_catalog()
    assert len(catalog) == len({d["id"] for d in catalog}) == 10
    assert all(set(d["code"]) == set(LANGUAGES) for d in catalog)
