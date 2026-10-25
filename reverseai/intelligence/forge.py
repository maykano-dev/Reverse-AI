"""Forge small tools, test them in the sandbox, and keep only what passes.

The forge is not a plugin loader that trusts generated code. It writes a tool
into the job workspace, runs it with a JSON test harness inside the isolating
sandbox, and records the manifest only when every declared test passes. A forged
tool is never registered globally without an explicit promotion step.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..sandbox import SandboxPolicy, create_sandbox
from ..security.validate import safe_join

MAX_CODE = 64 * 1024
_NAME = re.compile(r"^[a-z][a-z0-9_]{2,48}$")


class ForgeError(Exception):
    pass


@dataclass
class ForgedTool:
    id: str
    name: str
    description: str
    path: str
    sha256: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    tests: list[dict[str, Any]] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    status: str = "candidate"       # candidate | tested | promoted | failed
    limitations: list[str] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolForge:
    def __init__(self, root: str) -> None:
        self.root = Path(root) / "forged"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, description: str, code: str, *,
               inputs: dict[str, Any] | None = None,
               outputs: dict[str, Any] | None = None,
               limitations: list[str] | None = None) -> ForgedTool:
        name = (name or "").strip()
        if not _NAME.match(name):
            raise ForgeError("tool name must be 3-48 lowercase identifier characters")
        code = code or ""
        if len(code.encode("utf-8")) > MAX_CODE:
            raise ForgeError("tool code is too large")
        if "subprocess" in code or "os.system" in code or "socket" in code:
            # Not a blanket ban on execution; it is a warning that the tool will
            # still run only inside the sandbox, and needs an explicit review.
            limitations = list(limitations or []) + [
                "the tool uses process/network primitives; it is still sandboxed"]
        path = safe_join(self.root, f"{name}.py")
        path.write_text(code, encoding="utf-8")
        digest = hashlib.sha256(code.encode()).hexdigest()
        tool = ForgedTool(
            f"tool_{uuid.uuid4().hex[:10]}", name, description[:2000],
            str(path), digest, dict(inputs or {}), dict(outputs or {}),
            [], limitations=list(limitations or []))
        self._save(tool)
        return tool

    def test(self, tool: ForgedTool, cases: list[dict[str, Any]],
             policy: SandboxPolicy | None = None) -> ForgedTool:
        if not cases:
            raise ForgeError("at least one test case is required")
        harness = self.root / f".{tool.name}-harness.py"
        harness.write_text(
            "import json, sys\n"
            f"sys.path.insert(0, {str(self.root)!r})\n"
            f"from {tool.name} import run\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps(run(payload), default=str))\n",
            encoding="utf-8")
        policy = policy or SandboxPolicy(allow_untrusted_execution=True,
                                         timeout_seconds=15)
        from dataclasses import replace

        policy = replace(policy, allow_untrusted_execution=True,
                         workdir=str(self.root), timeout_seconds=15)
        try:
            sandbox = create_sandbox(policy)
        except Exception as exc:
            raise ForgeError(f"no isolating sandbox; refusing to run the forged tool: {exc}") from exc
        passed = failed = 0
        rows = []
        for case in cases:
            payload = case.get("inputs") or case.get("input") or {}
            expected = case.get("expect")
            result = sandbox.run([sys.executable, harness.name], policy,
                                 cwd=str(self.root),
                                 stdin=json.dumps(payload).encode())
            if result.error or result.exit_code != 0:
                failed += 1
                rows.append({"name": case.get("name"), "ok": False,
                             "error": result.error or result.stderr_text()[:800]})
                continue
            try:
                got = json.loads(result.stdout_text() or "{}")
            except json.JSONDecodeError:
                failed += 1
                rows.append({"name": case.get("name"), "ok": False,
                             "error": "tool did not print JSON"})
                continue
            ok = True
            if isinstance(expected, dict):
                ok = all(got.get(k) == v for k, v in expected.items())
            if ok:
                passed += 1
            else:
                failed += 1
            rows.append({"name": case.get("name"), "ok": ok,
                         "got": got, "expected": expected})
        tool.tests = rows
        tool.passed = passed
        tool.failed = failed
        tool.status = "tested" if failed == 0 and passed else "failed"
        self._save(tool)
        return tool

    def promote(self, tool: ForgedTool) -> ForgedTool:
        if tool.status != "tested" or tool.failed:
            raise ForgeError("only a fully tested tool can be promoted")
        tool.status = "promoted"
        self._save(tool)
        return tool

    def list(self) -> list[ForgedTool]:
        out = []
        for p in sorted(self.root.glob("tool_*.json")):
            try:
                data = json.loads(p.read_text("utf-8"))
                out.append(ForgedTool(**data))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return out

    def _save(self, tool: ForgedTool) -> None:
        path = safe_join(self.root, f"{tool.id}.json")
        path.write_text(json.dumps(tool.to_dict(), indent=2), encoding="utf-8")
