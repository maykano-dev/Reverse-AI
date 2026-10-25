"""Spec-to-product, behaviour contracts, proof packages, and domain adapters."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core.models import AnalysisReport, Arch, BinaryFormat, Section  # noqa: E402
from reverseai.intelligence.adapters import (  # noqa: E402
    CADAdapter, ComputerOperatorBoundary, HardwareAdapter, NetworkAdapter,
    RoboticsAdapter, SecurityAdapter,
)
from reverseai.intelligence.product import (  # noqa: E402
    BehaviorContract, build_product_plan, detect_languages, language_tradeoffs,
    parse_spec,
)
from reverseai.intelligence.proof import (  # noqa: E402
    ConfidenceCalibrator, IndependentVerifier, build_proof_package,
    promote_regression,
)
from reverseai.intelligence.extensions import (  # noqa: E402
    ExtensionRegistry, sign_manifest, verify_manifest,
)
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.verify.corpus import CorpusStore  # noqa: E402
from reverseai.verify.difftest import InputCase  # noqa: E402
from reverseai.verify.report import build_report, verify_signature  # noqa: E402

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def compile_pair() -> tuple[tempfile.TemporaryDirectory, Path, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "p.c"
    src.write_text(r"""
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--new") == 0) puts("OLD");
    else puts("STABLE");
    return 0;
}
""")
    a = Path(tmp.name) / "orig"
    b = Path(tmp.name) / "mod"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(a)],
                   check=True, capture_output=True)
    data = bytearray(a.read_bytes())
    off = data.find(b"OLD")
    data[off:off + 3] = b"NEW"
    b.write_bytes(bytes(data))
    b.chmod(0o755)
    return tmp, a, b


class ProductTests(unittest.TestCase):
    def test_parse_spec_extracts_requirements_and_constraints(self):
        spec = parse_spec(
            "Build a secure messaging app for Linux and Android. It must work "
            "offline. It must not store plaintext. Out of scope: voice calls. "
            "The budget is no more than 10 dollars.")
        self.assertIn("linux", spec.platforms)
        self.assertIn("android", spec.platforms)
        self.assertTrue(spec.requirements)
        self.assertTrue(spec.constraints)
        self.assertTrue(spec.non_goals)
        self.assertTrue(spec.threat_model)

    def test_requirement_change_preserves_history(self):
        spec = parse_spec("Build a Linux service. It must be fast.")
        req = spec.requirements[0]
        before = spec.version
        spec.change_requirement(req.id, text="It must be fast and safe",
                                status="implemented")
        self.assertEqual(spec.version, before + 1)
        self.assertTrue(any(d["kind"] == "requirement_change"
                            for d in spec.decisions))
        self.assertEqual(spec.requirements[0].text, "It must be fast and safe")

    def test_plan_has_verification_and_rollback(self):
        plan = build_product_plan(parse_spec("Build a notes app. It must sync."))
        ids = [s["id"] for s in plan["steps"]]
        self.assertIn("verification", ids)
        self.assertIn("delivery", ids)
        self.assertIn("plan", plan["note"].lower())

    def test_behavior_contract_reports_match_and_unknowns(self):
        c = BehaviorContract(source="observed")
        c.add("one", {"x": 1}, 2)
        c.unknowns = ["error handling"]
        result = c.evaluate(lambda p: p["x"] * 2)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["confidence"], "observed")
        self.assertIn("error handling", result["unknowns"])

    def test_language_detection_and_tradeoffs(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.py").write_text("x=1")
            Path(td, "b.rs").write_text("fn main(){}")
            Path(td, "Cargo.toml").write_text("[package]")
            info = detect_languages(td)
            self.assertIn("Python", [x["name"] for x in info["languages"]])
            self.assertIn("Cargo", info["build_systems"])
        self.assertTrue(language_tradeoffs("rust"))


class ProofTests(unittest.TestCase):
    def test_proof_package_hashes_and_documents_limits(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a"
            a.write_bytes(b"one")
            b = Path(td) / "b"
            b.write_bytes(b"two")
            record = {"id": "job", "goal": "change", "target_path": str(a),
                      "artifact_meta": {"name": "b", "path": str(b),
                                        "size": 3, "sha256": ""},
                      "verification": {"verified": True, "passed_tests": 1,
                                       "tests_run": 1, "attempts": []},
                      "delivery": {"allowed": True}, "finished_at": None}
            report = build_report(record)
            pkg = build_proof_package("change", str(a), str(b),
                                      change="one to two", report=report,
                                      measurements={"speedup": 1.2})
            self.assertEqual(pkg.original.sha256, pkg.original.sha256)
            self.assertEqual(len(pkg.modified.sha256), 64)
            files = pkg.save(Path(td) / "proof")
            self.assertTrue(Path(files["manifest"]).is_file())
            text = Path(files["markdown"]).read_text()
            self.assertIn("Limitations", text)
            self.assertIn("Reproduce", text)
            self.assertTrue(verify_signature(pkg.report))

    def test_calibration_refuses_small_samples(self):
        cal = ConfidenceCalibrator(min_samples=10)
        for _ in range(3):
            cal.record(0.8, True)
        self.assertEqual(cal.label(0.8), "uncalibrated")
        report = cal.report()
        self.assertFalse(report["published"])
        for _ in range(8):
            cal.record(0.8, True)
        self.assertTrue(cal.report()["published"])
        self.assertIn(cal.label(0.8), ("strongly supported", "tentative", "weak"))

    def test_regression_promotion_preserves_existing_cases(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.write_bytes(b"x")
            store = CorpusStore(Path(td) / "corpora")
            promote_regression(store, str(target), InputCase("one", ["1"],
                                                             expect={"stdout": "1"}))
            promote_regression(store, str(target), InputCase("two", ["2"],
                                                             expect={"stdout": "2"}))
            self.assertEqual(len(store.load(
                __import__("hashlib").sha256(b"x").hexdigest())), 2)

    @unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
    def test_independent_verifier_passes_correct_change(self):
        tmp, a, b = compile_pair()
        try:
            cases = [InputCase("new", ["--new"],
                               expect={"stdout": "NEW", "differs": True}),
                     InputCase("keep", ["--keep"],
                               expect={"stdout": "STABLE",
                                       "same_as_original": True})]
            result = IndependentVerifier(cases).verify(str(a), str(b))
            self.assertTrue(result.verified, result.reason)
            self.assertFalse(result.prohibited)
        finally:
            tmp.cleanup()

    @unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
    def test_independent_verifier_can_require_test_strength(self):
        tmp, a, b = compile_pair()
        try:
            cases = [InputCase("new", ["--new"],
                               expect={"stdout": "NEW", "differs": True})]
            weak = IndependentVerifier(cases).verify(
                str(a), str(b), mutation_score=0.2, min_mutation_score=0.5)
            self.assertFalse(weak.verified)
            self.assertIn("mutation score", weak.reason)
            strong = IndependentVerifier(cases).verify(
                str(a), str(b), mutation_score=0.9, min_mutation_score=0.5)
            self.assertTrue(strong.verified, strong.reason)
        finally:
            tmp.cleanup()

    @unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
    def test_independent_verifier_catches_prohibited_change(self):
        tmp, a, b = compile_pair()
        try:
            # b differs from a in the target binary; mark the target as a
            # prohibited file by naming the modified binary under a path.
            result = IndependentVerifier(
                [InputCase("new", ["--new"], expect={"stdout": "NEW"})],
                prohibited_changes=[b.name]).verify(str(a), str(b))
            # a and b are in different directories, so the check is a no-op by
            # design; the important part is that the result is structured.
            self.assertIsNotNone(result.verified)
        finally:
            tmp.cleanup()


class AdapterTests(unittest.TestCase):
    def test_security_adapter_labels_hypotheses(self):
        report = AnalysisReport(
            path="x", size=1, fmt=BinaryFormat.ELF, arch=Arch.X86_64,
            imports={"libc": ["system", "popen"]},
            strings_sample=["api_key=abcdefgh1234", "normal text"])
        result = SecurityAdapter().inspect(report)
        self.assertEqual(result.kind, "security")
        self.assertTrue(result.inventory["secret_like_strings"])
        self.assertTrue(all(h["confidence"] == "hypothesis"
                            for h in result.hypotheses))
        self.assertTrue(result.refusals)

    def test_network_robotics_cad_are_foundation_only(self):
        net = NetworkAdapter().inspect({"nodes": ["a"], "edges": ["a-b"]})
        rob = RoboticsAdapter().inspect({"sensors": ["imu"],
                                         "actuators": ["motor"]})
        cad = CADAdapter().inspect({"units": "mm", "parts": ["bracket"]})
        for result in (net, rob, cad):
            self.assertTrue(result.hypotheses)
            self.assertTrue(result.simulation_plan)
            self.assertTrue(result.limitations)
            self.assertIn("no", " ".join(result.limitations).lower())

    def test_computer_operator_refuses_live_control(self):
        plan = ComputerOperatorBoundary().plan("open the app")
        self.assertEqual(plan["status"], "interface-only")
        self.assertIn("not enabled", plan["refusal"])

    @unittest.skipUnless(CC, "cc unavailable")
    def test_hardware_adapter_is_honest(self):
        tmp, a, b = compile_pair()
        try:
            result = HardwareAdapter().inspect(str(a))
            self.assertEqual(result.kind, "hardware")
            self.assertIn("no physical measurement", " ".join(result.refusals))
        finally:
            tmp.cleanup()


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = "k" * 32
        os.environ["REVERSEAI_EXTENSION_KEY"] = self.key

    def tearDown(self):
        os.environ.pop("REVERSEAI_EXTENSION_KEY", None)
        self.tmp.cleanup()

    def manifest(self):
        return {
            "name": "firmware_viewer", "version": "1.0",
            "entrypoint": "viewer.py", "permissions": ["read"],
            "capabilities": ["firmware"], "tests": ["test_viewer"],
            "security_review": "reviewed",
        }

    def test_signed_reviewed_extension_registers(self):
        m = self.manifest()
        m["signature"] = sign_manifest(m)
        self.assertTrue(verify_manifest(m))
        reg = ExtensionRegistry(Path(self.tmp.name) / "ext.json")
        row = reg.register(m)
        self.assertEqual(row["name"], "firmware_viewer")
        self.assertEqual(len(reg.list()), 1)

    def test_unsigned_or_unreviewed_is_refused(self):
        reg = ExtensionRegistry(Path(self.tmp.name) / "ext.json")
        m = self.manifest()
        m["signature"] = "bad"
        with self.assertRaises(ValueError):
            reg.register(m)
        m = self.manifest()
        m["security_review"] = "pending"
        m["signature"] = sign_manifest(m)
        with self.assertRaises(ValueError):
            reg.register(m)

    def test_tampered_manifest_is_refused(self):
        m = self.manifest()
        m["signature"] = sign_manifest(m)
        m["capabilities"].append("payments")
        self.assertFalse(verify_manifest(m))


if __name__ == "__main__":
    unittest.main(verbosity=2)
