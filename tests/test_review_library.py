from types import SimpleNamespace
from app.connect import file_key
from app.ui import main as ui


def test_remove_and_forget_all_update_library_imported_and_future_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "settings.json")
    a, b, scan = (tmp_path / name for name in ("synthetic-a.zip", "synthetic-b.zip", "scan.json"))
    for p in (a, b, scan): p.write_bytes(b"synthetic")
    ui.save_settings({"auto_close_browsers": False, "library": [str(a), str(b)], "imported": [file_key(a), file_key(b), "dismissed.zip|1|2"]})
    app = SimpleNamespace(loaded_paths=[str(scan), str(a), str(b)], pending_paths=[str(a), str(b)], auto_queue=[a, b], loading=False)
    ui.NexDataApp.forget_exports(app, [a])
    settings = ui.load_settings()
    assert settings["library"] == [str(b)] and file_key(a) not in settings["imported"]
    assert file_key(b) in settings["imported"] and "dismissed.zip|1|2" in settings["imported"]
    assert app.loaded_paths == [str(scan), str(b)] and app.pending_paths == [str(b)] and app.auto_queue == [b]
    ui.NexDataApp.forget_exports(app)
    assert ui.load_settings() == {"auto_close_browsers": False, "library": [], "imported": []}
    assert app.loaded_paths == [str(scan)] and not app.pending_paths and not app.auto_queue
    assert a.exists() and b.exists()


def test_removal_cancels_busy_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "settings.json")
    path = tmp_path / "synthetic.zip"
    ui.save_settings({"library": [str(path)]})
    calls = []
    app = SimpleNamespace(loaded_paths=[], pending_paths=[str(path)], auto_queue=[], loading=True, cancel_audit=lambda: calls.append("cancel"))
    ui.NexDataApp.forget_exports(app, [path])
    assert calls == ["cancel"] and not app.pending_paths


def test_remembered_exports_list_has_working_remove_and_forget_buttons(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "SETTINGS", tmp_path / "settings.json")
    paths = [str(tmp_path / "synthetic-a.zip"), str(tmp_path / "synthetic-b.zip")]
    ui.save_settings({"library": paths, "imported": ["synthetic-a.zip|1|2", "synthetic-b.zip|1|2"]})
    buttons, labels = [], []
    class Widget:
        def __init__(self, parent=None, **kw):
            self.parent, self.children, self.kw = parent, [], kw
            if parent: parent.children.append(self)
            if "command" in kw: buttons.append(self)
        def pack(self, **kw): pass
        def winfo_children(self): return list(self.children)
        def destroy(self):
            if self in self.parent.children: self.parent.children.remove(self)
    monkeypatch.setattr(ui.ctk, "CTkButton", Widget)
    app = SimpleNamespace(label=lambda parent, text, **kw: labels.append(text), card=Widget,
                          loaded_paths=paths.copy(), pending_paths=[], auto_queue=[], loading=False)
    app.forget_exports = lambda paths=None: ui.NexDataApp.forget_exports(app, paths)
    app.render_library = lambda body: ui.NexDataApp.render_library(app, body)
    body = Widget()
    app.render_library(body)
    assert "Remembered exports" in labels
    next(b for b in buttons if b.kw["text"] == "Remove").kw["command"]()
    assert ui.load_settings()["library"] == paths[1:]
    next(b for b in buttons if b.kw["text"] == "Forget all").kw["command"]()
    assert ui.load_settings()["library"] == [] and ui.load_settings()["imported"] == []
    assert "No remembered exports." in labels
