import pytest

import app.ui.main as ui


@pytest.fixture(scope="module")
def shared_app():
    # One Tk root per module: creating/destroying many Tk roots in one process makes Tcl fail intermittently on Windows.
    mp = pytest.MonkeyPatch()
    mp.setattr(ui.NexDataApp, "scan_laptop", lambda self: None)  # no real scan in tests
    a = ui.NexDataApp()
    a.withdraw()
    yield a
    a.closing = True
    a.destroy()
    mp.undo()


@pytest.fixture
def app(shared_app, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "settings.json")
    a = shared_app
    a.calls = []
    a.auto_close_tried = False
    a.loading = False
    a.resolve_browser_locks = lambda confirmed=False: a.calls.append(confirmed)
    monkeypatch.setattr(a, "ask_auto_close", lambda: False, raising=False)
    return a


def test_settings_roundtrip_and_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "s.json")
    assert ui.load_settings() == {}
    ui.save_settings({"auto_close_browsers": True})
    assert ui.load_settings() == {"auto_close_browsers": True}
    (tmp_path / "s.json").write_text("{broken")
    assert ui.load_settings() == {}


def test_remembered_yes_closes_once_per_scan(app):
    ui.save_settings({"auto_close_browsers": True})
    app.maybe_auto_close()
    app.maybe_auto_close()  # same scan: must not loop
    assert app.calls == [True]
    app.manual_scan()  # new scan resets the guard
    app.maybe_auto_close()
    assert app.calls == [True, True]


def test_remembered_no_never_closes(app):
    ui.save_settings({"auto_close_browsers": False})
    app.maybe_auto_close()
    assert app.calls == []


def test_first_time_asks(app):
    asked = []
    app.ask_auto_close = lambda: asked.append(1) or False
    app.maybe_auto_close()
    assert asked == [1] and app.calls == []


def test_reopen_only_starts_real_browsers(tmp_path, monkeypatch):
    import subprocess
    from scanner import browser_access
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **k: started.append(args))
    fake = tmp_path / "chrome.exe"; fake.write_bytes(b"")
    other = tmp_path / "evil.exe"; other.write_bytes(b"")
    browser_access.reopen_browsers([str(fake), str(other), str(tmp_path / "msedge.exe")])  # last one missing
    assert started == [[str(fake), "--restore-last-session"]]


def test_imports_are_remembered_in_library(app, tmp_path):
    z = tmp_path / "instagram-x.zip"; z.write_bytes(b"PK")
    app.load_paths = lambda paths, *a: None
    app.import_exports([z])
    assert str(z) in ui.load_settings()["library"]
