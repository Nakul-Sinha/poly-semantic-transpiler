"""Local toolchain checks. Execution is only used by the explicit Check action.

This is a localhost developer tool, not a sandbox for untrusted programs.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .languages import LANGUAGES, language


def _environment():
    # Programs being checked do not need the server's authentication environment.
    return {k: v for k, v in os.environ.items()
            if not any(s in k.upper() for s in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CREDENTIAL"))}


def _run(cmd, cwd, stdin="", timeout=25):
    result = subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=timeout,
                            env=_environment())
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or f"Exit code {result.returncode}")[:4000])
    return result.stdout[:100000]


def check_code(code: str, lang: str, *, execute=False, stdin="") -> dict:
    lang = language(lang)
    tool = {"py": sys.executable, "js": "node", "c": "gcc", "cpp": "g++", "java": "javac",
            "cs": "dotnet", "go": "go", "rust": "rustc", "ruby": "ruby", "php": "php"}[lang]
    if not shutil.which(tool):
        return {"status": "unavailable", "detail": f"{tool} is not installed; code has not been checked."}
    try:
        with tempfile.TemporaryDirectory(prefix="poly_check_") as folder:
            root = Path(folder)
            file = root / ("Main" + LANGUAGES[lang]["extension"])
            if lang == "java":
                match = re.search(r"public\s+(?:final\s+)?class\s+(\w+)", code)
                file = root / ((match.group(1) if match else "Main") + ".java")
            file.write_text(code, encoding="utf-8")
            binary = str(root / ("program.exe" if os.name == "nt" else "program"))
            run = None
            if lang == "py":
                compile(code, "<translation>", "exec")
                run = [sys.executable, "-I", str(file)]
            elif lang == "js":
                _run([tool, "--check", str(file)], folder)
                run = [tool, str(file)]
            elif lang in ("c", "cpp"):
                flags = ["-std=c99"] if lang == "c" else ["-std=c++17"]
                if execute:
                    _run([tool, *flags, str(file), "-o", binary, "-lm"], folder)
                else:
                    _run([tool, *flags, "-fsyntax-only", str(file)], folder)
                run = [binary]
            elif lang == "java":
                _run([tool, "-encoding", "UTF-8", str(file)], folder)
                run = ["java", "-cp", folder, file.stem]
            elif lang == "rust":
                flags = [] if execute else ["--emit=metadata"]
                _run([tool, "--edition=2021", *flags, str(file), "-o", binary], folder)
                run = [binary]
            elif lang == "go":
                _run([tool, "build", "-o", binary, str(file)], folder)
                run = [binary]
            elif lang == "cs":
                versions = _run([tool, "--list-sdks"], folder)
                majors = re.findall(r"^(\d+)\.", versions, re.M)
                if not majors:
                    return {"status": "unavailable", "detail": "The .NET SDK is not installed."}
                (root / "Check.csproj").write_text(
                    '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
                    f'<TargetFramework>net{max(map(int, majors))}.0</TargetFramework>'
                    '</PropertyGroup></Project>', encoding="utf-8")
                _run([tool, "build", "Check.csproj", "-o", "out", "--nologo", "-v:q"], folder, timeout=45)
                run = [tool, str(root / "out" / "Check.dll")]
            elif lang == "ruby":
                _run([tool, "-c", str(file)], folder)
                run = [tool, str(file)]
            elif lang == "php":
                _run([tool, "-l", str(file)], folder)
                run = [tool, str(file)]
            if execute:
                output = _run(run, folder, stdin=stdin, timeout=8)
                return {"status": "passed", "detail": "Program executed successfully.", "output": output}
            return {"status": "passed", "detail": f"{LANGUAGES[lang]['name']} syntax/compiler check passed."}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "detail": "The compiler or program exceeded the time limit."}
    except (ValueError, OSError, SyntaxError) as exc:
        return {"status": "failed", "detail": str(exc)[:4000]}
