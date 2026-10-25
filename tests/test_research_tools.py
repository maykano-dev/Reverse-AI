"""Research tools import cleanly and refuse unsafe/empty requests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.builtins import WebReadTool, WebSearchTool  # noqa: E402
from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402


class ResearchToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = ToolContext(job_id="research", workspace=self.tmp.name,
                               evidence=EvidenceLog())

    def tearDown(self):
        self.tmp.cleanup()

    def test_private_url_is_refused_before_network(self):
        result = WebReadTool().run({"url": "http://127.0.0.1:1/secret"},
                                   self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("could not read", result.error or "")

    def test_empty_search_is_refused(self):
        result = WebSearchTool().run({"query": "   "}, self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("search failed", result.error or "")

    def test_tools_do_not_raise(self):
        for tool, args in ((WebReadTool(), {"url": "not-a-url"}),
                           (WebSearchTool(), {})):
            result = tool.run(args, self.ctx)
            self.assertFalse(result.ok, tool.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
