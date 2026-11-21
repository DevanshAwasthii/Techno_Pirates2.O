"""Regression tests for REVIEW-2026-11-22 findings fixed by the engine/data pass."""
import json
import zipfile

import pytest

from app import pipeline
from app.engine.messages import scan_text


def _ig_zip(path, who):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("connections/followers_and_following/followers_1.json",
                   json.dumps([{"string_list_data": [{"value": who, "timestamp": 1700000000}]}]))
    return path


def test_b01_ids_unique_across_same_platform_archives(tmp_path):
    r = pipeline.run([_ig_zip(tmp_path / "a.zip", "one"), _ig_zip(tmp_path / "b.zip", "two")])
    ids = [x["id"] for x in r["records"]]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_b01_identical_copy_skipped_not_double_counted(tmp_path):
    a = _ig_zip(tmp_path / "a.zip", "same")
    b = tmp_path / "a (1).zip"
    b.write_bytes(a.read_bytes())
    r = pipeline.run([a, b])
    assert len(r["records"]) == 1
    assert [e["code"] for e in r["errors"]] == ["duplicate"]


def test_b05_b10_all_mailboxes_read_and_temp_cleaned(tmp_path):
    msg = "From x@{d} Mon Jan 01 00:00:00 2024\nFrom: S <x@{d}>\nSubject: Verify your email\n\nhi\n\n"
    p = tmp_path / "takeout-1.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Takeout/Mail/Inbox.mbox", msg.format(d="one.com"))
        z.writestr("Takeout/Mail/Sent.mbox", msg.format(d="two.com"))
    r = pipeline.run([p])
    assert {x["meta"]["domain"] for x in r["records"]} == {"one.com", "two.com"}
    assert len({x["id"] for x in r["records"]}) == 2
    tmp = pipeline.TMP
    assert not tmp.exists() or not any(tmp.iterdir())


def test_b07_following_as_list_does_not_crash(tmp_path):
    p = tmp_path / "ig.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("connections/followers_and_following/following.json",
                   json.dumps([{"title": "x", "string_list_data": [{"timestamp": 1700000000}]}]))
    r = pipeline.run([p])
    assert r["errors"] == [] and len(r["records"]) == 1


def test_b08_following_only_export_recognised(tmp_path):
    p = tmp_path / "ig.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("connections/followers_and_following/following.json",
                   json.dumps({"relationships_following": [{"title": "y", "string_list_data": [{"timestamp": 1}]}]}))
    assert pipeline.run([p])["errors"] == []


def test_b09_unrelated_json_does_not_disable_html(tmp_path):
    p = tmp_path / "ig.zip"
    box = '<div class="pam _a6-g uiBoxWhite"><div class="_a6-p"><div><div><a href="u">fan</a></div><div>Nov 2, 2026 9:15 pm</div></div></div></div>'
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("connections/followers_and_following/followers_1.html", f"<html>{box}</html>")
        z.writestr("misc.json", "{}")
    r = pipeline.run([p])
    assert r["errors"] == [] and r["records"][0]["meta"]["person"] == "fan"


def test_b11_bad_charset_does_not_drop_mailbox(tmp_path):
    p = tmp_path / "m.mbox"
    p.write_bytes(b"From a@x.com Mon Jan 01 00:00:00 2024\nFrom: A <a@x.com>\nSubject: hi\n"
                  b"Content-Type: text/plain; charset=no-such-charset\n\nbody\n\n"
                  b"From b@app.io Mon Jan 01 00:00:00 2024\nFrom: App <b@app.io>\nSubject: Verify your email\n\nok\n\n")
    r = pipeline.run([p])
    assert r["errors"] == [] and [x["meta"]["domain"] for x in r["records"]] == ["app.io"]


def test_b14_counts_messages_not_occurrences(tmp_path):
    p = tmp_path / "WhatsApp Chat with A.txt"
    p.write_text("01/10/26, 9:00 pm - A: mail a@x.com or b@y.com\n01/10/26, 9:01 pm - B: ok", encoding="utf-8")
    r = pipeline.run([p])
    f = next(f for f in r["findings"] if "email" in f["title"].lower())
    assert f["metric"]["value"] == 1 and len(f["evidence"]) == 1
    assert scan_text("a@x.com b@y.com") == ["Email address", "Email address"]  # occurrences still available


@pytest.mark.parametrize("raw", ["null", "[]", '{"library": [null, 5, "x"], "auto_close_browsers": "yes"}'])
def test_b06_wrong_shape_settings_recover(tmp_path, monkeypatch, raw):
    import app.ui.main as ui
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "s.json")
    (tmp_path / "s.json").write_text(raw)
    s = ui.load_settings()
    assert isinstance(s, dict) and "auto_close_browsers" not in s
    assert all(isinstance(x, str) for x in s.get("library", []))
