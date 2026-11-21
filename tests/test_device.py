"""Layer 5 parser, scanner, rule and compatibility checks."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import pipeline
from app.engine.records import Record, ParseError
from app.engine.rules import build_findings
from app.parsers import deviceScan, iosPrivacy
from scanner import scan

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / "samples" / "persona_device_scan.json"
IOS = ROOT / "samples" / "persona_ios_privacy.ndjson"
NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def result():
    return pipeline.run([DEVICE, IOS])


def test_device_report_records_and_coverage():
    records, coverage = deviceScan.parse(DEVICE)
    assert set(coverage) == {"device", "android"}
    assert {r.platform for r in records} == {"device", "android"}
    assert all(r.category in {"device", "location"} for r in records)
    assert sum(r.meta.get("bytes", 0) for r in records) == 4_800_000_000
    assert sum(r.meta.get("recent_files", 0) for r in records) == 27
    assert len([r for r in records if r.meta.get("source") == "android_permissions"]) == 3
    assert all(r.sourceFile and r.recordRef for r in records)


def test_ios_report_records_and_interval_ends():
    records, coverage, stats = iosPrivacy.parse(IOS)
    assert stats == {"bad_lines": 0, "ignored_lines": 6}
    assert len(records) == 12  # Seven access beginnings and five network events.
    assert sum(r.meta.get("source") == "ios_network" for r in records) == 5
    assert coverage["location"] == coverage["contact"] == "found"
    assert all(r.platform == "ios" and r.recordRef.startswith("line ") for r in records)


def test_four_findings_and_summary_counts(result):
    assert result["errors"] == []
    records = [Record(**r) for r in result["records"]]
    findings, summary = build_findings(records, now=NOW)
    assert {f.title for f in findings} == {
        "4 apps accessed your location in the last 7 days",
        "3 apps send data to session-recording or tracking services",
        "3 apps hold 4.80 GB of your data on this laptop",
        "2 log files contain your email or IP address",
    }
    assert summary["recentLocationApps"] == 4
    assert summary["mobileTrackingApps"] == 3
    assert summary["laptopDataApps"] == 3
    assert summary["laptopDataBytes"] == 4_800_000_000
    assert summary["logsWithIdentifiers"] == 2
    by_id = {r.id: r for r in records}
    for finding in findings:
        assert finding.layer == 5 and finding.evidence
        assert set(finding.evidence) <= by_id.keys()
        assert finding.action["steps"]
    location = next(f for f in findings if "last 7 days" in f.title)
    assert set(location.platforms) == {"ios", "android"}


def test_existing_findings_unchanged_by_new_records(result):
    mock = json.loads((ROOT / "mock" / "findings.json").read_text(encoding="utf-8"))
    old_records = [Record(**r) for r in mock["records"] if r["platform"] not in {"device", "ios", "android"}]
    before, old_summary = build_findings(old_records, now=NOW)
    after, summary = build_findings(old_records + [Record(**r) for r in result["records"]], now=NOW)
    after_by_title = {f.title: asdict(f) for f in after}
    assert len(before) >= 21  # baseline grows as non-device findings are added; device records must not alter them
    for finding in before:
        assert asdict(finding) == after_by_title[finding.title]
    for key in ("servicesFound", "trackersFound", "sessionRecorders", "topPeople", "sensitiveHits"):
        assert summary[key] == old_summary[key]


def test_unique_device_ids_and_original_app_references(tmp_path):
    data = {"laptop": {"apps": [{"name": "Small", "bytes": 1}, {"name": "Large", "bytes": 100}]}}
    first, second = tmp_path / "one.json", tmp_path / "two.json"
    first.write_text(json.dumps(data))
    second.write_text(json.dumps(data))
    a, _ = deviceScan.parse(first)
    b, _ = deviceScan.parse(second)
    assert not {r.id for r in a} & {r.id for r in b}
    assert a[0].meta["app"] == "Large" and a[0].recordRef.startswith("laptop.apps[1]")


def test_device_content_detection_with_unusual_extension(tmp_path):
    path = tmp_path / "scan.export"
    path.write_bytes(DEVICE.read_bytes())
    parsed = pipeline.run([path])
    assert parsed["errors"] == []
    assert set(parsed["coverage"]) == {"device", "android"}


@pytest.mark.parametrize("text", ['{"other": 1}', '{broken', '{"laptop": null, "android": null}'])
def test_unrecognised_json_is_wrong_format(tmp_path, text):
    path = tmp_path / "invalid.json"
    path.write_text(text)
    assert pipeline.run([path])["errors"][0]["code"] == "wrong_format"


def test_malformed_device_entries_are_ignored(tmp_path):
    path = tmp_path / "tolerant.json"
    path.write_text(json.dumps({"laptop": {"apps": [None, {"name": "App", "bytes": "bad", "files": -1}], "logs": [None, {"emails": []}]},
                                "android": {"apps": [None, {"package": "example.app", "granted": [{}, "android.permission.CAMERA"], "last_access": []}]}}))
    records, _ = deviceScan.parse(path)
    assert next(r for r in records if r.meta.get("source") == "laptop_store").meta["bytes"] == 0
    assert any(r.meta.get("permissions") == ["camera"] for r in records)


def test_bad_ndjson_lines_skipped_and_counted(tmp_path):
    valid = {"type": "access", "accessor": {"identifier": "app.good"}, "category": "location", "kind": "intervalBegin", "timeStamp": NOW.isoformat()}
    rows = ["{bad", "[]", json.dumps({**valid, "accessor": None}), json.dumps({**valid, "category": []}),
            json.dumps({"type": "futureReportType"}), json.dumps({**valid, "kind": "intervalEnd"}), json.dumps(valid)]
    path = tmp_path / "privacy.ndjson"
    path.write_text("\n".join(rows))
    records, _, stats = iosPrivacy.parse(path)
    assert len(records) == 1 and records[0].recordRef == "line 7"
    assert stats == {"bad_lines": 4, "ignored_lines": 2}
    assert pipeline.run([path])["errors"] == []


def test_ndjson_without_recognised_events_is_wrong_format(tmp_path):
    path = tmp_path / "not_privacy.ndjson"
    path.write_text('{bad\n{"type":"unknown"}\n')
    with pytest.raises(ParseError) as error:
        iosPrivacy.parse(path)
    assert error.value.code == "wrong_format"
    assert pipeline.run([path])["errors"][0]["code"] == "wrong_format"


def test_location_window_boundaries_and_grants_are_not_access():
    records = []
    for i, stamp in enumerate((NOW, NOW - timedelta(days=7), NOW - timedelta(days=7, seconds=1), NOW + timedelta(seconds=1), None, "bad", "2026-11-21T00:00:00")):
        stamp = stamp.isoformat() if isinstance(stamp, datetime) else stamp
        records.append(Record(f"sensor-{i}", "android", "location", "Access", stamp,
                              meta={"source": "sensor_access", "app": f"app.{i}", "sensor": "location"}))
    records.append(Record("grant", "android", "device", "Allowed", NOW.isoformat(), meta={"source": "android_permissions", "app": "grant.only", "permissions": ["location"]}))
    findings, summary = build_findings(records, now=NOW)
    finding = next(f for f in findings if "last 7 days" in f.title)
    assert finding.metric["value"] == summary["recentLocationApps"] == 2
    assert set(finding.evidence) == {"sensor-0", "sensor-1"}


def test_tracker_subdomains_match_without_suffix_lookalikes(tmp_path):
    path = tmp_path / "net.ndjson"
    domains = ["api.google-analytics.com", "evilgoogle-analytics.com", "google-analytics.com.evil.test", "api.adjust.com"]
    path.write_text("\n".join(json.dumps({"type": "networkActivity", "bundleID": f"app.{i}", "domain": domain}) for i, domain in enumerate(domains)))
    records, _, _ = iosPrivacy.parse(path)
    findings, summary = build_findings(records, now=NOW)
    assert summary["mobileTrackingApps"] == 2
    assert set(findings[0].evidence) == {records[0].id, records[3].id}


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    roaming.mkdir()
    local.mkdir()
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return roaming, local


def test_laptop_metadata_log_counts_and_no_raw_values(appdata, monkeypatch):
    roaming, local = appdata
    app = local / "WhatsApp"
    app.mkdir()
    text = "riya@example.test RIYA@EXAMPLE.TEST 192.168.1.7 256.4.5.6 +91 98765 43210 9123456789\npassword=NEVER_EXPORT_THIS"
    log = app / "app.log"
    log.write_text(text)
    (app / "cache.db").write_bytes(b"NEVER_READ_CONTENTS" * 100)
    (app / "oversize.txt").write_bytes(b"x" * (scan.MAX_LOG_BYTES + 1))
    recent = roaming / "Microsoft" / "Windows" / "Recent"
    recent.mkdir(parents=True)
    (recent / "one.lnk").write_bytes(b"link")
    (recent / "two.LNK").write_bytes(b"link")
    (recent / "ignore.txt").write_bytes(b"nothing")
    original = Path.open
    def guarded_open(path, *args, **kwargs):
        assert path.suffix.lower() in {".txt", ".log"}, f"Unexpected content read: {path}"
        assert path.name != "oversize.txt"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    result = scan.scan_laptop()
    counts = next(row for row in result["logs"] if row["path"] == str(log))
    assert (counts["emails"], counts["ips"], counts["phones"]) == (2, 1, 2)
    assert result["recent_files"] == 2
    app_row = next(row for row in result["apps"] if row["name"] == "WhatsApp")
    assert app_row["bytes"] == sum(p.stat().st_size for p in app.iterdir())
    assert app_row["files"] == 3 and app_row["last_modified"]
    encoded = json.dumps(result)
    for secret in ("riya@example.test", "192.168.1.7", "98765 43210", "NEVER_EXPORT_THIS", "NEVER_READ_CONTENTS"):
        assert secret not in encoded


def test_laptop_keeps_thirty_largest_folders(appdata):
    roaming, _ = appdata
    for i in range(40):
        folder = roaming / f"App{i:02d}"
        folder.mkdir()
        (folder / "cache.bin").write_bytes(b"x" * (i + 1))
    result = scan.scan_laptop()
    assert len(result["apps"]) == 30
    assert [a["bytes"] for a in result["apps"]] == list(range(40, 10, -1))


def test_laptop_caps_log_count(appdata):
    roaming, _ = appdata
    folder = roaming / "Logs"
    folder.mkdir()
    for i in range(305):
        (folder / f"{i:03d}.log").write_text("x@example.test")
    result = scan.scan_laptop()
    assert len(result["logs"]) == 300
    assert all(log["emails"] == 1 for log in result["logs"])
    assert result["partial"]


def test_laptop_skips_permission_errors(appdata, monkeypatch):
    roaming, _ = appdata
    (roaming / "Locked").mkdir()
    original = scan.os.scandir
    def scandir(path):
        if Path(path).name == "Locked":
            raise PermissionError("denied")
        return original(path)
    monkeypatch.setattr(scan.os, "scandir", scandir)
    result = scan.scan_laptop()
    assert result["partial"] and result["logs"] == []


def test_laptop_zero_time_budget_returns_partial(appdata):
    result = scan.scan_laptop(max_seconds=0)
    assert result["partial"] and result["scan_seconds"] < 1


def test_scanner_is_importable_without_site_packages():
    completed = subprocess.run([sys.executable, "-S", "-c", "import scanner.scan"], cwd=ROOT, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr.decode()


def test_adb_missing_handled(monkeypatch, capsys):
    def missing(*args, **kwargs):
        raise FileNotFoundError("adb")
    monkeypatch.setattr(scan.subprocess, "run", missing)
    assert scan.scan_android() is None
    assert "adb was not found" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["unauthorised", "timeout", "failed"])
def test_adb_connection_errors_handled(monkeypatch, capsys, failure):
    def run(args, **kwargs):
        assert kwargs["timeout"] == scan.ADB_TIMEOUT
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if failure == "failed":
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout="List of devices attached\nserial\tunauthorized\n")
    monkeypatch.setattr(scan.subprocess, "run", run)
    assert scan.scan_android() is None
    assert {"unauthorised": "unauthorised", "timeout": "timed out", "failed": "command failed"}[failure] in capsys.readouterr().err


def test_android_commands_grants_and_access_parsing(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == scan.ADB_TIMEOUT and kwargs["check"]
        if args == ["adb", "devices"]:
            return SimpleNamespace(stdout="List of devices attached\nserial\tdevice\n")
        assert args[1:4] == ["-s", "serial", "shell"]
        if "packages" in args:
            return SimpleNamespace(stdout="package:in.swiggy.android\nignored rubbish\n")
        if "dumpsys" in args:
            return SimpleNamespace(stdout="  install permissions:\n    android.permission.READ_CONTACTS: granted=true\n  runtime permissions:\n    android.permission.ACCESS_FINE_LOCATION: granted=true, flags=[]\n    android.permission.CAMERA: granted=true\n    android.permission.RECORD_AUDIO: granted=false\n  other section:\n    android.permission.READ_CONTACTS: granted=true\n")
        assert args[-4:] == ["cmd", "appops", "get", "in.swiggy.android"]
        return SimpleNamespace(stdout="FINE_LOCATION: allow; time=-1h\nCAMERA: allow; time=2026-11-20T17:00:00+05:30\n")
    monkeypatch.setattr(scan.subprocess, "run", run)
    result = scan.scan_android()
    assert len(calls) == 4
    assert result["device"] == "serial"
    app = result["apps"][0]
    assert app["granted"] == ["android.permission.ACCESS_FINE_LOCATION", "android.permission.CAMERA"]
    assert app["last_access"]["location"] is not None
    assert app["last_access"]["camera"] == "2026-11-20T11:30:00+00:00"
    assert app["last_access"]["contacts"] is None


def test_appops_relative_times_rejections_and_multiline_access():
    output = """COARSE_LOCATION: allow; time=-1d
FINE_LOCATION: allow; time=+1h2m3s456ms ago; rejectTime=-1s
CAMERA (allow):
  Access: [top-s] 2026-11-21 10:00:00.000 (-2h)
  Reject: [top-s] 2026-11-21T11:00:00+00:00
RECORD_AUDIO: allow; rejectTime=-1h
READ_CONTACTS: allow; time=2026-11-20T15:30:00+05:30
READ_SMS: allow; time=-1s
"""
    access = scan.parse_appops(output, NOW)
    assert access == {"location": (NOW - timedelta(hours=1, minutes=2, seconds=3, milliseconds=456)).isoformat(),
                      "camera": "2026-11-21T10:00:00+00:00", "microphone": None, "contacts": "2026-11-20T10:00:00+00:00"}


def test_appops_invalid_dates_and_unrepresentable_durations():
    access = scan.parse_appops("CAMERA: allow; time=2026-99-99T00:00:00Z\nREAD_CONTACTS: allow; time=-999999999999999999999999d", NOW)
    assert access["camera"] is None and access["contacts"] is None
