"""Mutation testing: can the declared corpus detect a broken candidate?

A passing test suite is only meaningful if it can fail. This module creates small,
deterministic mutations of the *modified* artifact, runs the same behavioral cases
against the original, and reports how many mutations the corpus kills.

Everything runs through the sandbox. Mutants are written to a temporary directory;
the original and the delivered candidate are never modified.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..modify import BytePatch, PatchError, apply_byte_patches
from ..sandbox import SandboxPolicy
from .difftest import InputCase, run_differential

MAX_MUTATIONS = 12


class MutationError(Exception):
    pass


@dataclass
class Mutation:
    name: str
    offset: int
    original: str          # hex bytes
    replacement: str       # hex bytes, same length
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MutationReport:
    mutation_score: float
    killed: int
    survived: int
    total: int
    killed_by: dict[str, list[str]] = field(default_factory=dict)
    survived_mutations: list[dict[str, Any]] = field(default_factory=list)
    weak_cases: list[str] = field(default_factory=list)
    confidence: str = "unknown"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_score": round(self.mutation_score, 3),
            "killed": self.killed,
            "survived": self.survived,
            "total": self.total,
            "killed_by": self.killed_by,
            "survived_mutations": self.survived_mutations,
            "weak_cases": self.weak_cases,
            "confidence": self.confidence,
            "note": self.note,
        }


def _mutate_bytes(data: bytes, mutation: Mutation) -> bytes:
    try:
        original = bytes.fromhex(mutation.original)
        replacement = bytes.fromhex(mutation.replacement)
    except ValueError as exc:
        raise MutationError(f"bad mutation hex: {exc}") from exc
    if len(original) != len(replacement):
        raise MutationError("mutation replacement must have the same length")
    if mutation.offset < 0 or mutation.offset + len(original) > len(data):
        raise MutationError("mutation is out of bounds")
    if data[mutation.offset:mutation.offset + len(original)] != original:
        raise MutationError("mutation does not match the candidate bytes")
    out = bytearray(data)
    out[mutation.offset:mutation.offset + len(original)] = replacement
    return bytes(out)


def _case_names(report) -> list[str]:
    return [c.name for c in report.cases]


def assess_mutations(
    original_path: str,
    modified_path: str,
    cases: list[InputCase],
    mutations: list[Mutation],
    *,
    policy: SandboxPolicy | None = None,
    timeout_seconds: float = 10.0,
) -> MutationReport:
    if not cases:
        raise MutationError("mutation testing needs at least one behavioral case")
    if not mutations:
        raise MutationError("no mutations supplied")
    mutations = mutations[:MAX_MUTATIONS]
    baseline = run_differential(original_path, modified_path, cases,
                                policy=policy,
                                timeout_seconds=timeout_seconds)
    if not baseline.ran:
        raise MutationError(f"baseline verification could not run: {baseline.error}")
    data = Path(modified_path).read_bytes()
    tmp = tempfile.mkdtemp(prefix="rvai-mutants-")
    killed = survived = 0
    killed_by: dict[str, list[str]] = {c.name: [] for c in cases}
    survivors: list[dict[str, Any]] = []
    try:
        for mutation in mutations:
            try:
                mutant = _mutate_bytes(data, mutation)
            except MutationError as exc:
                raise MutationError(
                    f"invalid mutation {mutation.name!r}: {exc}") from exc
            out = Path(tmp) / f"{mutation.name}.bin"
            out.write_bytes(mutant)
            # Preserve the executable bit so the sandbox can run it.
            try:
                shutil.copymode(modified_path, out)
            except OSError:
                pass
            report = run_differential(original_path, str(out), cases,
                                      policy=policy,
                                      timeout_seconds=timeout_seconds)
            if not report.ran:
                survivors.append({
                    "mutation": mutation.to_dict(),
                    "reason": f"could not run: {report.error}",
                })
                survived += 1
                continue
            # A case kills this mutant when it observes a difference from the
            # original. This is exactly the evidence the corpus is supposed to
            # provide.
            killers = [c.name for c in report.cases if not c.matched]
            if killers:
                killed += 1
                for name in killers:
                    killed_by[name].append(mutation.name)
            else:
                survived += 1
                survivors.append({"mutation": mutation.to_dict(),
                                  "reason": "all cases matched the original"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = killed + survived
    score = (killed / total) if total else 0.0
    weak = [name for name, names in killed_by.items() if not names]
    if total == 0:
        confidence = "unknown"
    elif total >= 3:
        confidence = "observed"
    else:
        confidence = "tentative"
    note = (
        f"{killed}/{total} mutants were detected by the corpus. "
        "Mutation score is a test-strength signal, not a proof of correctness.")
    return MutationReport(score, killed, survived, total, killed_by,
                          survivors, weak, confidence, note)


def generate_string_mutations(original_path: str, modified_path: str,
                              strings: list[str],
                              max_mutations: int = 6) -> list[Mutation]:
    """Create deterministic one-byte string mutations in the modified artifact."""
    data = Path(modified_path).read_bytes()
    out: list[Mutation] = []
    for text in strings:
        if len(out) >= max_mutations:
            break
        raw = str(text).encode("utf-8")
        if len(raw) < 3:
            continue
        off = data.find(raw)
        if off < 0:
            continue
        # Change the final printable byte to another printable byte.
        old = raw[-1]
        new = b"X" if old != ord("X") else b"Y"
        out.append(Mutation(
            f"string-{len(out) + 1}", off + len(raw) - 1,
            bytes([old]).hex(), new.hex(),
            f"change {text[:40]!r}"));
    return out
