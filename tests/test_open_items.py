"""Landlock/cgroup surfaces are honest about what they enforce."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox import cgroup, landlock  # noqa: E402


class LandlockTests(unittest.TestCase):
    def test_abi_and_plan_are_honest(self):
        abi = landlock.abi_version()
        self.assertGreaterEqual(abi, 0)
        plan = landlock.plan(["/usr", "/lib"], ["/work"])
        self.assertEqual(plan.abi, abi)
        self.assertIn("Plan only", plan.note)
        if abi:
            self.assertGreater(plan.handled_access, 0)
            self.assertEqual(plan.read_paths, ["/usr", "/lib"])
        else:
            self.assertEqual(plan.handled_access, 0)


class CgroupTests(unittest.TestCase):
    def test_detect_shape(self):
        info = cgroup.detect()
        for key in ("v2", "writable", "root", "controllers"):
            self.assertIn(key, info)

    def test_scope_creation_is_explicitly_optional(self):
        if not cgroup.detect()["v2"]:
            self.skipTest("cgroup v2 unavailable")
        try:
            scope = cgroup.create_scope("test", memory_max=64 * 1024 * 1024,
                                        pids_max=64)
        except cgroup.CgroupError as exc:
            self.assertIn("delegated", str(exc).lower())
            return
        try:
            self.assertTrue(scope.created)
        finally:
            scope.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
