"""Multi-turn conversation tests.

Run: python3 -m unittest tests.test_conversation -v
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import Agent, Permission  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402

CC = shutil.which("cc") is not None


def compile_marker(marker="HELLO"):
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "a.c"
    src.write_text(f'#include <stdio.h>\nint main(){{puts("{marker}");return 0;}}\n')
    out = Path(tmp.name) / "a"
    subprocess.run(["cc", "-no-pie", str(src), "-o", str(out)], check=True, capture_output=True)
    return tmp, out


@unittest.skipUnless(CC, "cc unavailable")
class ConversationTests(unittest.TestCase):
    def test_follow_up_shares_context(self):
        tmp, binp = compile_marker("CONVO_MARK")
        try:
            # Script spans two turns: turn1 analyzes, turn2 runs it.
            provider = MockProvider([
                call("analyze_binary", {}), say("It's an ELF binary."),
                call("run_in_sandbox", {"args": []}), say("It prints CONVO_MARK."),
            ])
            agent = Agent(provider, max_permission=Permission.EXECUTE)
            conv = agent.open(target_path=str(binp))

            job1 = conv.run_turn("Analyze this binary.")
            self.assertEqual(job1.status, "completed")
            msgs_after_1 = len(conv.messages)

            job2 = conv.run_turn("Now run it and tell me the output.")
            self.assertEqual(job2.status, "completed")

            # History carried over: turn 2 starts from where turn 1 ended.
            self.assertGreater(len(conv.messages), msgs_after_1)
            # Evidence accumulates across turns (observed from turn1 + verified turn2).
            summary = conv.evidence.summary()
            self.assertGreaterEqual(summary["observed"], 1)
            self.assertGreaterEqual(summary["verified"], 1)
            # Same workspace reused across turns.
            self.assertEqual(job1.workspace, job2.workspace)
            # The first user goal is still present in the transcript.
            contents = [m.content or "" for m in conv.messages]
            self.assertTrue(any("Analyze this binary" in c for c in contents))
        finally:
            tmp.cleanup()

    def test_single_turn_run_still_works(self):
        tmp, binp = compile_marker("ONESHOT")
        try:
            agent = Agent(MockProvider([call("analyze_binary", {}), say("done")]),
                          max_permission=Permission.READ)
            job = agent.run("Analyze.", target_path=str(binp))
            self.assertEqual(job.status, "completed")
        finally:
            tmp.cleanup()

    def test_refused_target_in_conversation(self):
        agent = Agent(MockProvider([say("x")]))
        conv = agent.open(target_path="/no/such/file")
        job = conv.run_turn("do it")
        self.assertEqual(job.status, "refused")


if __name__ == "__main__":
    unittest.main(verbosity=2)
