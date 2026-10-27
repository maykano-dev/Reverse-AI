"""Release metadata, test baseline, and feature claims must agree."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.release import (  # noqa: E402
    feature_issues, latest_changelog_version, package_version, readme_latest_version,
    release_truth,
)

ROOT = Path(__file__).resolve().parent.parent


class ReleaseIntegrityTests(unittest.TestCase):
    def test_repository_release_is_consistent(self):
        truth = release_truth(ROOT)
        self.assertEqual(truth.issues, [])
        self.assertEqual(truth.version, "0.9.0")
        self.assertEqual(truth.changelog_version, "0.9.0")
        self.assertEqual(truth.readme_version, "0.9.0")
        self.assertEqual(truth.audit_version, "0.9.0")
        self.assertEqual(truth.testing_version, "0.9.0")
        self.assertEqual(truth.tests, 558)
        self.assertGreaterEqual(truth.tools, 50)

    def test_every_feature_claim_has_source_and_test(self):
        self.assertEqual(feature_issues(ROOT), [])

    def test_parsers_handle_a_temp_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.2.3: x\n")
            (root / "README.md").write_text("## What's new in 1.2.3\n")
            (root / "pyproject.toml").write_text('version = "1.2.3"\n')
            (root / "reverseai").mkdir()
            (root / "reverseai/__init__.py").write_text('__version__ = "1.2.3"\n')
            self.assertEqual(latest_changelog_version(root), "1.2.3")
            self.assertEqual(readme_latest_version(root), "1.2.3")
            self.assertEqual(package_version(root), "1.2.3")

    def test_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "CHANGELOG.md").write_text("## 9.9.9: x\n")
            (root / "README.md").write_text("## What's new in 1.0.0\n")
            (root / "pyproject.toml").write_text('version = "1.0.0"\n')
            (root / "reverseai").mkdir()
            (root / "reverseai/__init__.py").write_text('__version__ = "1.0.0"\n')
            truth = release_truth(root)
            self.assertTrue(any("changelog" in i for i in truth.issues))


if __name__ == "__main__":
    unittest.main(verbosity=2)
