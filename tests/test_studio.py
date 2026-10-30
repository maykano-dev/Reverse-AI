"""Studio: edit a generated deliverable and regenerate / export it."""

import tempfile
import unittest
from pathlib import Path

from reverseai import studio


class StudioSpecTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.spec = {"slides": [
            {"title": "Intro", "subtitle": "s", "bullets": ["a", "b"]},
            {"title": "Two", "bullets": ["c"]},
        ]}
        studio.save_spec(self.ws, "deck.pptx", "pptx", self.spec, name="deck")

    def test_load_roundtrip(self):
        rec = studio.load_spec(self.ws, "deck.pptx")
        self.assertEqual(rec["kind"], "pptx")
        self.assertEqual(len(rec["spec"]["slides"]), 2)
        self.assertEqual(rec["filename"], "deck.pptx")

    def test_load_missing_is_error(self):
        with self.assertRaises(studio.StudioError):
            studio.load_spec(self.ws, "nope.pptx")

    def test_regenerate_overwrites_file(self):
        before = Path(self.ws, "deck.pptx")
        studio.regenerate(self.ws, "deck.pptx",
                          {"slides": [{"title": "Only", "bullets": []}]})
        self.assertTrue(before.is_file())
        self.assertTrue(before.read_bytes().startswith(b"PK"))  # a zip/OOXML
        # the sidecar reflects the edit
        rec = studio.load_spec(self.ws, "deck.pptx")
        self.assertEqual(rec["spec"]["slides"][0]["title"], "Only")

    def test_export_deck_to_pdf(self):
        out = studio.export(self.ws, "deck.pptx", "pdf")
        self.assertEqual(out.kind, "pdf")
        self.assertTrue(out.data.startswith(b"%PDF-"))
        self.assertTrue(out.filename.endswith(".pdf"))

    def test_export_unknown_format_refused(self):
        with self.assertRaises(studio.StudioError):
            studio.export(self.ws, "deck.pptx", "exe")

    def test_filename_traversal_refused(self):
        for bad in ("..", "../x", "a/b", "x\\y"):
            with self.assertRaises(studio.StudioError):
                studio.save_spec(self.ws, bad, "pptx", {}, name="x")


class StudioDocTests(unittest.TestCase):
    def test_document_regenerate(self):
        ws = tempfile.mkdtemp()
        spec = {"title": "Report", "blocks": [
            {"type": "heading", "text": "H"}, {"type": "paragraph", "text": "p"}]}
        studio.save_spec(ws, "report.docx", "docx", spec, name="report")
        out = studio.regenerate(ws, "report.docx",
                                {"title": "Report v2", "blocks": spec["blocks"]})
        self.assertEqual(out.kind, "docx")
        self.assertTrue(Path(ws, "report.docx").read_bytes().startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
