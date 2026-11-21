import pytest

import app.ui.main as ui


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(ui.NexDataApp, "scan_laptop", lambda self: None)  # no real scan in tests
    a = ui.NexDataApp()
    a.withdraw()
    a.calls = []
    a.resolve_browser_locks = lambda confirmed=False: a.calls.append(confirmed)
    yield a
    a.closing = True
    a.destroy()


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
