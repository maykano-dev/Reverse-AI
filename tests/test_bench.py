"""Benchmark harness tests — deterministic via per-task scripted mock providers.

Run: python3 -m unittest tests.test_bench -v
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import Agent, Permission  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402
from reverseai.bench import builtin_tasks  # noqa: E402
from reverseai.bench.runner import run_task  # noqa: E402

CC = shutil.which("cc") is not None

# Scripts that make each task's ground-truth checker pass.
SCRIPTS = {
    "identify_format": [call("analyze_binary", {}), say("It is an ELF x86_64 binary.")],
    "run_and_report": [
        call("run_in_sandbox", {"args": []}),
        say("It prints BENCH_MARKER_42."),
    ],
    "patch_and_verify": [
        call("analyze_binary", {}),
        # offset is resolved at runtime below via a callable step
    ],
}


class BenchHarnessTests(unittest.TestCase):
    @unittest.skipUnless(CC, "cc unavailable")
    def test_identify_task_passes_with_good_script(self):
        task = next(t for t in builtin_tasks() if t.id == "identify_format")
        factory = lambda perm: Agent(MockProvider(list(SCRIPTS["identify_format"])),
                                     max_permission=perm)
        res = run_task(task, factory)
        self.assertTrue(res.passed, res.notes)
        self.assertEqual(res.status, "completed")
        self.assertIn("analyze_binary", res.tools_used)

    @unittest.skipUnless(CC, "cc unavailable")
    def test_run_task_reports_marker(self):
        task = next(t for t in builtin_tasks() if t.id == "run_and_report")
        factory = lambda perm: Agent(MockProvider(list(SCRIPTS["run_and_report"])),
                                     max_permission=perm)
        res = run_task(task, factory)
        self.assertTrue(res.passed, res.notes)
        self.assertGreaterEqual(res.evidence.get("verified", 0), 1)

    @unittest.skipUnless(CC, "cc unavailable")
    def test_failing_script_fails_task(self):
        # An agent that just says something without investigating must FAIL.
        task = next(t for t in builtin_tasks() if t.id == "identify_format")
        factory = lambda perm: Agent(MockProvider([say("I think it's a PDF.")]),
                                     max_permission=perm)
        res = run_task(task, factory)
        self.assertFalse(res.passed)

    @unittest.skipUnless(CC, "cc unavailable")
    def test_patch_and_verify_task(self):
        task = next(t for t in builtin_tasks() if t.id == "patch_and_verify")

        def factory(perm):
            # Resolve the patch offset from the compiled target at setup time is
            # awkward here; instead drive a fixed-string search patch by reading
            # the file the task just built. We discover it via a callable step.
            def dynamic_patch(messages):
                # Find the user message with the target path and locate OLD.
                return call("apply_byte_patch", {"patches": _old_to_new(messages)})

            script = [
                call("analyze_binary", {}),
                dynamic_patch,
                call("verify_modification", {
                    "expect_stdout": "NEW", "expect_diff": True,
                    "max_attempts": 1, "repair": False}),
                say("Patched OLD->NEW and verified with a behavioral test."),
            ]
            return Agent(MockProvider(script), max_permission=perm)

        res = run_task(task, factory)
        self.assertTrue(res.passed, res.notes)
        self.assertIn("apply_byte_patch", res.tools_used)
        self.assertIn("verify_modification", res.tools_used)
        self.assertTrue(res.verified)
        self.assertEqual(res.split, "dev")
        self.assertFalse(res.false_verification)


def _old_to_new(messages):
    """Locate the target path from the conversation, find 'OLD', return a patch."""
    import re

    # messages are Message objects; find the one carrying the target path.
    path = None
    for m in messages:
        content = getattr(m, "content", None)
        if content and "path:" in content:
            mo = re.search(r"path:\s*(\S+)\)", content)
            if mo:
                path = mo.group(1)
    if not path:
        raise AssertionError("could not find target path in conversation")
    data = Path(path).read_bytes()
    off = data.find(b"OLD")
    return [{"offset": off, "hex": "4e4557", "expect_hex": "4f4c44"}]


if __name__ == "__main__":
    unittest.main(verbosity=2)
