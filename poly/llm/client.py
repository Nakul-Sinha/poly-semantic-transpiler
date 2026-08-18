"""HoleFiller — resolves each hole to a validated target fragment.

Resolution order per hole:  golden cache  ->  offline mock  ->  live Claude API.
Whatever proposes the fragment, it is accepted only after passing gates A, B and C.
On a gate failure the precise reason is fed back and the proposal is retried up to
MAX_ATTEMPTS; on exhaustion a clean CompileError is raised (never unvalidated code).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from ..codegen.base import iter_holes
from ..errors import CompileError
from . import gates, mock

MAX_ATTEMPTS = 4
HOLE_TARGETS = {"js", "py", "python"}   # C target does not support holes in v1
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
_DEFAULT_MODEL = os.environ.get("POLY_LLM_MODEL", "claude-sonnet-5")


@dataclass
class FillRecord:
    hole_id: str
    target: str
    source_via: str          # 'cache' | 'mock' | 'live'
    attempts: int
    gate_failures: list = field(default_factory=list)


class HoleFiller:
    def __init__(self, mode: str | None = None, cache_dir: str | None = None,
                 model: str = _DEFAULT_MODEL):
        self.mode = self._resolve_mode(mode)
        self.cache_dir = cache_dir or _CACHE_DIR
        self.model = model
        self.records: list[FillRecord] = []
        os.makedirs(self.cache_dir, exist_ok=True)

    @staticmethod
    def _resolve_mode(requested: str | None) -> str:
        choice = requested or os.environ.get("POLY_LLM_MODE")
        if choice in ("mock", "live"):
            return choice
        return "live" if os.environ.get("ANTHROPIC_API_KEY") else "mock"

    # ---- public API -------------------------------------------------------
    def fill_for_target(self, module, target: str) -> list[FillRecord]:
        """Fill every hole in `module` for `target` (validated). Returns fill records."""
        if target not in HOLE_TARGETS:
            raise CompileError(f"holes are not supported for target {target!r} in v1")
        for hole in iter_holes(module):
            hole.filled[target] = self.fill(hole, target)
        return self.records

    def fill(self, hole, target: str) -> str:
        contract = hole.contract
        key = self._hash(contract, target)
        cached = self._cache_get(key)
        if cached is not None:
            self.records.append(FillRecord(hole.hole_id, target, "cache", 0))
            return cached

        failures: list[str] = []
        feedback: str | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            body = self._propose(contract, target, feedback)
            ok, reason = self._run_gates(contract, body, target)
            if ok:
                self._cache_put(key, contract, target, body)
                self.records.append(FillRecord(hole.hole_id, target, self.mode, attempt, failures))
                return body
            failures.append(f"attempt {attempt}: {reason}")
            feedback = reason
        raise CompileError(
            f"could not fill {hole.hole_id} ({contract.kind}) for {target} after "
            f"{MAX_ATTEMPTS} attempts; last failure: {failures[-1] if failures else '?'}"
        )

    # ---- gates ------------------------------------------------------------
    @staticmethod
    def _run_gates(contract, body: str, target: str) -> tuple[bool, str | None]:
        for name, gate in gates.ALL_GATES:
            ok, reason = gate(contract, body, target)
            if not ok:
                return False, f"gate {name} failed: {reason}"
        return True, None

    # ---- proposal sources -------------------------------------------------
    def _propose(self, contract, target: str, feedback: str | None) -> str:
        if self.mode == "live":
            return self._propose_live(contract, target, feedback)
        return mock.propose(contract, target)

    def _propose_live(self, contract, target: str, feedback: str | None) -> str:
        try:
            import anthropic
        except ImportError as exc:
            raise CompileError("live LLM mode needs the 'anthropic' package "
                               "(pip install poly-transpiler[llm])") from exc
        client = anthropic.Anthropic()
        prompt = self._prompt(contract, target, feedback)
        msg = client.messages.create(
            model=self.model, max_tokens=600, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._strip_fences("".join(b.text for b in msg.content if b.type == "text"))

    @staticmethod
    def _prompt(contract, target: str, feedback: str | None) -> str:
        lang = {"js": "JavaScript", "py": "Python", "python": "Python"}[target]
        params = ", ".join(contract.param_names)
        types = ", ".join(f"{v.name}: {v.type}" for v in contract.free_vars)
        p = (
            f"You are translating ONE pure Python expression into {lang}.\n"
            f"Write ONLY the BODY (statements, ending in a return) of the function:\n"
            f"    {contract.fn_name}({params})\n"
            f"It must be pure: no imports, no I/O, no global state. Use only the parameters.\n"
            f"Parameter types: {types}\n"
            f"Required return type: {contract.result_type}\n"
            f"Python source to translate:\n    {contract.source}\n"
        )
        if feedback:
            p += f"\nYour previous attempt was rejected: {feedback}\nFix it.\n"
        return p + "\nReturn only the function body, no explanation, no markdown fences."

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        return text.strip()

    # ---- cache ------------------------------------------------------------
    @staticmethod
    def _hash(contract, target: str) -> str:
        payload = json.dumps({
            "kind": contract.kind,
            "source": contract.source,
            "free_vars": [(v.name, str(v.type)) for v in contract.free_vars],
            "result_type": str(contract.result_type),
            "fn_name": contract.fn_name,
            "target": target,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def _cache_get(self, key: str) -> str | None:
        path = self._cache_path(key)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)["body"]
        return None

    def _cache_put(self, key: str, contract, target: str, body: str) -> None:
        with open(self._cache_path(key), "w") as f:
            json.dump({"target": target, "kind": contract.kind,
                       "fn_name": contract.fn_name, "source": contract.source,
                       "body": body}, f, indent=2)
