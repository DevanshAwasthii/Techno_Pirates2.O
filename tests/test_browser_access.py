"""Browser locks, safe exit requests, cancellation and closed-profile scans."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app import pipeline
from app.parsers import chrome
from app.ui import main as ui
from scanner import browser_access as access

BROWSER = {"pid": 123, "executable": "chrome.exe", "started": 456}


def test_diagnosis_identifies_browser_lock_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(access, "file_users", lambda path: [BROWSER])
    result = access.describe_failure(tmp_path / "History", sqlite3.OperationalError("database is locked"))
    assert result["reason"] == "browser_running"
    assert result["blocked_by"] == [BROWSER]
    assert "PID 123" in result["message"]
    assert "windows are closed" in result["message"]


def test_unidentified_lock_stays_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr(access, "file_users", lambda path: [])
    result = access.describe_failure(tmp_path / "History", sqlite3.OperationalError("database is locked"))
    assert result["reason"] == "file_locked"
    assert result["blocked_by"] == []
    assert "did not identify" in result["message"]


def test_failed_diagnostics_do_not_hide_read_error(monkeypatch, tmp_path):
    def unavailable(path):
        raise OSError("diagnostics unavailable")
    monkeypatch.setattr(access, "file_users", unavailable)
    result = access.describe_failure(tmp_path / "Cookies", PermissionError("access denied"))
    assert result["reason"] == "source_unavailable"
    assert result["blocked_by"] == [] and "access denied" in result["message"]


def test_schema_failure_is_not_misdiagnosed_as_browser_lock(monkeypatch, tmp_path):
    def unexpected(path):
        pytest.fail("A schema error is not a file-lock diagnosis")
    monkeypatch.setattr(access, "file_users", unexpected)
    result = access.describe_failure(tmp_path / "History", sqlite3.OperationalError("no such table: downloads"))
    assert result["reason"] == "source_unavailable" and not result["blocked_by"]


def test_reused_pid_is_never_closed(monkeypatch):
    monkeypatch.setattr(access, "_process_identity", lambda pid: {**BROWSER, "started": 999})
    monkeypatch.setattr(access, "_apis", lambda: pytest.fail("Must reject a reused PID before shutdown"))
    with pytest.raises(RuntimeError, match="changed"):
        access.close_browsers([BROWSER])


def test_non_browser_is_never_closed(monkeypatch):
    other = {**BROWSER, "executable": "python.exe"}
    monkeypatch.setattr(access, "_process_identity", lambda pid: other)
    monkeypatch.setattr(access, "_apis", lambda: pytest.fail("Must reject non-browser processes"))
    with pytest.raises(RuntimeError, match="changed"):
        access.close_browsers([other])


def test_already_closed_browser_needs_no_shutdown(monkeypatch):
    monkeypatch.setattr(access, "_process_identity", lambda pid: None)
    monkeypatch.setattr(access, "_apis", lambda: pytest.fail("An exited process needs no shutdown"))
    access.close_browsers([BROWSER])


def fake_shutdown(monkeypatch, *, result=0, exits=True):
    calls = []
    class RestartManager:
        def RmRegisterResources(self, session, count_files, files, count_apps, apps, count_services, services):
            assert count_files == count_services == 0 and files is None and services is None
            assert count_apps == 1 and apps[0].pid == BROWSER["pid"]
            assert apps[0].started.dwLowDateTime == BROWSER["started"]
            calls.append("register")
            return 0
        def RmShutdown(self, session, flags, callback):
            assert flags == 0 and callback is None  # A force flag is never acceptable.
            calls.append("normal_exit")
            return result
    @contextmanager
    def session(rm):
        yield 7
    rm = RestartManager()
    monkeypatch.setattr(access, "_apis", lambda: (rm, None))
    monkeypatch.setattr(access, "_session", session)
    monkeypatch.setattr(access, "_process_identity", lambda pid: None if exits and "normal_exit" in calls else BROWSER)
    return calls


def test_shutdown_requests_only_verified_browser_without_force(monkeypatch):
    calls = fake_shutdown(monkeypatch)
    access.close_browsers([BROWSER, BROWSER])
    assert calls == ["register", "normal_exit"]


def test_refused_shutdown_is_not_reported_as_success(monkeypatch):
    calls = fake_shutdown(monkeypatch, result=351, exits=False)
    with pytest.raises(OSError, match="did not exit normally"):
        access.close_browsers([BROWSER])
    assert calls == ["register", "normal_exit"]


def test_remaining_browser_is_not_force_killed(monkeypatch):
    calls = fake_shutdown(monkeypatch, exits=False)
    moments = iter((0, 11))
    monkeypatch.setattr(access.time, "monotonic", lambda: next(moments))
    with pytest.raises(RuntimeError, match="not force-closed"):
        access.close_browsers([BROWSER])
    assert calls == ["register", "normal_exit"]


def test_cancel_does_not_start_shutdown(monkeypatch):
    app = SimpleNamespace(loading=False, closing=False, result={"errors": [{"blocked_by": [BROWSER]}]})
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *args, **kwargs: False)
    monkeypatch.setattr(ui.threading, "Thread", lambda **kwargs: pytest.fail("Cancellation must not launch shutdown"))
    ui.NexDataApp.resolve_browser_locks(app)


def test_empty_closed_profile_is_successfully_assessed(tmp_path):
    profile = tmp_path / "Default"
    profile.mkdir()
    with sqlite3.connect(profile / "History") as con:
        con.execute("CREATE TABLE urls(url TEXT, visit_count INTEGER, last_visit_time INTEGER)")
        con.execute("CREATE TABLE downloads(target_path TEXT, tab_url TEXT, start_time INTEGER)")
    result = pipeline.run([profile])
    assert result["errors"] == []
    assert result["records"] == []
    assert result["coverage"]["chrome"]["activity"] == "not_found"


def test_other_profile_warning_does_not_mark_readable_history_unknown(tmp_path):
    with sqlite3.connect(tmp_path / "History") as con:
        con.execute("CREATE TABLE urls(url TEXT, visit_count INTEGER, last_visit_time INTEGER)")
        con.execute("CREATE TABLE downloads(target_path TEXT, tab_url TEXT, start_time INTEGER)")
    warnings = [{"file": "another profile", "message": "unavailable"}]
    _, coverage = chrome.parse(tmp_path, warnings=warnings)
    assert coverage["activity"] == "not_found"


def test_browser_error_display_is_concise_and_preserves_provenance():
    error = {"file": r"C:\Profile\Network\Cookies", "code": "unknown", "reason": "browser_running", "message": "Chrome PID 123 holds this file"}
    assert ui.error_text([error]) == "Cookies: Chrome PID 123 holds this file"
    assert error["file"] == r"C:\Profile\Network\Cookies"


def test_background_stop_requires_explicit_opt_in(monkeypatch):
    fake_shutdown(monkeypatch, result=351, exits=False)
    monkeypatch.setattr(access, "_stop_background", lambda targets: pytest.fail("No implicit process stop"))
    with pytest.raises(OSError):
        access.close_browsers([BROWSER])


def test_explicit_background_fallback_only_after_refused_normal_exit(monkeypatch):
    calls = fake_shutdown(monkeypatch, result=351, exits=False)
    monkeypatch.setattr(access, "has_visible_windows", lambda pid: False)
    def stop(targets):
        assert calls == ["register", "normal_exit"]
        assert targets == [BROWSER]
        calls.append("explicit_background_stop")
        monkeypatch.setattr(access, "_process_identity", lambda pid: None)
    monkeypatch.setattr(access, "_stop_background", stop)
    access.close_browsers([BROWSER], allow_background_stop=True)
    assert calls[-1] == "explicit_background_stop"


def test_visible_browser_window_blocks_background_shutdown(monkeypatch):
    monkeypatch.setattr(access, "_process_identity", lambda pid: BROWSER)
    monkeypatch.setattr(access, "has_visible_windows", lambda pid: True)
    monkeypatch.setattr(access, "_apis", lambda: pytest.fail("Must not stop a visible browser"))
    with pytest.raises(RuntimeError, match="visible"):
        access.close_browsers([BROWSER], allow_background_stop=True)


def test_other_shutdown_errors_never_trigger_background_stop(monkeypatch):
    fake_shutdown(monkeypatch, result=350, exits=False)
    monkeypatch.setattr(access, "has_visible_windows", lambda pid: False)
    monkeypatch.setattr(access, "_stop_background", lambda targets: pytest.fail("Do not force through unrelated Windows failures"))
    with pytest.raises(OSError):
        access.close_browsers([BROWSER], allow_background_stop=True)


def test_background_stop_rechecks_handle_identity_before_termination(monkeypatch):
    class Kernel:
        def OpenProcess(self, rights, inherit, pid):
            return 99
        def TerminateProcess(self, handle, code):
            pytest.fail("A reused PID must never be stopped")
        def CloseHandle(self, handle):
            assert handle == 99
    monkeypatch.setattr(access, "has_visible_windows", lambda pid: False)
    monkeypatch.setattr(access, "_apis", lambda: (None, Kernel()))
    monkeypatch.setattr(access, "_identity_from_handle", lambda *args: {**BROWSER, "started": 999})
    with pytest.raises(RuntimeError, match="identity changed"):
        access._stop_background([BROWSER])
