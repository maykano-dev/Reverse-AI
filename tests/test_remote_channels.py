"""Desktop listener and Telegram channel boundaries."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.remote.desktop import DesktopBroker, DesktopControlServer  # noqa: E402
from reverseai.remote.telegram import TelegramBot, TelegramConfig  # noqa: E402
from reverseai.security.approvals import ApprovalLedger  # noqa: E402
from reverseai.security.capabilities import CapabilityPolicy  # noqa: E402

ENV = {
    "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
    "REVERSEAI_ENABLE_WORKSTATION": "1",
    "REVERSEAI_ENABLE_REMOTE_CONTROL": "1",
    "REVERSEAI_APPROVAL_KEY": "a" * 32,
}


def _get(url: str, token: str = "") -> tuple[int, dict]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        finally:
            e.close()


def _post(url: str, payload: dict, token: str = "") -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        finally:
            e.close()


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.policy = CapabilityPolicy(ENV)
        self.ledger = ApprovalLedger(Path(self.tmp.name) / "approvals", env=ENV)
        self.broker = DesktopBroker(
            policy=self.policy, ledger=self.ledger,
            root=Path(self.tmp.name) / "sessions")

    def tearDown(self):
        self.tmp.cleanup()

    def test_capability_denied_by_default(self):
        broker = DesktopBroker(policy=CapabilityPolicy({}),
                               root=Path(self.tmp.name) / "denied")
        with self.assertRaises(Exception):
            broker.open("x")

    def test_open_status_and_unsupported_input(self):
        s = self.broker.open("demo")
        out = self.broker.execute(s.id, "status")
        self.assertEqual(out["display"], "none")
        with self.assertRaises(PermissionError):
            self.broker.execute(s.id, "type")
        with self.assertRaises(PermissionError):
            self.broker.execute(s.id, "shell")

    def test_takeover_requires_approval(self):
        s = self.broker.open("demo")
        with self.assertRaises(PermissionError):
            self.broker.execute(s.id, "takeover")
        grant = self.ledger.grant("desktop.takeover", s.id)
        out = self.broker.execute(s.id, "takeover", grant.token)
        self.assertTrue(out["ok"])
        self.assertEqual(self.broker.execute(s.id, "status")["status"], "open")

    def test_loopback_listener_requires_token(self):
        token = "desk-" + "x" * 20
        server = DesktopControlServer(self.broker, token)
        server.start()
        try:
            base = f"http://{server.address[0]}:{server.address[1]}"
            self.assertEqual(_get(base + "/sessions")[0], 401)
            status, body = _get(base + "/sessions", token)
            self.assertEqual(status, 200, body)
            status, body = _post(base + "/open", {"name": "ui"}, token)
            self.assertEqual(status, 200, body)
            session = body["id"]
            status, body = _post(base + "/action",
                                 {"session": session, "action": "type"}, token)
            self.assertEqual(status, 403, body)
        finally:
            server.stop()


class TelegramTests(unittest.TestCase):
    def bot(self, *, paired=True):
        cfg = TelegramConfig(allowed_chat_ids=[42] if paired else [],
                             pairing_code="PAIR", rate_limit_seconds=0)
        return TelegramBot(cfg, policy=CapabilityPolicy(ENV),
                           job_summary=lambda n: [{"id": "j1", "status": "done",
                                                   "goal": "inspect"}],
                           discover=lambda p: {"opportunities": [{"title": "x"}]},
                           readiness=lambda p: {"verdict": "analysis_only"})

    def test_read_only_commands(self):
        bot = self.bot()
        self.assertIn("online", bot.handle_text(42, "/status"))
        self.assertIn("j1", bot.handle_text(42, "/jobs"))
        self.assertIn("opportunities", bot.handle_text(42, "/discover ./app"))
        self.assertIn("analysis_only", bot.handle_text(42, "/readiness ./app"))

    def test_unpaired_chat_is_refused(self):
        bot = self.bot(paired=False)
        self.assertIn("not paired", bot.handle_text(99, "/status"))
        self.assertIn("Paired", bot.handle_text(99, "/pair PAIR"))
        self.assertIn("online", bot.handle_text(99, "/status"))

    def test_no_shell_or_payment_command(self):
        bot = self.bot()
        self.assertIn("Unknown", bot.handle_text(42, "/exec rm -rf /"))
        self.assertIn("Unknown", bot.handle_text(42, "/pay 100"))

    def test_capability_disabled(self):
        cfg = TelegramConfig(allowed_chat_ids=[42], rate_limit_seconds=0)
        bot = TelegramBot(cfg, policy=CapabilityPolicy({}))
        self.assertIn("disabled", bot.handle_text(42, "/status"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
