"""Interactive surface validation, tool creation, persistence, and HTTP events."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.job import Job  # noqa: E402
from reverseai.agent.surface_tools import CreateSurfaceTool  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.server.app import ReverseAIServer  # noqa: E402
from reverseai.surface import (  # noqa: E402
    SurfaceError, SurfaceEventStore, event_from_body, validate_surface,
)
from tests.test_server import _get, _post  # noqa: E402


def question_spec() -> dict:
    return {
        "kind": "question",
        "title": "Which change should I make?",
        "description": "The evidence supports more than one path.",
        "blocks": [{
            "kind": "choice",
            "id": "strategy",
            "label": "Choose a strategy",
            "options": [
                {"value": "patch", "label": "Patch the binary",
                 "description": "Smallest change", "recommended": True},
                {"value": "rebuild", "label": "Rebuild from source",
                 "description": "Larger change", "risk": "high"},
            ],
            "allow_other": True,
        }],
        "actions": [{"id": "continue", "label": "Continue"}],
    }


class SurfaceModelTests(unittest.TestCase):
    def test_question_validates_and_gets_an_id(self):
        s = validate_surface(question_spec())
        self.assertTrue(s["id"].startswith("sf_"))
        self.assertEqual(s["kind"], "question")
        self.assertEqual(s["blocks"][0]["options"][1]["risk"], "high")
        self.assertTrue(s["blocks"][0]["allow_other"])

    def test_invalid_block_is_refused(self):
        spec = question_spec()
        spec["blocks"] = [{"kind": "not-a-block"}]
        with self.assertRaises(SurfaceError):
            validate_surface(spec)

    def test_custom_html_is_bounded_and_marked_as_custom(self):
        spec = {
            "title": "Custom view",
            "blocks": [{"kind": "custom", "html": "<b>hi</b>", "height": 300}],
        }
        s = validate_surface(spec)
        self.assertEqual(s["blocks"][0]["kind"], "custom")
        self.assertIn("hi", s["blocks"][0]["html"])

    def test_event_requires_an_known_action(self):
        s = validate_surface(question_spec())
        with self.assertRaises(SurfaceError):
            event_from_body("job_x", s, {"action_id": "nope"})
        ev = event_from_body("job_x", s, {"action_id": "continue",
                                          "value": {"strategy": "patch"}})
        self.assertEqual(ev.value["strategy"], "patch")

    def test_event_store_is_job_scoped(self):
        with tempfile.TemporaryDirectory() as td:
            store = SurfaceEventStore(td)
            s = validate_surface(question_spec())
            ev = event_from_body("job_abc", s, {"action_id": "continue",
                                                "other_text": "custom"})
            store.append("job_abc", s["id"], ev)
            self.assertEqual(len(store.list("job_abc", s["id"])), 1)
            with self.assertRaises(SurfaceError):
                store.list("../../etc", s["id"])


class SurfaceToolTests(unittest.TestCase):
    def test_tool_stores_and_emits_surface(self):
        with tempfile.TemporaryDirectory() as td:
            events = []
            ctx = ToolContext(job_id="job_tool", workspace=td,
                              evidence=EvidenceLog(), goal="ask",
                              extra={"emit": events.append})
            res = CreateSurfaceTool().run({"surface": question_spec()}, ctx)
            self.assertTrue(res.ok, res.content)
            self.assertEqual(len(ctx.extra["surfaces"]), 1)
            self.assertEqual(events[0]["type"], "surface")
            self.assertEqual(events[0]["surface"]["title"],
                             "Which change should I make?")

    def test_invalid_tool_surface_is_a_failure(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ToolContext(job_id="job_tool", workspace=td,
                              evidence=EvidenceLog(), goal="ask")
            res = CreateSurfaceTool().run(
                {"surface": {"title": "x", "blocks": [{"kind": "bad"}]}}, ctx)
            self.assertFalse(res.ok)
            self.assertIn("invalid surface", res.error or "")

    def test_job_serializes_surfaces(self):
        job = Job(goal="ask")
        job.surfaces = [validate_surface(question_spec())]
        data = job.to_dict()
        self.assertEqual(data["surfaces"][0]["kind"], "question")


class SurfaceHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading

        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = ReverseAIServer("127.0.0.1", 0, cls.tmp.name)
        cls.base = f"http://{cls.srv.address[0]}:{cls.srv.address[1]}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.thread.join(timeout=3)
        cls.tmp.cleanup()

    def _make_job_with_surface(self) -> tuple[str, dict]:
        sid, cid, err = self.srv.runs.start({"goal": "surface test",
                                             "provider": "mock"})
        self.assertIsNone(err)
        run = self.srv.runs.get(sid)
        self.assertIsNotNone(run)
        run.done.wait(5)
        rec = self.srv.store.get(sid)
        self.assertIsNotNone(rec)
        surface = validate_surface(question_spec())
        rec["surfaces"] = [surface]
        self.srv.store.path_for(sid).write_text(json.dumps(rec, indent=2))
        return sid, surface

    def test_get_surfaces_and_submit_event(self):
        sid, surface = self._make_job_with_surface()
        status, body = _get(f"{self.base}/jobs/{sid}/surfaces")
        self.assertEqual(status, 200)
        self.assertEqual(body["surfaces"][0]["id"], surface["id"])
        status, body = _post(
            f"{self.base}/jobs/{sid}/surfaces/{surface['id']}/events",
            {"action_id": "continue", "value": {"strategy": "patch"},
             "other_text": ""})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["accepted"])
        status, rec = _get(f"{self.base}/jobs/{sid}")
        self.assertEqual(status, 200)
        self.assertEqual(rec["surfaces"][0]["status"], "submitted")
        status, body = _post(
            f"{self.base}/jobs/{sid}/surfaces/{surface['id']}/events",
            {"action_id": "not-real"},)
        self.assertEqual(status, 400, body)

    def test_respond_continues_the_conversation(self):
        sid, surface = self._make_job_with_surface()
        status, body = _post(
            f"{self.base}/jobs/{sid}/surfaces/{surface['id']}/respond",
            {"action_id": "continue", "value": {"strategy": "patch"},
             "permission": "read", "max_steps": 2})
        self.assertEqual(status, 202, body)
        self.assertIn("job_id", body)
        self.assertNotEqual(body["job_id"], sid)
        run = self.srv.runs.get(body["job_id"])
        self.assertIsNotNone(run)
        run.done.wait(5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
