"""Release truth: versions, test baselines, and feature claims must agree.

This is a static consistency check, not a test runner. It catches the common
failure where the package, README, changelog, audit record, and test baseline
describe different releases.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SEMVER = r"\d+\.\d+\.\d+"


@dataclass
class ReleaseTruth:
    version: str = ""
    changelog_version: str = ""
    readme_version: str = ""
    audit_version: str = ""
    testing_version: str = ""
    roadmap_version: str = ""
    dangerous_version: str = ""
    audit_report_version: str = ""
    tests: int = 0
    tools: int = 0
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureClaim:
    name: str
    source: str
    test: str
    status: str = "implemented_tested"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FEATURE_CLAIMS = [
    FeatureClaim("differential fuzzing", "reverseai/verify/fuzz.py",
                 "tests/test_fuzz.py"),
    FeatureClaim("mission persistence", "reverseai/missions.py",
                 "tests/test_missions_quota.py"),
    FeatureClaim("PE resources/debug/TLS/rich header",
                 "reverseai/core/pe_extra.py", "tests/test_pe_extra.py"),
    FeatureClaim("Mach-O dependencies", "reverseai/core/macho.py",
                 "tests/test_macho_extra.py"),
    FeatureClaim("MCP client", "reverseai/mcp/client.py",
                 "tests/test_mcp_hooks.py"),
    FeatureClaim("hook runner", "reverseai/hooks/runner.py",
                 "tests/test_mcp_hooks.py"),
    FeatureClaim("desktop broker", "reverseai/remote/desktop.py",
                 "tests/test_remote_channels.py"),
    FeatureClaim("Telegram channel", "reverseai/remote/telegram.py",
                 "tests/test_remote_channels.py"),
    FeatureClaim("payment ledger", "reverseai/payments/ledger.py",
                 "tests/test_payments.py"),
    FeatureClaim("deployment controller", "reverseai/deploy/controller.py",
                 "tests/test_self_improvement.py"),
    FeatureClaim("per-token quotas", "reverseai/security/quota.py",
                 "tests/test_missions_quota.py"),
    FeatureClaim("verified-trace dataset", "reverseai/training/dataset.py",
                 "tests/test_self_improvement.py"),
    FeatureClaim("Landlock surface", "reverseai/sandbox/landlock.py",
                 "tests/test_open_items.py"),
    FeatureClaim("cgroup surface", "reverseai/sandbox/cgroup.py",
                 "tests/test_open_items.py"),
    FeatureClaim("QEMU surface", "reverseai/sandbox/backends/qemu_backend.py",
                 "tests/test_qemu_surface.py"),
    FeatureClaim("repository audit", "reverseai/audit.py",
                 "tests/test_audit.py"),
]


def _read(root: Path, name: str) -> str:
    try:
        return (root / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _match(pattern: str, text: str, default: str = "") -> str:
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else default


def latest_changelog_version(root: str | Path) -> str:
    text = _read(Path(root), "CHANGELOG.md")
    return _match(r"^##\s+(" + _SEMVER + r")", text)


def readme_latest_version(root: str | Path) -> str:
    text = _read(Path(root), "README.md")
    return _match(r"What's new in\s+(" + _SEMVER + r")", text)


def package_version(root: str | Path) -> str:
    root = Path(root)
    pyproject = _read(root, "pyproject.toml")
    init = _read(root, "reverseai/__init__.py")
    return _match(r'^version\s*=\s*"([^"]+)"', pyproject) or \
        _match(r'__version__\s*=\s*"([^"]+)"', init)


def test_baseline(root: str | Path) -> int:
    root = Path(root)
    text = _read(root, "docs/TESTING.md")
    return int(_match(r"Unit/contract tests:\s*(\d+)", text, "0"))


def release_truth(root: str | Path) -> ReleaseTruth:
    root = Path(root)
    version = package_version(root)
    truth = ReleaseTruth(
        version=version,
        changelog_version=latest_changelog_version(root),
        readme_version=readme_latest_version(root),
        audit_version=_match(r"^- Version:\s*(" + _SEMVER + r")",
                             _read(root, "docs/AUDIT_REMEDIATION.md")),
        testing_version=_match(r"^- Version:\s*(" + _SEMVER + r")",
                               _read(root, "docs/TESTING.md")),
        roadmap_version=_match(r"Updated with v(" + _SEMVER + r")",
                               _read(root, "docs/ROADMAP.md")),
        dangerous_version=_match(r"version (" + _SEMVER + r")\.",
                                 _read(root, "docs/DANGEROUS_AND_OPEN_ITEMS.md")),
        audit_report_version=_match(r"^#\s+ReverseAI\s+(" + _SEMVER + r")",
                                    _read(root, "docs/AUDIT_0_8_0.md")),
        tests=test_baseline(root),
    )
    try:
        from .agent.builtins import default_tools
        truth.tools = len(default_tools())
    except Exception:
        truth.tools = 0
    expected = version
    for name, value in (
            ("changelog", truth.changelog_version),
            ("README", truth.readme_version),
            ("audit baseline", truth.audit_version),
            ("testing baseline", truth.testing_version),
            ("roadmap baseline", truth.roadmap_version),
            ("dangerous-surface ledger", truth.dangerous_version)):
        if value != expected:
            truth.issues.append(
                f"{name} version is {value or '(missing)'}, expected {expected}")
    # Test count must agree across the release records.
    checks = {
        "CHANGELOG": _match(r"total\s+(\d+)", _read(root, "CHANGELOG.md")),
        "README badge": _match(r"tests-(\d+)%2B", _read(root, "README.md")),
        "audit baseline": _match(r"Tests:\s*(\d+)",
                                 _read(root, "docs/AUDIT_REMEDIATION.md")),
        "testing baseline": str(truth.tests or ""),
        "intelligence roadmap": _match(r"full suite is\s*(\d+)",
                                       _read(root, "docs/INTELLIGENCE_ROADMAP.md")),
        "dangerous-surface ledger": _match(r"(\d+)\s+tests passing",
                                           _read(root, "docs/DANGEROUS_AND_OPEN_ITEMS.md")),
        "roadmap": _match(r"\*\*Tests\*\*:\s*(\d+)",
                          _read(root, "docs/ROADMAP.md")),
    }
    values = {k: v for k, v in checks.items() if v}
    if values:
        baseline = values.get("CHANGELOG")
        for name, value in values.items():
            if baseline and value != baseline:
                truth.issues.append(
                    f"{name} test count is {value}, changelog says {baseline}")
        truth.tests = int(baseline) if baseline and baseline.isdigit() else truth.tests
    return truth


def feature_issues(root: str | Path) -> list[str]:
    root = Path(root)
    issues = []
    for claim in FEATURE_CLAIMS:
        if not (root / claim.source).is_file():
            issues.append(f"{claim.name}: missing source {claim.source}")
        if not (root / claim.test).is_file():
            issues.append(f"{claim.name}: missing test {claim.test}")
    return issues
