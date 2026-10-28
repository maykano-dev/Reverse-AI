"""The browser surface renderer and its safety-facing pieces are present."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "reverseai/server/static/app.js"
CSS = ROOT / "reverseai/server/static/style.css"


class SurfaceUIContractTests(unittest.TestCase):
    def test_renderer_handles_the_surface_vocabulary(self):
        js = APP.read_text(encoding="utf-8")
        for token in ("renderSurface", "renderSurfaces", "surface-card",
                      "data-surface-other", "surface-approval",
                      "surface-chart", "surface-graph", "surface-custom",
                      "image_choice", "surface-images", "imageMeta"):
            self.assertIn(token, js, token)

    def test_other_escape_hatch_is_default(self):
        js = APP.read_text(encoding="utf-8")
        self.assertIn("Other — type your own", js)
        self.assertIn("data-surface-other", js)

    def test_surface_styles_exist(self):
        css = CSS.read_text(encoding="utf-8")
        for token in (".surface-card", ".surface-option", ".surface-table",
                      ".surface-approval", ".surface-custom"):
            self.assertIn(token, css, token)

    def test_answer_actions_exist(self):
        js = APP.read_text(encoding="utf-8")
        self.assertIn("renderAnswerActions", js)
        self.assertIn("navigator.clipboard.writeText", js)

    def test_sidebar_groups_turns_by_conversation(self):
        js = APP.read_text(encoding="utf-8")
        self.assertIn("j.conversation_id || j.id", js)
        self.assertIn("groups.get(key)", js)
        self.assertIn("g.jobs.flatMap(", js)
        self.assertIn("x.ids", js)

    def test_generated_sites_have_a_live_preview(self):
        js = APP.read_text(encoding="utf-8")
        self.assertIn("renderPreviewCard", js)
        self.assertIn("previewHref", js)
        self.assertIn("preview_fresh", js)
        self.assertIn("client: 2", js)
        self.assertIn(".preview-card", CSS.read_text(encoding="utf-8"))

    def test_preview_panel_is_a_live_browser(self):
        js = APP.read_text(encoding="utf-8")
        html = (ROOT / "reverseai/server/static/index.html").read_text(encoding="utf-8")
        for token in ("pvReload", "pvBack", "pvForward", "pvFull", "pvNewTab",
                      "pvExternal", "pvLaunch", "pvTabList"):
            self.assertIn(token, js, token)
            self.assertIn(token, html, token)
        for token in ("previewTabs", "switchPreviewTab", "closePreviewTab"):
            self.assertIn(token, js)
        server = (ROOT / "reverseai/server/app.py").read_text(encoding="utf-8")
        self.assertIn("__reload.js", server)
        self.assertIn("__events", server)
        self.assertIn("pv-live", CSS.read_text(encoding="utf-8"))

    def test_service_worker_updates_do_not_leave_a_stale_shell(self):
        js = APP.read_text(encoding="utf-8")
        sw = (ROOT / "reverseai/server/static/sw.js").read_text(encoding="utf-8")
        self.assertIn("controllerchange", js)
        self.assertIn("rvai-v19", sw)

    def test_custom_view_is_sandboxed(self):
        js = APP.read_text(encoding="utf-8")
        self.assertIn('iframe.setAttribute("sandbox", "allow-scripts")', js)
        self.assertIn("referrerpolicy", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
