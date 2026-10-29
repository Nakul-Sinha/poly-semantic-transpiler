"""Routing all 100 language pairs, repairs, local checks, and honest verification."""
import importlib
import sys

import pytest

from poly.languages import LANGUAGES, language
from poly.validation import check_code

translation = importlib.import_module("poly.translate")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "web"))
import server


@pytest.fixture(autouse=True)
def empty_translation_cache(monkeypatch):
    # These tests exercise the general AI path, separately from prepared demos.
    monkeypatch.setattr(translation, "prepared_translation", lambda *a: None)
    translation.clear_translation_cache()
    yield
    translation.clear_translation_cache()


@pytest.mark.parametrize("src", LANGUAGES)
@pytest.mark.parametrize("target", LANGUAGES)
def test_all_100_language_pairs_route_through_api(src, target, monkeypatch):
    calls = []

    def ask(prompt, **options):
        calls.append(prompt)
        assert LANGUAGES[src]["name"] in prompt
        assert LANGUAGES[target]["name"] in prompt
        assert LANGUAGES[src]["example"] in prompt
        return LANGUAGES[target]["example"], "test-provider"

    monkeypatch.setattr(translation, "_ask", ask)
    monkeypatch.setattr(translation, "check_code", lambda *a, **k: {"status": "passed", "detail": "test compiler"})
    result = server.api_transpile({"source": LANGUAGES[src]["example"], "source_lang": src,
                                   "target": target, "engine": "llm"})
    assert result["ok"], result
    assert result["code"] == LANGUAGES[target]["example"]
    assert len(calls) == (0 if src == target else 1)


def test_compiler_failure_repairs_with_diagnostic(monkeypatch):
    prompts = []
    candidates = iter(["```javascript\nconsole.log(;\n```", "console.log(42);"])
    def ask(prompt, **kwargs):
        prompts.append(prompt)
        return next(candidates), "test"
    monkeypatch.setattr(translation, "_ask", ask)
    checks = iter([{"status": "failed", "detail": "unexpected semicolon"}, {"status": "passed", "detail": "ok"}])
    monkeypatch.setattr(translation, "check_code", lambda *a, **k: next(checks))
    result = translation.translate("print(42)", "py", "js")
    assert result["attempts"] == 2
    assert "unexpected semicolon" in prompts[1]
    assert result["code"] == "console.log(42);\n"


def test_missing_compiler_does_not_claim_validation(monkeypatch):
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: ("puts 42", "test"))
    monkeypatch.setattr(translation, "check_code", lambda *a, **k: {"status": "unavailable", "detail": "ruby missing"})
    assert translation.translate("print(42)", "py", "ruby")["validation"]["status"] == "unavailable"


def test_no_service_gives_actionable_error(monkeypatch):
    monkeypatch.setattr(translation.shutil, "which", lambda *a: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Claude Code"):
        translation.translate("puts 42", "ruby", "py")


def test_failed_repairs_are_not_emitted(monkeypatch):
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: ("broken", "test"))
    monkeypatch.setattr(translation, "check_code", lambda *a, **k: {"status": "failed", "detail": "invalid syntax"})
    with pytest.raises(ValueError, match="after two attempts"):
        translation.translate("puts 42", "ruby", "py")


def test_invalid_requests():
    for payload in ({"source": " "}, {"source": "x", "source_lang": "brainfuck"},
                    {"source": "x", "target": "unknown"}, {"source": "x" * 60001}, []):
        assert not server.api_transpile(payload)["ok"]


def test_aliases():
    assert language("C++") == "cpp"
    assert language("C#") == "cs"
    assert language("python") == "py"


def test_python_syntax_and_execution():
    assert check_code("print(", "py")["status"] == "failed"
    assert check_code("print(6 * 7)", "py", execute=True)["output"] == "42\n"


def test_check_compares_supplied_translation_without_model():
    result = server.api_selfcheck({"source": "print(42)", "source_lang": "py", "target": "py",
                                  "translated_code": "print(41)"})
    assert result["ok"] and result["verified"] and not result["all_ok"]
    assert result["rows"][-1]["status"] == "FAIL"


def test_missing_runtime_is_not_a_success(monkeypatch):
    monkeypatch.setattr(server, "check_code", lambda *a, **k: {"status": "unavailable", "detail": "missing runtime"})
    result = server.api_selfcheck({"source": "puts 42", "source_lang": "ruby", "target": "py", "translated_code": "print(42)"})
    assert not result["verified"] and not result["all_ok"]


def test_native_python_still_works_without_ai(monkeypatch):
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: pytest.fail("unexpected model call"))
    result = server.api_transpile({"source": "print(42)\n", "source_lang": "py", "target": "js"})
    assert result["ok"] and result["engine"] == "compiler"


def test_cli_uses_language_from_extension(tmp_path, capsys, monkeypatch):
    from poly.cli import main
    file = tmp_path / "demo.rb"
    file.write_text("puts 42\n")
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: ("print(42)", "test"))
    assert main([str(file), "-t", "python"]) == 0
    assert "print(42)" in capsys.readouterr().out


@pytest.mark.parametrize("lang", LANGUAGES)
def test_language_examples_with_local_toolchain(lang):
    result = check_code(LANGUAGES[lang]["example"], lang, execute=True)
    if result["status"] == "unavailable":
        pytest.skip(result["detail"])
    assert result["status"] == "passed", result
    assert result["output"].strip() == "12"


def test_model_name_cannot_inject_shell_arguments():
    with pytest.raises(ValueError, match="Invalid model"):
        translation.translate("puts 42", "ruby", "py", model="sonnet&whoami")


def test_model_prose_outside_fenced_code_is_not_emitted():
    assert translation._clean("Here is the program:\n```python\nprint(42)\n```\nExplanation.") == "print(42)\n"
    assert translation._clean('{"code": "print(42)"}') == "print(42)\n"


def test_rich_python_identity_needs_no_translation_service(monkeypatch):
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: pytest.fail("unexpected model call"))
    source = "import math\na, b = 1, 2\nprint(math.sqrt(a + b))\n"
    result = server.api_transpile({"source": source, "source_lang": "py", "target": "py"})
    assert result["ok"] and result["code"] == source and result["engine"] == "identity"


def test_repeated_translation_skips_model_and_compiler(monkeypatch):
    calls = []
    def ask(*args, **kwargs):
        calls.append(1)
        return "print(42)", "test"
    monkeypatch.setattr(translation, "_ask", ask)
    first = translation.translate("puts 42", "ruby", "py")
    monkeypatch.setattr(translation, "check_code", lambda *a, **k: pytest.fail("cached code should not be recompiled"))
    second = translation.translate("puts 42", "ruby", "py")
    assert first["code"] == second["code"] and second["cached"] is True
    assert len(calls) == 1
    second["validation"]["status"] = "changed"
    assert translation.translate("puts 42", "ruby", "py")["validation"]["status"] == "passed"


def test_cache_expiry_and_model_changes_call_model_again(monkeypatch):
    calls = []
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: (calls.append(1) or "print(42)", "test"))
    translation.translate("puts 42", "ruby", "py", model="sonnet")
    translation.translate("puts 42", "ruby", "py", model="haiku")
    monkeypatch.setattr(translation, "_CACHE_TTL", 0)
    translation.translate("puts 42", "ruby", "py", model="sonnet")
    assert len(calls) == 3


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(translation, "_CACHE_LIMIT", 2)
    monkeypatch.setattr(translation, "_ask", lambda *a, **k: ("print(42)", "test"))
    for n in range(3):
        translation.translate(f"puts {n}", "ruby", "py")
    assert len(translation._CACHE) == 2
