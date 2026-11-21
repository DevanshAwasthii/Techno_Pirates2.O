import re
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from app import pipeline
from app.cancellation import Cancelled, cancellation
from app.engine import messages
from app.engine.records import Record
from app.parsers import spotify, instagram, chrome, whatsapp, mbox, iosPrivacy, ocr, google_access, instagram_html
from app.ui import main as ui

ROOT = Path(__file__).resolve().parents[1]


def test_cancel_at_parse_progress_does_not_parse_file():
    event = threading.Event()
    with pytest.raises(Cancelled):
        pipeline.run([ROOT / "samples/persona_spotify.zip"], progress=lambda *a: event.set(), cancel=event)


@pytest.mark.parametrize("module,filename", [(spotify, "persona_spotify.zip"), (instagram, "persona_instagram.zip"),
                                             (chrome, "persona_chrome.zip"), (mbox, "persona_gmail.mbox"),
                                             (iosPrivacy, "persona_ios_privacy.ndjson")])
def test_cancel_inside_long_parser(module, filename, monkeypatch):
    path = ROOT / "samples" / filename
    assert path.is_file(), filename
    event, made = threading.Event(), []
    def record(*a, **kw):
        made.append(1)
        event.set()
        return Record(*a, **kw)
    monkeypatch.setattr(module, "Record", record)
    with pytest.raises(Cancelled):
        pipeline.run([path], cancel=event)
    assert len(made) == 1


def test_cancel_inside_whatsapp_and_ocr(tmp_path, monkeypatch):
    event = threading.Event()
    original = whatsapp._ts
    def stamp(*a):
        event.set()
        return original(*a)
    monkeypatch.setattr(whatsapp, "_ts", stamp)
    with cancellation(None):
        with pytest.raises(Cancelled), cancellation(event):
            whatsapp.parse_text("01/10/26, 9:00 pm - A: hi\n01/10/26, 9:01 pm - B: hello", "synthetic.txt")
    event.clear()
    monkeypatch.setattr(ocr, "frames", lambda p: [(0, None), (1, None)])
    monkeypatch.setattr(ocr, "read_lines", lambda f: event.set() or ["Viewed by 1", "Contact", "Today"])
    with pytest.raises(Cancelled), cancellation(event):
        ocr.parse(tmp_path / "synthetic.mp4")


def test_overlap_resolution_has_linear_comparison_budget(monkeypatch):
    comparisons = [0]
    class Position(int):
        def __lt__(self, other):
            comparisons[0] += 1
            return int(self) < other
        def __le__(self, other):
            comparisons[0] += 1
            return int(self) <= other
    class Match:
        def __init__(self, start, end): self.bounds = Position(start), Position(end)
        def span(self): return self.bounds
        def start(self): return self.bounds[0]
        def end(self): return self.bounds[1]
    class Pattern:
        def __init__(self, offset): self.offset = offset
        def finditer(self, text): return (Match(4*i+self.offset, 4*i+self.offset+1) for i in range(2000))
    monkeypatch.setattr(messages, "PATTERNS", {"first": Pattern(0), "second": Pattern(2), "overlap": Pattern(0)})
    assert messages.scan_text("synthetic") == ["first"] * 2000 + ["second"] * 2000
    assert comparisons[0] < 50 * 6000


def test_span_resolution_retains_priority_and_occurrences():
    text = "4111 1111 1111 1111; 4521 8890 1234; 9876543210; a@example.test; password abcd"
    assert messages.scan_text(text) == ["Card number", "Aadhaar number", "Phone number", "Email address", "OTP / password"]


class Widget:
    def __init__(self, exists=True): self.options, self.exists = {}, exists
    def configure(self, **kw): self.options.update(kw)
    def winfo_exists(self): return self.exists
    def grid(self): pass
    def grid_remove(self): pass
    def start(self): pass
    def stop(self): pass


def test_cancel_button_signals_pipeline_and_finishes_without_replacing_result(tmp_path, monkeypatch):
    jobs, callbacks = [], []
    class Thread:
        def __init__(self, *, target, **kw): jobs.append(target)
        def start(self): pass
    monkeypatch.setattr(ui.threading, "Thread", Thread)
    app = SimpleNamespace(loading=False, closing=False, result={"previous": True},
                          source_label=Widget(), scan_mode=Widget(), resolve_button=Widget(), scan_button=Widget(),
                          open_button=Widget(), cancel_button=Widget(), status_label=Widget(), progress=Widget(),
                          show_errors=lambda text: None, dispatch=lambda *a: callbacks.append(a),
                          load_cancelled=lambda: None, load_failed=lambda *a: None)
    ui.NexDataApp.load_paths(app, [tmp_path / "synthetic.zip"])
    ui.NexDataApp.cancel_audit(app)
    assert app.cancel_event.is_set() and app.cancel_button.options["state"] == "disabled"
    jobs[0]()
    assert callbacks == [(app.load_cancelled,)]
    app.restore_browsers = lambda: None
    app.finish_loading = lambda: ui.NexDataApp.finish_loading(app)
    ui.NexDataApp.load_cancelled(app)
    assert not app.loading and app.result == {"previous": True}


def test_pdf_completion_ignores_destroyed_widgets_stale_jobs_and_views():
    app = SimpleNamespace(closing=False, pdf_job_id=2, view_generation=3)
    for job, view in ((1, 3), (2, 2)):
        widgets = Widget(), Widget()
        ui.NexDataApp.export_complete(app, "old", job, view, widgets)
        assert not any(w.options for w in widgets)
    dead = Widget(False), Widget(False)
    ui.NexDataApp.export_complete(app, "gone", 2, 3, dead)
    assert not any(w.options for w in dead)
    live = Widget(), Widget()
    ui.NexDataApp.export_complete(app, "saved", 2, 3, live)
    assert live[0].options == {"state": "normal"} and live[1].options == {"text": "saved"}


def test_evidence_next_prev_exposes_every_record_in_fifty_record_pages(monkeypatch):
    widgets, shown = [], []
    class FakeWidget:
        def __init__(self, parent=None, **kw):
            self.kw, self.children, self.parent = kw, [], parent
            self._parent_canvas = SimpleNamespace(yview_moveto=lambda p: None)
            if isinstance(parent, FakeWidget): parent.children.append(self)
            widgets.append(self)
        def pack(self, **kw): pass
        def configure(self, **kw): self.kw.update(kw)
        def winfo_children(self): return list(self.children)
        def destroy(self):
            if self in self.parent.children: self.parent.children.remove(self)
        def title(self, *a): pass
        def geometry(self, *a): pass
        def transient(self, *a): pass
        def after(self, *a): pass
        def lift(self): pass
    for name in ("CTkToplevel", "CTkFrame", "CTkScrollableFrame", "CTkButton", "CTkLabel"):
        monkeypatch.setattr(ui.ctk, name, FakeWidget)
    def label(parent, text, **kw):
        if text.startswith("Record "): shown.append(text)
    app = SimpleNamespace(label=label, card=lambda body: FakeWidget(body),
                          records_by_id={str(i): {"item": f"Record {i}"} for i in range(123)})
    ui.NexDataApp.show_evidence(app, {"evidence": list(app.records_by_id)})
    prev = next(w for w in widgets if w.kw.get("text") == "Prev")
    nxt = next(w for w in widgets if w.kw.get("text") == "Next")
    assert len(shown) == 50 and prev.kw["state"] == "disabled"
    nxt.kw["command"]()
    assert len(shown) == 100
    nxt.kw["command"]()
    assert len(shown) == 123 and nxt.kw["state"] == "disabled"
    prev.kw["command"]()
    assert shown[-50:] == [f"Record {i}" for i in range(50, 100)]
    assert max(len(w.children) for w in widgets) <= 50


def test_google_csv_loop_and_html_feed_cancel_internally(tmp_path, monkeypatch):
    import zipfile
    event, rows = threading.Event(), []
    def stream(zf, name):
        for i in range(1000):
            rows.append(i)
            if i == 1: event.set()
            yield {}
    monkeypatch.setattr(google_access, "_rows", stream)
    class Archive:
        def namelist(self): return ["Access Log Activity/Devices - synthetic.csv"]
    with pytest.raises(Cancelled), cancellation(event):
        google_access.parse(Archive())
    assert len(rows) == 2
    event.clear()
    original = instagram_html._Boxes.handle_data
    def handle(self, text):
        event.set()
        original(self, text)
    monkeypatch.setattr(instagram_html._Boxes, "handle_data", handle)
    with pytest.raises(Cancelled), cancellation(event):
        instagram_html.boxes("<div>synthetic</div>" * 1000)
