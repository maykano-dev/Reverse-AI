"""Clean-install check: build the wheel, install it, and run the entry point."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai import __version__  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PIP = shutil.which("pip") is not None or shutil.which("pip3") is not None


@unittest.skipUnless(PIP, "pip unavailable")
class PackagingInstallTests(unittest.TestCase):
    def test_wheel_builds_and_installs_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            wheel_dir = Path(td) / "wheel"
            site = Path(td) / "site"
            wheel_dir.mkdir()
            site.mkdir()
            build = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                 "--no-build-isolation", "-w", str(wheel_dir)],
                cwd=ROOT, capture_output=True, text=True, timeout=180)
            self.assertEqual(build.returncode, 0, build.stderr[-3000:])
            wheels = list(wheel_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            self.assertIn(__version__, wheels[0].name)
            with zipfile.ZipFile(wheels[0]) as zf:
                names = zf.namelist()
                for required in (
                        "reverseai/server/static/index.html",
                        "reverseai/server/static/app.js",
                        "reverseai/remote/telegram.py",
                        "reverseai/payments/ledger.py",
                        "reverseai/mcp/client.py",
                        "reverseai/hooks/runner.py"):
                    self.assertIn(required, names)
            install = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-deps",
                 "--target", str(site), str(wheels[0])],
                capture_output=True, text=True, timeout=180)
            self.assertEqual(install.returncode, 0, install.stderr[-3000:])
            env = {**os.environ, "PYTHONPATH": str(site)}
            check = subprocess.run(
                [sys.executable, "-c",
                 "import reverseai; print(reverseai.__version__); "
                 "print(reverseai.__file__)"],
                cwd=td, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(check.returncode, 0, check.stderr)
            lines = check.stdout.strip().splitlines()
            self.assertEqual(lines[0], __version__)
            self.assertIn(str(site), lines[1])
            help_run = subprocess.run(
                [sys.executable, "-m", "reverseai", "--help"],
                cwd=td, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(help_run.returncode, 0, help_run.stderr)
            self.assertIn("analyze", help_run.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
