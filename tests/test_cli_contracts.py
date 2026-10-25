"""CLI contracts: every command parses, help works, and safe commands run."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.cli import build_parser, main  # noqa: E402
from reverseai.hooks.runner import HookManifest, sign_manifest  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as exc:  # --help
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class CliContractTests(unittest.TestCase):
    def test_parser_has_every_public_command(self):
        parser = build_parser()
        sub = next(a for a in parser._actions if a.dest == "command")
        names = set(sub.choices)
        for name in ("analyze", "diff", "world", "discover", "repo", "cfg", "caps",
                     "surfaces", "capabilities", "mcp", "hooks",
                     "readiness", "sandbox", "verify", "corpus",
                     "report", "approvals", "agent", "bench", "serve"):
            self.assertIn(name, names)

    def test_every_command_help_exits_zero(self):
        parser = build_parser()
        sub = next(a for a in parser._actions if a.dest == "command")
        for name in sub.choices:
            code, out, err = _run([name, "--help"])
            self.assertEqual(code, 0, f"{name}: {err}")
            self.assertIn(name, out.lower() + err.lower())

    def test_agent_help_lists_product_modes(self):
        code, out, err = _run(["agent", "run", "--help"])
        self.assertEqual(code, 0)
        for mode in ("ask", "build", "modify", "optimize", "autonomous"):
            self.assertIn(mode, out)

    def test_unknown_command_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["not-a-command"])

    def test_capabilities_and_caps_are_json(self):
        code, out, _ = _run(["capabilities", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("remote_control", out)
        code, out, _ = _run(["caps", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("bubblewrap", out)

    def test_world_and_discover_on_a_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample"
            p.write_bytes(b"MZ" + b"\x00" * 100)
            code, out, err = _run(["world", str(p), "--json"])
            self.assertEqual(code, 0, err)
            self.assertIn('"nodes"', out)
            code, out, err = _run(["discover", str(p), "--json"])
            self.assertEqual(code, 0, err)
            self.assertIn("opportunities", out)
            self.assertIn("mission", out)

    def test_repo_maps_a_small_tree(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "main.py").write_text("import os\n")
            Path(td, "test_main.py").write_text("def test(): pass\n")
            code, out, err = _run(["repo", td, "--json"])
            self.assertEqual(code, 0, err)
            self.assertIn("languages", out)
            self.assertIn("Python", out)

    def test_readiness_reports_a_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample"
            p.write_bytes(b"not a real binary")
            code, out, err = _run(["readiness", str(p), "--json"])
            self.assertIn(code, (0, 1))
            self.assertIn("analysis_only", out + err)

    @unittest.skipUnless(CC, "cc unavailable")
    def test_cfg_and_analyze_run_on_a_real_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "x.c"
            src.write_text("int main(void){return 0;}\n")
            out_bin = Path(td) / "x"
            subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out_bin)],
                           check=True, capture_output=True)
            code, out, err = _run(["analyze", str(out_bin), "--json"])
            self.assertEqual(code, 0, err)
            self.assertIn('"fmt"', out)
            code, out, err = _run(["cfg", str(out_bin), "--json"])
            self.assertEqual(code, 0, err)
            self.assertIn("functions", out)
            code, out, err = _run(["xrefs", str(out_bin), "--json"])
            self.assertEqual(code, 0, err)
            self.assertIn("refs", out)

    def test_missing_file_is_a_clean_error(self):
        code, out, err = _run(["world", "/definitely/not/a/file"])
        self.assertEqual(code, 2)
        self.assertIn("error", err.lower())

    def test_mcp_and_hook_manifest_validation(self):
        with tempfile.TemporaryDirectory() as td:
            mcp = Path(td) / "mcp.json"
            mcp.write_text(json.dumps({"name": "files",
                                       "command": ["python", "server.py"],
                                       "allowed_tools": ["read"]}))
            code, out, err = _run(["mcp", "validate", str(mcp), "--json"])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["problems"], [])

            manifest = HookManifest(
                "echo", "tool.before", ["true"], timeout_seconds=5).to_dict()
            manifest["signature"] = sign_manifest(
                manifest, key="h" * 32)
            hook = Path(td) / "hook.json"
            hook.write_text(json.dumps(manifest))
            old = os.environ.get("REVERSEAI_HOOK_KEY")
            os.environ["REVERSEAI_HOOK_KEY"] = "h" * 32
            try:
                code, out, err = _run(["hooks", "validate", str(hook), "--json"])
            finally:
                if old is None:
                    os.environ.pop("REVERSEAI_HOOK_KEY", None)
                else:
                    os.environ["REVERSEAI_HOOK_KEY"] = old
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["signature_valid"])

    def test_bench_list_needs_no_provider(self):
        code, out, err = _run(["bench", "--list"])
        self.assertEqual(code, 0, err)
        self.assertIn("holdout", out)
        self.assertIn("patch_and_verify", out)

    def test_approvals_grant_and_list(self):
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("REVERSEAI_APPROVAL_KEY")
            os.environ["REVERSEAI_APPROVAL_KEY"] = "a" * 32
            try:
                code, out, err = _run([
                    "approvals", "grant", "--action", "payments.charge",
                    "--scope", "invoice:1", "--ttl", "60", "--dir", td,
                    "--json"])
                self.assertEqual(code, 0, err)
                token = json.loads(out)["token"]
                self.assertTrue(token)
                code, out, err = _run(["approvals", "list", "--dir", td,
                                       "--json"])
                self.assertEqual(code, 0, err)
                self.assertEqual(len(json.loads(out)), 1)
            finally:
                if old is None:
                    os.environ.pop("REVERSEAI_APPROVAL_KEY", None)
                else:
                    os.environ["REVERSEAI_APPROVAL_KEY"] = old

    def test_agent_mock_run(self):
        with tempfile.TemporaryDirectory() as td:
            old_home = os.environ.get("REVERSEAI_HOME")
            os.environ["REVERSEAI_HOME"] = td
            try:
                code, out, err = _run([
                    "agent", "run", "--provider", "mock",
                    "--goal", "Say hello.", "--permission", "read",
                    "--max-steps", "2"])
            finally:
                if old_home is None:
                    os.environ.pop("REVERSEAI_HOME", None)
                else:
                    os.environ["REVERSEAI_HOME"] = old_home
            self.assertEqual(code, 0, err)
            self.assertIn("ReverseAI job", out)

    @unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
    def test_corpus_verify_and_report_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "x.c"
            src.write_text(r"""
#include <stdio.h>
int main(void){puts("CLI_OK");return 0;}
""")
            binary = Path(td) / "x"
            subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(binary)],
                           check=True, capture_output=True)
            cases = Path(td) / "cases.json"
            cases.write_text(json.dumps({"cases": [
                {"name": "smoke", "args": [], "stdin": "",
                 "expect": {"stdout": "CLI_OK", "differs": False}}]}))
            corpus = Path(td) / "corpora"
            code, out, err = _run(["corpus", "capture", "--target", str(binary),
                                   "--cases", str(cases), "--dir", str(corpus),
                                   "--json"])
            self.assertEqual(code, 0, err)
            self.assertIn("target_sha256", out)
            code, out, err = _run(["corpus", "list", "--dir", str(corpus),
                                   "--json"])
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out))
            report = Path(td) / "report.json"
            code, out, err = _run(["verify", "--original", str(binary),
                                   "--modified", str(binary),
                                   "--cases", str(cases),
                                   "--report", str(report)])
            self.assertEqual(code, 0, err)
            code, out, err = _run(["report", "verify", str(report), "--json"])
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["valid"])

    def test_report_verify_rejects_bad_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{not json")
            code, out, err = _run(["report", "verify", str(p)])
            self.assertEqual(code, 2)
            self.assertIn("error", err.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
