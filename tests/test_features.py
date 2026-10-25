"""Tests for the unified agent features added in v0.2.

Covers naming, memory, research parsing, routines, templates/narrative, the
Unlimited-OCR adapter, durable events/conversations, cancellation, and the new
HTTP endpoints. No network access: research parsing is pure, OCR is mocked.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import Agent, Permission, ToolContext, ToolMediator, ToolRegistry, default_tools
from reverseai.agent.evidence import EvidenceLog
from reverseai.agent.memory import MemoryStore
from reverseai.agent.narrative import describe_tool, plan_for
from reverseai.agent.providers.mock import MockProvider, call, say
from reverseai.agent.research import (
    ResearchError,
    is_public_host,
    parse_page,
    parse_search_results,
)
from reverseai.agent.store import JobStore
from reverseai.agent.templates import all_templates, get_template
from reverseai.naming import artifact_meta, artifact_name, safe_download_name
from reverseai.ocr.engine import _endpoint, _parse_content, ocr_unlimited, unlimited_ocr_available
from reverseai.routines import RoutineScheduler, RoutineStore, compute_next
from reverseai.server.app import ReverseAIServer
from reverseai.server.runs import RunManager


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------
class NamingTests(unittest.TestCase):
    def test_descriptive_unique_and_safe(self):
        a = artifact_name("/tmp/app.exe", "remove the license check", "patch",
                          nonce="abc123")
        self.assertEqual(a, "app-patched-remove-license-check-abc123.exe")
        b = artifact_name("/tmp/app.exe", "remove the license check", "patch",
                          nonce="def456")
        self.assertNotEqual(a, b)
        self.assertNotIn(" ", a)
        self.assertNotIn("/", a)

    def test_suffix_override_and_safe_download(self):
        n = artifact_name("example.com", "clone the landing page", "site",
                          suffix=".zip", nonce="ff00")
        self.assertTrue(n.endswith(".zip"))
        self.assertTrue(n.startswith("example-com-site"))
        self.assertEqual(safe_download_name('a"b\r\nc'), "abc")

    def test_artifact_meta(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.bin"
            p.write_bytes(b"hello")
            meta = artifact_meta(p)
            self.assertEqual(meta["name"], "x.bin")
            self.assertEqual(meta["size"], 5)
            self.assertEqual(len(meta["sha256"]), 64)


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------
class MemoryTests(unittest.TestCase):
    def test_add_search_delete_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.json"
            m = MemoryStore(path)
            note = m.add("Prefers short answers", tags=["style"])
            self.assertTrue(note["id"].startswith("mem_"))
            m.add("Works on mobile reverse engineering")
            self.assertEqual(len(m.all()), 2)
            self.assertEqual(len(m.search("mobile")), 1)
            self.assertIn("Prefers short answers", m.prompt_context())
            # reload from disk
            m2 = MemoryStore(path)
            self.assertEqual(len(m2.all()), 2)
            self.assertTrue(m2.delete(note["id"]))
            self.assertFalse(m2.delete(note["id"]))

    def test_empty_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                MemoryStore(Path(d) / "m.json").add("   ")


# ---------------------------------------------------------------------------
# research parsing (no network)
# ---------------------------------------------------------------------------
class ResearchTests(unittest.TestCase):
    def test_parse_page_strips_scripts_and_extracts_meta(self):
        html = b"""<html><head><title>Test Page</title>
        <meta name="description" content="A useful description">
        <script>evil()</script><style>.x{}</style></head>
        <body><h1>Hello</h1><p>World &amp; friends</p><a href="/next">Next</a></body></html>"""
        page = parse_page(html, "https://example.com/a")
        self.assertEqual(page.title, "Test Page")
        self.assertEqual(page.description, "A useful description")
        self.assertIn("Hello", page.text)
        self.assertIn("World & friends", page.text)
        self.assertNotIn("evil()", page.text)
        self.assertIn("https://example.com/next", page.links)

    def test_parse_search_results_decodes_redirect(self):
        html = """<a class="result__a"
          href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Title A</a>
          <a class="result__snippet">Snippet A</a>
          <a class="result__a" href="https://example.com/b">Title B</a>"""
        rows = parse_search_results(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].url, "https://example.com/a")
        self.assertEqual(rows[0].title, "Title A")
        self.assertEqual(rows[0].snippet, "Snippet A")
        self.assertEqual(rows[1].url, "https://example.com/b")

    def test_private_hosts_rejected(self):
        self.assertFalse(is_public_host("127.0.0.1"))
        self.assertFalse(is_public_host("localhost"))


# ---------------------------------------------------------------------------
# routines
# ---------------------------------------------------------------------------
class RoutineTests(unittest.TestCase):
    def test_compute_next_daily_weekdays_weekly_every_once(self):
        from datetime import datetime

        now = datetime(2026, 10, 26, 10, 0)  # Monday
        self.assertEqual(
            compute_next({"kind": "daily", "time": "09:00"}, now),
            datetime(2026, 10, 27, 9, 0).timestamp())
        self.assertEqual(
            compute_next({"kind": "daily", "time": "11:00"}, now),
            datetime(2026, 10, 26, 11, 0).timestamp())
        self.assertEqual(
            compute_next({"kind": "weekdays", "time": "09:00"}, now),
            datetime(2026, 10, 27, 9, 0).timestamp())
        self.assertEqual(
            compute_next({"kind": "weekly", "weekday": 4, "time": "09:00"}, now),
            datetime(2026, 10, 30, 9, 0).timestamp())
        self.assertEqual(
            compute_next({"kind": "every", "minutes": 30}, now),
            datetime(2026, 10, 26, 10, 30).timestamp())
        self.assertIsNone(compute_next({"kind": "once", "at": "2020-01-01T09:00"}, now))

    def test_store_and_scheduler(self):
        class FakeRuns:
            def __init__(self):
                self.started = []
            def get(self, _id):
                return None
            def start(self, body):
                self.started.append(body)
                return f"job_{len(self.started):08x}", "conv_x", None

        with tempfile.TemporaryDirectory() as d:
            store = RoutineStore(Path(d) / "routines.json")
            r = store.add("brief", "Brief me", {"kind": "daily", "time": "09:00"})
            self.assertIsNotNone(r.next_run)
            self.assertEqual(len(store.all()), 1)
            runs = FakeRuns()
            sched = RoutineScheduler(store, runs)
            # force due
            r.next_run = time.time() - 1
            store.update(r)
            started = sched.run_due()
            self.assertEqual(len(started), 1)
            self.assertEqual(runs.started[0]["goal"], "Brief me")
            # persisted update
            again = RoutineStore(Path(d) / "routines.json").get(r.id)
            self.assertIsNotNone(again.last_job)


# ---------------------------------------------------------------------------
# templates + narrative
# ---------------------------------------------------------------------------
class TemplateTests(unittest.TestCase):
    def test_templates_and_fallback(self):
        ids = {t.id for t in all_templates()}
        self.assertIn("reverse", ids)
        self.assertIn("researcher", ids)
        self.assertEqual(get_template("nope").id, "general")
        self.assertIn("research", get_template("researcher").addendum.lower())

    def test_narrative_is_human_and_never_says_investigating(self):
        for name in ("analyze_binary", "run_in_sandbox", "web_search", "apply_byte_patch"):
            d = describe_tool(name, {"query": "test", "offset": 16})
            self.assertTrue(d["title"])
            self.assertNotIn("investigat", d["title"].lower())
            self.assertNotIn("investigat", d["detail"].lower())
        for t in all_templates():
            for step in plan_for(t.id, True, "do it"):
                self.assertNotIn("investigat", step["title"].lower())


# ---------------------------------------------------------------------------
# OCR adapter (mocked HTTP)
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._payload


class OcrTests(unittest.TestCase):
    def test_endpoint_variants(self):
        with mock.patch.dict(os.environ, {"REVERSEAI_OCR_URL": "http://x:10000"}):
            self.assertEqual(_endpoint(), "http://x:10000/v1/chat/completions")
        with mock.patch.dict(os.environ, {"REVERSEAI_OCR_URL": "http://x:10000/v1"}):
            self.assertEqual(_endpoint(), "http://x:10000/v1/chat/completions")
        with mock.patch.dict(os.environ, {"REVERSEAI_OCR_URL": "http://x/v1/chat/completions"}):
            self.assertEqual(_endpoint(), "http://x/v1/chat/completions")

    def test_parse_content_shapes(self):
        self.assertEqual(_parse_content({"choices": [{"message": {"content": "hi"}}]}), "hi")
        self.assertEqual(_parse_content({"choices": [{"message": {"content": [
            {"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]}), "a\nb")

    def test_unlimited_ocr_mocked(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "x.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            payload = {"choices": [{"message": {"content": "parsed text"}}]}
            with mock.patch.dict(os.environ, {
                "REVERSEAI_OCR_URL": "http://localhost:9",
                "REVERSEAI_OCR_MODEL": "Unlimited-OCR",
            }), mock.patch("reverseai.ocr.engine.urllib.request.urlopen",
                           return_value=_FakeResp(payload)):
                self.assertTrue(unlimited_ocr_available())
                res = ocr_unlimited(str(img))
                self.assertTrue(res.ok)
                self.assertEqual(res.text, "parsed text")
                self.assertEqual(res.engine, "unlimited-ocr")


# ---------------------------------------------------------------------------
# conversation events, cancellation, persistence
# ---------------------------------------------------------------------------
class ConversationFeatureTests(unittest.TestCase):
    def test_reason_and_plan_events(self):
        provider = MockProvider([call("host_capabilities", {}), say("Done.")])
        agent = Agent(provider, max_permission=Permission.READ)
        events = []
        job = agent.run("Check the host.", on_event=events.append)
        types = [e["type"] for e in events]
        self.assertIn("plan", types)
        self.assertIn("reason", types)
        reasons = [e for e in events if e["type"] == "reason"]
        self.assertTrue(reasons)
        self.assertNotIn("investigat", reasons[0]["title"].lower())
        self.assertEqual(job.status, "completed")

    def test_cancellation(self):
        provider = MockProvider([say("should not run")])
        agent = Agent(provider, max_permission=Permission.READ)
        ev = threading.Event()
        ev.set()
        job = agent.open().run_turn("Do something", stop_event=ev)
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(provider.calls, [])

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            provider = MockProvider([call("host_capabilities", {}), say("Done.")])
            agent = Agent(provider, max_permission=Permission.READ, template="researcher")
            conv = agent.open(workspace=d)
            conv.evidence.observed("a fact", source="test")
            conv.ctx.sources = [{"url": "https://example.com", "title": "Example"}]
            conv.run_turn("Check.", on_event=lambda e: None)
            state = conv.to_state()
            restored = type(conv).from_state(agent, state)
            self.assertEqual(restored.template, "researcher")
            self.assertEqual(len(restored.evidence.all()), 1)
            self.assertEqual(restored.ctx.sources[0]["url"], "https://example.com")
            self.assertEqual(len(restored.messages), len(conv.messages))


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------
def _get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            try:
                body = json.loads(e.read())
            except Exception:
                body = {}
            return e.code, body
        finally:
            e.close()


def _post(base, path, payload, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                 headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            try:
                body = json.loads(e.read())
            except Exception:
                body = {}
            return e.code, body
        finally:
            e.close()


def _sse(base, path, limit=100):
    types = []
    with urllib.request.urlopen(base + path, timeout=10) as r:
        for raw in r:
            line = raw.decode().strip()
            if line.startswith("data:"):
                ev = json.loads(line[5:].strip())
                types.append(ev)
                if ev.get("type") in ("final", "error") or len(types) >= limit:
                    break
    return types


class ServerFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = mock.patch.dict(os.environ, {"REVERSEAI_PROVIDER": "mock"}, clear=False)
        cls.env.start()
        os.environ.pop("REVERSEAI_AUTH_TOKEN", None)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = ReverseAIServer("127.0.0.1", 0, cls.tmp.name)
        cls.host, cls.port = cls.srv.address
        cls.base = f"http://{cls.host}:{cls.port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()
        cls.env.stop()

    def test_templates_and_skills(self):
        s, b = _get(self.base, "/templates")
        self.assertEqual(s, 200)
        self.assertTrue(any(t["id"] == "researcher" for t in b["templates"]))
        s, b = _get(self.base, "/skills")
        self.assertEqual(s, 200)
        self.assertIn("skills", b)

    def test_memory_crud(self):
        s, b = _post(self.base, "/memory", {"text": "likes concise answers", "tags": ["style"]})
        self.assertEqual(s, 200)
        nid = b["note"]["id"]
        s, b = _get(self.base, "/memory")
        self.assertTrue(any(n["id"] == nid for n in b["notes"]))
        req = urllib.request.Request(self.base + f"/memory/{nid}", method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_routines_crud(self):
        s, b = _post(self.base, "/routines", {
            "name": "morning", "goal": "Brief me",
            "schedule": {"kind": "daily", "time": "09:00"},
        })
        self.assertEqual(s, 200, b)
        rid = b["routine"]["id"]
        s, b = _get(self.base, "/routines")
        self.assertTrue(any(r["id"] == rid for r in b["routines"]))
        req = urllib.request.Request(self.base + f"/routines/{rid}", method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_usage_and_feedback(self):
        s, b = _get(self.base, "/usage")
        self.assertEqual(s, 200)
        self.assertIn("total_tokens", b)
        s, b = _post(self.base, "/feedback", {"job_id": "job_abc", "rating": "up"})
        self.assertEqual(s, 200)
        s, b = _get(self.base, "/feedback")
        self.assertTrue(any(f["rating"] == "up" for f in b["feedback"]))

    def test_start_template_and_events_replay(self):
        s, b = _post(self.base, "/jobs/start",
                     {"goal": "say hi", "provider": "mock", "template": "researcher"})
        self.assertEqual(s, 200)
        job_id = b["job_id"]
        events = _sse(self.base, f"/jobs/{job_id}/events")
        types = [e["type"] for e in events]
        self.assertIn("start", types)
        self.assertIn("plan", types)
        self.assertEqual(types[-1], "final")
        # Replay from an offset: should start later and still end at final.
        replay = _sse(self.base, f"/jobs/{job_id}/events?after=2")
        self.assertTrue(replay)
        self.assertEqual(replay[-1]["type"], "final")
        self.assertLessEqual(len(replay), len(events))

    def test_auth_and_path_guard(self):
        token = "test-token-123"
        os.environ["REVERSEAI_AUTH_TOKEN"] = token
        try:
            s, _ = _get(self.base, "/jobs")
            self.assertEqual(s, 401)
            s, b = _get(self.base, "/jobs", {"Authorization": f"Bearer {token}"})
            self.assertEqual(s, 200)
            s, b = _post(self.base, "/analyze", {"path": "/etc/passwd"},
                         {"Authorization": f"Bearer {token}"})
            self.assertEqual(s, 403)
        finally:
            os.environ.pop("REVERSEAI_AUTH_TOKEN", None)


class RunManagerDurabilityTests(unittest.TestCase):
    def test_conversation_restores_after_memory_eviction(self):
        with tempfile.TemporaryDirectory() as d:
            rm = RunManager(JobStore(d))
            sid, cid, err = rm.start({"goal": "one", "provider": "mock"})
            self.assertIsNone(err)
            self.assertTrue(rm.get(sid).done.wait(5))
            # Simulate a restart: drop in-memory conversations.
            rm._convos.clear()
            sid2, cid2, err2 = rm.start({
                "goal": "two", "provider": "mock", "conversation_id": cid,
            })
            self.assertIsNone(err2)
            self.assertEqual(cid2, cid)
            self.assertTrue(rm.get(sid2).done.wait(5))

    def test_cancel_flag(self):
        with tempfile.TemporaryDirectory() as d:
            rm = RunManager(JobStore(d))
            from reverseai.server.runs import Run
            r = Run(job_id="job_abcdef012345")
            rm._runs[r.job_id] = r
            self.assertTrue(rm.cancel(r.job_id))
            self.assertTrue(r.cancel.is_set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
