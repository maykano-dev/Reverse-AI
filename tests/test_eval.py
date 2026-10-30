"""The capability eval set must pass (it runs on every change)."""

import unittest

from reverseai.eval.cases import CASES
from reverseai.eval.harness import run_cases, summarize


class EvalSetTests(unittest.TestCase):
    def test_all_cases_pass(self):
        results = run_cases(CASES)
        failed = [f"{r.category}/{r.name}: {r.detail.splitlines()[0] if r.detail else ''}"
                  for r in results if not r.ok]
        self.assertTrue(summarize(results)["ok"], "eval failures:\n" + "\n".join(failed))
        self.assertGreaterEqual(len(results), 12)


if __name__ == "__main__":
    unittest.main()
