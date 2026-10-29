"""Document & file generation: validity of every format + the agent tool."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.docgen import KINDS, DocGenError, generate  # noqa: E402

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")

_DOC_SPEC = {"title": "Report", "blocks": [
    {"type": "heading", "text": "Summary"},
    {"type": "paragraph", "text": "Verified in the sandbox."},
    {"type": "bullet", "text": "point one"},
]}
_SPECS = {
    "pdf": _DOC_SPEC, "docx": _DOC_SPEC, "md": _DOC_SPEC,
    "html": _DOC_SPEC, "txt": _DOC_SPEC,
    "pptx": {"slides": [{"title": "A", "subtitle": "s", "bullets": ["x", "y"]},
                        {"title": "B", "bullets": ["z"]}]},
    "xlsx": {"rows": [["name", "n"], ["a", 1], ["b", 2]], "sheet": "S"},
    "csv": {"rows": [["a", "b"], [1, 2]]},
    "json": {"data": {"ok": True}},
    "svg": {"content": '<svg xmlns="http://www.w3.org/2000/svg"/>'},
}


def _wellformed(data: bytes) -> bool:
    try:
        minidom.parseString(data)
        return True
    except Exception:
        return False


class GenerateTests(unittest.TestCase):
    def test_every_kind_generates_nonempty_with_right_name(self):
        for k in KINDS:
            f = generate(k, _SPECS[k])
            self.assertTrue(f.data, k)
            self.assertTrue(f.filename.endswith("." + k), f.filename)
            self.assertEqual(f.mime, generate(k, _SPECS[k]).mime)

    def test_unsupported_kind_raises(self):
        with self.assertRaises(DocGenError):
            generate("exe", {})

    def test_aliases_map(self):
        self.assertEqual(generate("powerpoint", _SPECS["pptx"]).kind, "pptx")
        self.assertEqual(generate("word", _DOC_SPEC).kind, "docx")
        self.assertEqual(generate("excel", _SPECS["xlsx"]).kind, "xlsx")

    def test_pdf_is_valid(self):
        data = generate("pdf", _DOC_SPEC).data
        self.assertTrue(data.startswith(b"%PDF-1."))
        self.assertIn(b"xref", data)
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))

    def test_ooxml_are_valid_zips_with_required_parts(self):
        checks = {
            "pptx": ["[Content_Types].xml", "ppt/presentation.xml",
                     "ppt/slides/slide1.xml", "ppt/slideMasters/slideMaster1.xml"],
            "docx": ["[Content_Types].xml", "word/document.xml"],
            "xlsx": ["[Content_Types].xml", "xl/workbook.xml",
                     "xl/worksheets/sheet1.xml"],
        }
        for kind, parts in checks.items():
            data = generate(kind, _SPECS[kind]).data
            with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
                self.assertIsNone(z.testzip(), kind)
                names = set(z.namelist())
                for p in parts:
                    self.assertIn(p, names, f"{kind} missing {p}")
                    self.assertTrue(_wellformed(z.read(p)), f"{kind}:{p} not well-formed XML")

    def test_xlsx_numbers_and_text(self):
        data = generate("xlsx", {"rows": [["n", 42], ["t", "hi"]]}).data
        with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
            sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("<v>42</v>", sheet)
        self.assertIn("inlineStr", sheet)


@unittest.skipUnless(SOFFICE, "LibreOffice not available")
class OfficeOpenTests(unittest.TestCase):
    """The strongest check: a real office suite opens and converts the files."""

    def _converts(self, kind: str) -> bool:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / f"f.{kind}"
            src.write_bytes(generate(kind, _SPECS[kind]).data)
            out = Path(td) / "out"
            out.mkdir()
            r = subprocess.run(
                [SOFFICE, "--headless", "--convert-to", "pdf",
                 "--outdir", str(out), str(src)],
                capture_output=True, timeout=120)
            return r.returncode == 0 and any(out.glob("*.pdf"))

    def test_pptx_opens(self):
        self.assertTrue(self._converts("pptx"))

    def test_docx_opens(self):
        self.assertTrue(self._converts("docx"))

    def test_xlsx_opens(self):
        self.assertTrue(self._converts("xlsx"))


class CreateDocumentToolTests(unittest.TestCase):
    def test_tool_writes_file_and_marks_fresh_deliverable(self):
        from reverseai.agent import ToolContext
        from reverseai.agent.evidence import EvidenceLog
        from reverseai.agent.docgen_tools import CreateDocumentTool
        with tempfile.TemporaryDirectory() as td:
            ctx = ToolContext(job_id="j1", workspace=td, target_path=None,
                              evidence=EvidenceLog(), goal="make a report",
                              extra={})
            res = CreateDocumentTool().run(
                {"kind": "pdf", "spec": _DOC_SPEC, "name": "my report"}, ctx)
            self.assertTrue(res.ok, res.content)
            self.assertEqual(ctx.extra["modified_operation"], "document")
            self.assertEqual(ctx.extra["modified_turn"], "j1")
            p = Path(ctx.extra["modified_path"])
            self.assertTrue(p.exists() and p.read_bytes().startswith(b"%PDF"))

    def test_bad_spec_is_rejected(self):
        from reverseai.agent import ToolContext
        from reverseai.agent.docgen_tools import CreateDocumentTool
        with tempfile.TemporaryDirectory() as td:
            ctx = ToolContext(job_id="j", workspace=td, target_path=None,
                              goal="x", extra={})
            res = CreateDocumentTool().run({"kind": "pdf", "spec": "nope"}, ctx)
            self.assertFalse(res.ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
