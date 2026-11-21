from types import SimpleNamespace
from app.ui import main as ui


def test_browser_settings_action_copies_with_feedback(monkeypatch):
    opened, clipboard, labels = [], [], []
    class Button:
        def __init__(self, parent, **kw): self.kw = kw
        def pack(self, **kw): pass
        def configure(self, **kw): self.kw.update(kw)
    monkeypatch.setattr(ui.ctk, "CTkButton", Button)
    monkeypatch.setattr(ui.webbrowser, "open", lambda url: opened.append(url))
    app = SimpleNamespace(label=lambda *a, **kw: labels.append(a[1]), clipboard_clear=lambda: clipboard.clear(),
                          clipboard_append=clipboard.append, show_errors=lambda text: None)
    app.copy_link = lambda url, button: ui.NexDataApp.copy_link(app, url, button)
    app.open_link = lambda url: ui.NexDataApp.open_link(app, url)
    for url in ("chrome://settings/privacy", "chrome://settings/adPrivacy", "chrome://settings/content"):
        button = ui.NexDataApp.action_link(app, None, url)
        assert button.kw["text"] == "Copy link"
        button.kw["command"]()
        assert clipboard == [url] and "Copied link" in button.kw["text"]
    assert not opened and any("edge://settings" in text for text in labels)
    button = ui.NexDataApp.action_link(app, None, "https://example.test")
    button.kw["command"]()
    assert opened == ["https://example.test"]
