import shutil
import subprocess
from pathlib import Path
import pytest
from app.engine.messages import person_key, closeness
from app.engine.records import Record
from app.parsers import ocr
from app.ui import main as ui


def test_person_keys_preserve_scripts_marks_and_raw_fallback():
    names = ["अमित", "सुमित", "李", "王", "😀", "🚀"]
    assert len({person_key(n) for n in names}) == len(names)
    assert person_key("Ａlice") == person_key("Alice")
    assert person_key("अमित") != person_key("अमत")
    assert person_key("😀") == "😀"
    rows = [Record(str(i), "whatsapp", "message", "synthetic", None, meta={"person": n}) for i, n in enumerate(names)]
    assert len(closeness(rows)) == len(names)


def test_ocr_status_accepts_non_latin_initials(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "frames", lambda path: [(0, None)])
    monkeypatch.setattr(ocr, "read_lines", lambda frame: ["Viewed by 3", "अमित", "Today 10:00 am", "李", "Today 10:01 am", "علي", "Today 10:02 am"])
    records, _ = ocr.parse(tmp_path / "synthetic.mp4")
    assert {r.meta["person"] for r in records if r.meta.get("person")} == {"अमित", "李", "علي"}


def test_pdf_embeds_unicode_and_preserves_extracted_text(tmp_path):
    text = "अमित 李 😀"
    pdf = ui.report_bytes({"findings": [{"title": text}]})
    assert b"/FontFile2" in pdf and b"/ToUnicode" in pdf
    tool = shutil.which("pdftotext")
    if not tool:
        pytest.skip("pdftotext unavailable; embedding already checked")
    p = tmp_path / "unicode.pdf"
    p.write_bytes(pdf)
    result = subprocess.run([tool, str(p), "-"], capture_output=True, check=True).stdout.decode("utf-8")
    assert all(name in result for name in text.split())


def test_pdf_missing_fonts_preserves_text_as_escapes(tmp_path, monkeypatch):
    monkeypatch.setenv("WINDIR", str(tmp_path))
    pdf = ui.report_bytes({"findings": [{"title": "अमित"}]})
    assert pdf.startswith(b"%PDF") and b"%%EOF" in pdf
    class MissingFonts:
        def add_font(self, *a, **kw): raise AssertionError("no font should be loaded")
    assert ui.report_fonts(MissingFonts()) is None
