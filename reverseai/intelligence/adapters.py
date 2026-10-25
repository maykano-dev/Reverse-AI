"""Domain adapter contracts.

These adapters turn domain facts into the same world-model vocabulary and
explicitly refuse claims the platform cannot support. They are foundations for
hardware, robotics, CAD, network, security, and computer-operator work; they do
not pretend a Python process can inspect a circuit or drive a robot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core import analyze_file
from .world import WorldModel

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
)


@dataclass
class AdapterResult:
    kind: str
    inventory: dict[str, Any] = field(default_factory=dict)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    simulation_plan: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "inventory": self.inventory,
            "hypotheses": self.hypotheses,
            "simulation_plan": self.simulation_plan,
            "refusals": self.refusals, "limitations": self.limitations,
        }


class HardwareAdapter:
    def inspect(self, firmware_path: str) -> AdapterResult:
        report = analyze_file(firmware_path)
        return AdapterResult(
            "hardware",
            {"format": report.fmt.value, "arch": report.arch.value,
             "size": report.size, "entropy": report.entropy,
             "sections": len(report.sections),
             "strings": report.string_count},
            [{"claim": "the image contains a bootloader or update path",
              "confidence": "hypothesis",
              "test": "inspect partition tables and update strings"},
             {"claim": "a high-entropy region is compressed firmware",
              "confidence": "hypothesis",
              "test": "attempt unpacking only on a copy"}],
            ["unpack on a copy; compare partition layout before flashing",
             "test on a disposable device or emulator, never production hardware"],
            ["no physical measurement, PCB inspection, or safe-flash guarantee"],
            ["a firmware image is not a circuit diagram; no electrical claims"],
        )


class RoboticsAdapter:
    def inspect(self, config: dict[str, Any]) -> AdapterResult:
        sensors = list(config.get("sensors") or [])
        actuators = list(config.get("actuators") or [])
        return AdapterResult(
            "robotics",
            {"sensors": sensors, "actuators": actuators,
             "control_hz": config.get("control_hz"),
             "calibration": config.get("calibration")},
            [{"claim": "a calibration offset explains the targeting miss",
              "confidence": "hypothesis",
              "test": "vary one calibration factor at a time in simulation"},
             {"claim": "the control loop is too slow for the required rate",
              "confidence": "hypothesis",
              "test": "measure loop jitter and deadline misses"}],
            ["simulate sensor noise and actuator latency",
             "require a human safety observer before physical actuation"],
            ["no actuation, no physical safety certification"],
            ["simulation does not prove real-world safety"],
        )


class CADAdapter:
    def inspect(self, metadata: dict[str, Any]) -> AdapterResult:
        return AdapterResult(
            "cad",
            {"units": metadata.get("units"), "parts": metadata.get("parts", []),
             "constraints": metadata.get("constraints", [])},
            [{"claim": "a constraint conflict causes the invalid geometry",
              "confidence": "hypothesis",
              "test": "resolve constraints in a geometry kernel on a copy"}],
            ["validate geometry and manufacturing constraints in a real kernel",
             "keep the original model; never overwrite it"],
            ["no geometry kernel or physics engine is bundled"],
            ["a language model is not a CAD kernel"],
        )


class NetworkAdapter:
    def inspect(self, topology: dict[str, Any]) -> AdapterResult:
        return AdapterResult(
            "network",
            {"nodes": topology.get("nodes", []),
             "edges": topology.get("edges", []),
             "protocols": topology.get("protocols", [])},
            [{"claim": "a dependency or timeout causes the observed failure",
              "confidence": "hypothesis",
              "test": "reproduce in a network namespace or lab, one variable at a time"}],
            ["simulate loss/latency in an isolated lab",
             "require an approval before touching a live device"],
            ["no live configuration change without approval"],
            ["a topology diagram is not a live network"],
        )


class SecurityAdapter:
    def inspect(self, report) -> AdapterResult:
        strings = list(report.strings_sample or [])
        secrets = []
        for text in strings:
            for pat in _SECRET_PATTERNS:
                if pat.search(text):
                    secrets.append(text[:120])
                    break
        sharp = [s for syms in (report.imports or {}).values() for s in syms
                 if s in ("system", "popen", "exec", "dlopen", "ptrace",
                          "setuid", "chmod", "unlink")]
        return AdapterResult(
            "security",
            {"format": report.fmt.value, "imports": len(report.imports or {}),
             "secret_like_strings": secrets[:10],
             "sharp_imports": sharp[:20]},
            [{"claim": "a secret-like string is a live credential",
              "confidence": "hypothesis",
              "test": "verify with the owner in an authorized environment; never print it"},
             {"claim": "a sharp import is reachable from untrusted input",
              "confidence": "hypothesis",
              "test": "trace the call site and test a malformed input in the sandbox"}],
            ["build a threat model and a reproducible failing case",
             "patch on a copy; verify the failure no longer reproduces; run regressions"],
            ["no finding is a vulnerability until it is reproduced and scoped"],
            ["a passing patch test does not prove the class of vulnerability is eliminated"],
        )


class ComputerOperatorBoundary:
    def plan(self, objective: str, *, environment: str = "vm") -> dict[str, Any]:
        return {
            "objective": objective,
            "environment": environment,
            "requirements": [
                "a disposable VM or container with snapshots",
                "a visible, recorded input channel",
                "a human takeover and kill switch",
                "capability opt-in plus a live approval for consequential actions",
            ],
            "status": "interface-only",
            "refusal": ("live desktop input and remote control are not enabled in "
                        "this release; the boundary exists so they cannot be added "
                        "without a threat model"),
        }
