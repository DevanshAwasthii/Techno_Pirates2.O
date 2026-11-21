from types import SimpleNamespace
import app.ui.main as ui


def test_old_undisclosed_consent_requires_new_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "settings.json")
    ui.save_settings({"auto_close_browsers": True})
    calls = []
    app = SimpleNamespace(auto_close_tried=False, loading=False, closing=False,
                          ask_auto_close=lambda: calls.append("disclosure") or False,
                          resolve_browser_locks=lambda **kw: calls.append("close"))
    ui.NexDataApp.maybe_auto_close(app)
    assert calls == ["disclosure"]


def test_dialog_discloses_stop_before_remembering(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "settings.json")
    labels, buttons = [], {}
    class Widget:
        def __init__(self, *a, **kw):
            labels.append(kw.get("text", ""))
            if "command" in kw:
                buttons[kw["text"]] = kw["command"]
        def __getattr__(self, name):
            return lambda *a, **kw: None
    class Var:
        def __init__(self, value): self.value = value
        def get(self): return self.value
        def set(self, value): self.value = value
    for name in ("CTkToplevel", "CTkLabel", "CTkCheckBox", "CTkFrame", "CTkButton"):
        monkeypatch.setattr(ui.ctk, name, Widget)
    monkeypatch.setattr(ui.ctk, "BooleanVar", Var)
    def accept(win):
        assert "auto_close_browsers" not in ui.load_settings()
        assert any("If normal close fails" in t and "stop verified background browser processes" in t and "interrupt downloads" in t for t in labels)
        buttons["Close browsers and scan"]()
    app = SimpleNamespace(wait_window=accept, auto_close_var=Var(False))
    assert ui.NexDataApp.ask_auto_close(app) is True
    assert ui.load_settings() == {"auto_close_browsers": True, "browser_close_consent_version": 1}


def test_enabling_checkbox_uses_disclosure():
    calls = []
    var = SimpleNamespace(get=lambda: True, set=lambda value: calls.append(value))
    app = SimpleNamespace(auto_close_var=var, ask_auto_close=lambda: calls.append("disclosure") or False)
    ui.NexDataApp.toggle_auto_close(app)
    assert calls == ["disclosure", False]
