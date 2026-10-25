"""seccomp denylist tests. Skipped when the host cannot apply the filter."""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.sandbox import seccomp  # noqa: E402

HOST_OK = seccomp.available()
BWRAP = shutil.which("bwrap") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


class FilterTests(unittest.TestCase):
    @unittest.skipUnless(HOST_OK, "seccomp only supported on x86_64 Linux")
    def test_program_shape(self):
        raw = seccomp.build_filter({"ptrace"})
        self.assertEqual(len(raw) % 8, 0)
        instructions = [struct.unpack("<HBBI", raw[i:i + 8])
                        for i in range(0, len(raw), 8)]
        # arch load, arch check, nr load, one jeq, allow, deny
        self.assertEqual(len(instructions), 6)
        self.assertEqual(instructions[0][3], 4)
        self.assertEqual(instructions[3][3], 101)  # ptrace
        self.assertEqual(instructions[-1][3] & 0xFFFF0000,
                         seccomp.SECCOMP_RET_ERRNO)

    def test_unknown_syscall_is_rejected(self):
        with self.assertRaises(ValueError):
            seccomp.build_filter({"not_a_syscall"})

    @unittest.skipUnless(HOST_OK, "seccomp only supported on x86_64 Linux")
    def test_install_filter_blocks_a_syscall(self):
        code = (
            "import ctypes, os\n"
            "from reverseai.sandbox.seccomp import install_filter\n"
            "install_filter({'getpid'})\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "r = libc.getpid()\n"
            "print(r, ctypes.get_errno())\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, cwd=str(Path(__file__).resolve().parent.parent))
        self.assertEqual(r.returncode, 0, r.stderr)
        value, _errno = r.stdout.split()
        self.assertEqual(int(value), -1)  # EPERM from seccomp


@unittest.skipUnless(HOST_OK and BWRAP and SANDBOX, "bwrap seccomp unavailable")
class BubblewrapSeccompTests(unittest.TestCase):
    def _run(self, seccomp_on: bool):
        py = sys.executable
        script = (
            "import ctypes, os\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "r = libc.ptrace(0, 0, 0, 0)\n"
            "print(r, ctypes.get_errno())\n")
        with tempfile.TemporaryDirectory() as td:
            p = SandboxPolicy(allow_untrusted_execution=True, timeout_seconds=5,
                              seccomp=seccomp_on, ro_binds=[py])
            sb = create_sandbox(p)
            res = sb.run([py, "-c", script], p, cwd=td)
        return res

    def test_ptrace_is_blocked_when_enabled(self):
        res = self._run(True)
        self.assertEqual(res.exit_code, 0, res.stderr_text())
        value, errno = res.stdout_text().split()
        self.assertEqual(int(value), -1)
        self.assertEqual(int(errno), 1)
        self.assertTrue(res.isolation.seccomp)

    def test_filter_can_be_disabled_and_is_reported(self):
        res = self._run(False)
        self.assertEqual(res.exit_code, 0, res.stderr_text())
        self.assertFalse(res.isolation.seccomp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
