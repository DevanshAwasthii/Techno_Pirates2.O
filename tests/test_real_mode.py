"""Production startup, provenance and read-only live-browser checks."""
from pathlib import Path
import sqlite3
import zipfile

import pytest

from app import pipeline
from app.engine.records import Record
from app.engine.rules import build_findings
from app.parsers import chrome
from app.ui.main import ROOT, is_demo_path, pc_scan_paths


def test_pc_sources_exclude_project_demo_and_deduplicate(tmp_path):
    scan = tmp_path / "device_scan.json"
    profile = tmp_path / "Profile 1"
    own = tmp_path / "my-export.zip"
    paths = pc_scan_paths(scan, [profile], [ROOT / "samples" / "persona_instagram.zip", own, scan, profile])
    assert paths == [str(scan.resolve()), str(profile.resolve()), str(own.resolve())]
    assert all(not is_demo_path(path) for path in paths)
    assert is_demo_path(ROOT / "samples" / "persona_ios_privacy.ndjson")


def test_discover_numbered_real_browser_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    expected = []
    for browser in ("Google/Chrome", "Microsoft/Edge"):
        for name in ("Default", "Profile 1", "System Profile", "Guest Profile"):
            folder = tmp_path / browser / "User Data" / name
            folder.mkdir(parents=True)
            (folder / "History").write_bytes(b"")
            if name in {"Default", "Profile 1"}:
                expected.append(folder)
    assert set(chrome.default_profiles()) == set(expected)


def test_query_uses_original_database_read_only(tmp_path):
    db = tmp_path / "History"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE metadata (domain TEXT, secret TEXT)")
        con.execute("INSERT INTO metadata VALUES ('example.test', 'SECRET_NOT_SELECTED')")
    before = db.read_bytes()
    assert chrome._query(db, "SELECT domain FROM metadata") == [("example.test",)]
    with pytest.raises(sqlite3.OperationalError):
        chrome._query(db, "DELETE FROM metadata")
    assert db.read_bytes() == before
    assert set(tmp_path.iterdir()) == {db}


def test_live_profiles_have_unique_ids_and_full_source_paths(tmp_path):
    profiles = []
    for name in ("one", "two"):
        folder = tmp_path / name
        with zipfile.ZipFile(ROOT / "samples" / "persona_chrome.zip") as archive:
            archive.extractall(folder)
        profiles.append(folder / "Default")
    result = pipeline.run(profiles)
    assert result["errors"] == []
    ids = [record["id"] for record in result["records"]]
    assert len(ids) == len(set(ids))
    assert all(Path(r["sourceFile"]).is_absolute() for r in result["records"])
    assert result["summary"]["trackersFound"] == 12
    assert result["summary"]["sessionRecorders"] == 6
    assert "6 sites have session-replay cookie indicators" in {f["title"] for f in result["findings"]}


def test_locked_source_keeps_other_metadata_and_reports_problem(tmp_path, monkeypatch):
    with zipfile.ZipFile(ROOT / "samples" / "persona_chrome.zip") as archive:
        archive.extractall(tmp_path)
    query = chrome._query
    def locked_cookies(path, sql):
        if path.name == "Cookies":
            raise sqlite3.OperationalError("database is locked")
        return query(path, sql)
    monkeypatch.setattr(chrome, "_query", locked_cookies)
    result = pipeline.run([tmp_path / "Default"])
    assert any("locked" in error["message"] for error in result["errors"])
    assert any(record["category"] == "activity" for record in result["records"])
    assert result["summary"]["trackersFound"] == 0
    assert result["coverage"]["chrome"]["activity"] == "found"


def test_live_cookie_indicators_do_not_claim_proven_recording():
    records = [Record("cookie", "chrome", "account", "cookie indicator", None,
                      meta={"source": "session_replay", "domain": "example.test", "vendor": "Hotjar", "live_profile": True})]
    findings, _ = build_findings(records)
    assert findings[0].title == "1 sites have session-replay cookie indicators"
    assert "does not prove" in findings[0].detail
