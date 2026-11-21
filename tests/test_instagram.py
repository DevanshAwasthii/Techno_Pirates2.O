import io
import json
import zipfile
from pathlib import Path

import pytest

from app import pipeline
from app.engine.messages import scan_text
from app.parsers.instagram import fix_text

PERSONA = Path(__file__).resolve().parents[1] / "samples" / "persona_instagram.zip"


@pytest.fixture(scope="module")
def result():
    if not PERSONA.exists():
        import runpy
        runpy.run_path(str(PERSONA.parent / "make_persona.py"))
    return pipeline.run([PERSONA])


def test_persona_end_to_end(result):
    assert not result["errors"]
    titles = [f["title"] for f in result["findings"]]
    assert any("23 companies sent Meta" in t for t in titles)
    assert any("15 advertisers" in t for t in titles)
    assert any("4 different IP" in t for t in titles)
    assert result["coverage"]["instagram"] == {k: "found" for k in ("location", "interest", "contact", "activity")}


def test_every_finding_has_resolvable_evidence(result):
    ids = {r["id"] for r in result["records"]}
    for f in result["findings"]:
        assert f["evidence"], f["title"]
        assert set(f["evidence"]) <= ids, f["title"]
        assert f["action"]["steps"], f["title"]


def test_sensitive_data_found_in_dms(result):
    titles = " ".join(f["title"] for f in result["findings"])
    for label in ("aadhaar", "phone", "pan", "otp", "email"):
        assert label in titles.lower(), label


def test_mojibake_fixed(result):
    texts = [r["meta"].get("text", "") for r in result["records"] if r["category"] == "message"]
    assert any("আজকে" in t for t in texts)  # Bengali survives
    assert fix_text("plain") == "plain"


def test_closeness_ranks_frequent_contacts(result):
    top = [p["name"] for p in result["summary"]["topPeople"][:3]]
    assert "arjun.das" in top


def test_scan_text_no_double_count():
    assert scan_text("aadhaar 4521 8890 1234") == ["Aadhaar number"]
    assert scan_text("call 9876543210") == ["Phone number"]
    assert scan_text("nothing here") == []


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_html_export_rejected(tmp_path):
    p = tmp_path / "ig.zip"
    p.write_bytes(_zip({"your_instagram_activity/likes/liked_posts.html": "<html></html>"}))
    r = pipeline.run([p])
    assert r["errors"][0]["code"] == "html_export"


def test_corrupt_and_unknown_files_do_not_crash(tmp_path):
    bad = tmp_path / "bad.zip"; bad.write_bytes(b"not a zip")
    other = tmp_path / "x.zip"; other.write_bytes(_zip({"readme.txt": "hi"}))
    r = pipeline.run([bad, other, PERSONA])
    codes = sorted(e["code"] for e in r["errors"])
    assert codes == ["corrupt_zip", "wrong_format"]
    assert r["findings"]  # persona still analysed


def test_cancel(tmp_path):
    import threading
    ev = threading.Event(); ev.set()
    with pytest.raises(pipeline.Cancelled):
        pipeline.run([PERSONA], cancel=ev)
