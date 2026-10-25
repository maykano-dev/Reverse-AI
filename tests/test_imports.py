"""Every package module imports without an optional backend or a key."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reverseai  # noqa: E402


class ImportTests(unittest.TestCase):
    def test_every_module_imports(self):
        problems = []
        modules = [m for m in pkgutil.walk_packages(
            reverseai.__path__, reverseai.__name__ + ".")
            if not m.name.endswith(".__main__")]
        self.assertGreater(len(modules), 50)
        for m in modules:
            try:
                importlib.import_module(m.name)
            except Exception as exc:  # noqa: BLE001 - the report is the test
                problems.append(f"{m.name}: {type(exc).__name__}: {exc}")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
