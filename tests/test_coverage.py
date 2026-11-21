"""Honest source coverage, bounded scans and unavailable-vs-empty reporting."""
import json
from pathlib import Path
import sqlite3
import time
import zipfile

import pytest

from app import pipeline
from app.engine.coverage import coverage_rows, audit_is_partial, tracker_display, storage_display, chat_display
from app.parsers import chrome, deviceScan
from app.ui.main import report_bytes
from scanner import scan

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    roaming.mkdir()
    local.mkdir()
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return roaming, local


def test_log_limit_does_not_make_storage_measurements_incomplete(appdata):
    roaming, _ = appdata
    folder = roaming / "App"
    folder.mkdir()
    for i in range(305):
        (folder / f"{i}.log").write_text("user@example.test")
    result = scan.scan_laptop()
    scope = result["scope"]
    assert not result["storage_partial"]
    assert result["logs_partial"] and result["partial"]
    assert scope["folders_complete"] == scope["folders_discovered"] == 1
    assert scope["logs_checked"] == 300 and scope["logs_skipped_limit"] == 5
    assert scope["logs_candidates"] == 305
    assert not result["apps"][0]["partial"]
    records, _ = deviceScan.parse(Path("scan.json"), {"laptop": result})
    assert not next(r for r in records if r.meta.get("source") == "laptop_store").meta["partial"]


def test_large_logs_are_counted_as_skipped(appdata):
    roaming, _ = appdata
    folder = roaming / "App"
    folder.mkdir()
    (folder / "large.txt").write_bytes(b"x" * (scan.MAX_LOG_BYTES + 1))
    (folder / "small.log").write_text("one@example.test")
    result = scan.scan_laptop()
    assert result["scope"]["logs_skipped_large"] == 1
    assert result["scope"]["logs_checked"] == 1
    assert result["logs_partial"] and not result["storage_partial"]


def test_zero_budget_reports_storage_limit(appdata):
    result = scan.scan_laptop(max_seconds=0)
    assert result["storage_partial"] and result["scope"]["storage_time_limited"]


def test_log_regex_remains_bounded_for_large_non_email_input(appdata):
    roaming, _ = appdata
    folder = roaming / "App"
    folder.mkdir()
    (folder / "large.log").write_bytes(b"A" * (scan.MAX_LOG_BYTES - 8) + b"@invalid")
    start = time.monotonic()
    result = scan.scan_laptop()
    assert time.monotonic() - start < 5
    assert result["scope"]["logs_checked"] == 1
    assert result["logs"][0]["emails"] == 0


@pytest.mark.parametrize("budget", [float("inf"), float("nan")])
def test_nonfinite_budget_is_rejected(budget):
    with pytest.raises(ValueError, match="finite"):
        scan.scan_laptop(budget)


def test_laptop_source_details_explain_selection_and_limits():
    data = {"laptop": {"apps": [{"name": "App", "bytes": 123}], "logs": [], "storage_partial": False, "logs_partial": True,
                       "scope": {"roots_provided": 2, "folders_discovered": 40, "folders_measured": 40, "folders_complete": 40,
                                 "folder_limit": 30, "logs_checked": 0, "logs_skipped_limit": 5, "logs_skipped_large": 2, "budget_seconds": 20}}}
    from app.engine.coverage import laptop_sources
    rows = laptop_sources("scan.json", data)
    storage, logs = rows[:2]
    assert storage["status"] == "partial"  # Reported subset, even though all folder walks finished.
    assert "40 of 40" in storage["detail"] and "up to 30" in storage["detail"]
    assert "5 files over the file-count limit" in logs["detail"]
    assert "2 files over the size limit" in logs["detail"]


def test_malformed_scope_does_not_crash_parser_or_claim_missing_entries_checked(tmp_path):
    path = tmp_path / "scan.json"
    path.write_text(json.dumps({"laptop": {"apps": [None, {"name": "App", "bytes": 1}], "logs": [None],
                                          "scope": {"folders_measured": "bad", "log_max_bytes": [], "budget_seconds": "bad"}}}))
    result = pipeline.run([path])
    assert not result["errors"]
    storage = next(r for r in result["sourceCoverage"] if r["kind"] == "device_storage")
    assert storage["records"] == 1 and storage["status"] == "partial"
    logs = next(r for r in result["sourceCoverage"] if r["kind"] == "device_logs")
    assert logs["records"] == 0 and logs["status"] == "partial"


def test_chrome_each_database_is_explicitly_assessed_even_when_empty(tmp_path):
    with zipfile.ZipFile(ROOT / "samples" / "persona_chrome.zip") as archive:
        archive.extractall(tmp_path)
    profile = tmp_path / "Default"
    with sqlite3.connect(profile / "Login Data") as con:
        con.execute("DELETE FROM logins")
    result = pipeline.run([profile])
    rows = [r for r in result["sourceCoverage"] if r["platform"] == "chrome"]
    assert len(rows) == 4 and all(r["status"] == "scanned" for r in rows)
    login = next(r for r in rows if r["kind"] == "browser_logins")
    assert login["records"] == 0 and login["metadata_rows"] == 0
    replay = [r for r in result["records"] if r["meta"].get("source") == "session_replay"]
    assert replay and all("cookie associated with" in r["item"] for r in replay)


def test_locked_cookie_source_is_not_reported_as_zero_trackers(tmp_path, monkeypatch):
    with zipfile.ZipFile(ROOT / "samples" / "persona_chrome.zip") as archive:
        archive.extractall(tmp_path)
    query = chrome._query
    def locked(path, sql):
        if path.name == "Cookies":
            raise sqlite3.OperationalError("database is locked")
        return query(path, sql)
    monkeypatch.setattr(chrome, "_query", locked)
    result = pipeline.run([tmp_path / "Default"])
    row = next(r for r in result["sourceCoverage"] if r["kind"] == "browser_cookies")
    assert row["status"] == "unavailable"
    assert tracker_display(result) == "Not assessed"
    assert audit_is_partial(result)


def test_bad_preferences_do_not_discard_readable_history(tmp_path):
    with zipfile.ZipFile(ROOT / "samples" / "persona_chrome.zip") as archive:
        archive.extractall(tmp_path)
    profile = tmp_path / "Default"
    (profile / "Preferences").write_text("{broken")
    result = pipeline.run([profile])
    assert any(r["category"] == "activity" for r in result["records"])
    row = next(r for r in result["sourceCoverage"] if r["kind"] == "browser_permissions")
    assert row["status"] == "unavailable" and result["errors"]


def test_bad_ndjson_lines_are_visible_as_partial_coverage(tmp_path):
    path = tmp_path / "phone.ndjson"
    row = {"type": "access", "kind": "intervalBegin", "accessor": {"identifier": "app.example"}, "category": "camera"}
    path.write_text("bad line\n" + json.dumps(row) + "\n")
    result = pipeline.run([path])
    assert result["errors"] == []
    coverage = next(r for r in result["sourceCoverage"] if r["kind"] == "ios_report")
    assert coverage["status"] == "partial" and "1 bad lines skipped" in coverage["detail"]
    assert audit_is_partial(result)


def test_unavailable_input_is_not_marked_scanned(tmp_path):
    result = pipeline.run([tmp_path / "missing.zip"])
    assert result["sourceCoverage"][0]["status"] == "unavailable"
    assert audit_is_partial(result)


def test_missing_data_stays_unprovided_and_coverage_is_idempotent():
    result = {"records": [], "summary": {"sensitiveHits": 0}, "coverage": {}, "errors": [], "sourceCoverage": []}
    rows = coverage_rows(result)
    assert any(r["name"] == "Social interests" and r["status"] == "not_provided" for r in rows)
    result["sourceCoverage"] = rows
    assert coverage_rows(result) == rows
    assert chat_display(result) == "Not provided"


def test_partial_scan_with_no_errors_is_still_partial():
    result = {"errors": [], "sourceCoverage": [{"status": "partial", "kind": "device_storage"}]}
    assert audit_is_partial(result)
    result["sourceCoverage"][0]["status"] = "scanned"
    assert not audit_is_partial(result)


def test_partial_storage_display_is_a_rounded_down_lower_bound():
    result = {"summary": {"laptopDataBytes": 1_239_999_999}, "sourceCoverage": [{"kind": "device_storage", "status": "partial"}]}
    assert storage_display(result) == "1.23+"
    result["sourceCoverage"][0]["status"] = "scanned"
    assert storage_display(result) == "1.24"


def test_pdf_exports_coverage_without_fabricating_empty_chat_results():
    result = pipeline.run([ROOT / "samples" / "persona_device_scan.json"])
    result["sourceMode"] = "pc"
    assert chat_display(result) == "Not provided"
    pdf = report_bytes(result)
    assert pdf.startswith(b"%PDF-") and b"%%EOF" in pdf


def test_extended_mode_passes_120_seconds_to_background_scanner(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ui import main as ui
    jobs, budgets, completions = [], [], []
    class Widget:
        def configure(self, **kwargs):
            pass
        def get(self):
            return "Extended (120s)"
        def grid(self):
            pass
        def start(self):
            pass
    class Thread:
        def __init__(self, *, target, **kwargs):
            jobs.append(target)
        def start(self):
            pass
    def collect(*, max_seconds):
        budgets.append(max_seconds)
        return {"apps": [], "logs": [], "recent_files": 0}
    app = SimpleNamespace(loading=False, closing=False, resolve_button=Widget(), open_button=Widget(),
                          scan_button=Widget(), scan_mode=Widget(), status_label=Widget(), progress=Widget(),
                          show_errors=lambda message: None, dispatch=lambda *args: completions.append(args),
                          scan_complete=lambda *args: None, load_failed=lambda *args: None)
    monkeypatch.setattr(ui, "ROOT", tmp_path)
    monkeypatch.setattr(ui.threading, "Thread", Thread)
    monkeypatch.setattr(scan, "scan_laptop", collect)
    monkeypatch.setattr(chrome, "default_profiles", lambda: [])
    ui.NexDataApp.scan_laptop(app)
    assert app.loading and len(jobs) == 1 and budgets == []
    jobs[0]()
    assert budgets == [120]
    assert completions[0][0] == app.scan_complete
    assert json.loads((tmp_path / ".cache" / "device_scan.json").read_text())["laptop"]["recent_files"] == 0


def test_android_package_failures_are_reported_as_partial(monkeypatch):
    def adb(*args):
        if args == ("devices",):
            return "List of devices attached\nserial\tdevice\n"
        if "packages" in args:
            return "package:app.good\npackage:app.failed\n"
        if "app.failed" in args:
            raise RuntimeError("Package unavailable")
        if "dumpsys" in args:
            return "  runtime permissions:\n    android.permission.CAMERA: granted=true\n"
        return "CAMERA: allow"
    monkeypatch.setattr(scan, "_adb", adb)
    report = scan.scan_android()
    assert report["partial"] and report["packages_total"] == 2 and report["packages_scanned"] == 1
    assert report["errors"][0]["package"] == "app.failed"
    from app.engine.coverage import laptop_sources
    rows = laptop_sources("phone.json", {"android": report})
    assert rows[0]["status"] == "partial" and "1 package checks failed" in rows[0]["detail"]
