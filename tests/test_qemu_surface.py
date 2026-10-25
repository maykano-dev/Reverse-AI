"""QEMU VM surface: command builder and honest refusal."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox import SandboxPolicy  # noqa: E402
from reverseai.sandbox.backends.qemu_backend import (  # noqa: E402
    QemuConfig, QemuVmBackend,
)
from reverseai.sandbox.base import SandboxUnavailable  # noqa: E402

QEMU = shutil.which("qemu-system-x86_64") is not None


@unittest.skipUnless(QEMU, "qemu-system-x86_64 unavailable")
class QemuSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kernel = Path(self.tmp.name) / "vmlinuz"
        self.rootfs = Path(self.tmp.name) / "rootfs.img"
        self.kernel.write_bytes(b"kernel")
        self.rootfs.write_bytes(b"rootfs")
        self.old = {k: os.environ.get(k) for k in
                    ("REVERSEAI_QEMU_KERNEL", "REVERSEAI_QEMU_ROOTFS")}
        os.environ["REVERSEAI_QEMU_KERNEL"] = str(self.kernel)
        os.environ["REVERSEAI_QEMU_ROOTFS"] = str(self.rootfs)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_config_and_preflight(self):
        cfg = QemuConfig.from_env()
        self.assertTrue(cfg.configured)
        self.assertTrue(QemuVmBackend.is_available())
        pre = QemuVmBackend.preflight()
        self.assertTrue(pre["available"])
        self.assertIn("guest runner", pre["note"])

    def test_command_builder(self):
        args = QemuVmBackend.build_args(["target"])
        self.assertIn("-nographic", args)
        self.assertIn("-snapshot", args)
        self.assertIn(str(self.kernel), args)
        self.assertEqual(args[-1], "target")

    def test_run_refuses_until_guest_runner_exists(self):
        with self.assertRaises(SandboxUnavailable) as ctx:
            QemuVmBackend().run(["true"], SandboxPolicy(allow_untrusted_execution=True))
        self.assertIn("guest runner", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
