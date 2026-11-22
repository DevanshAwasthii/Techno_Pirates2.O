import shutil
import subprocess
import os
import sys

from app import pipeline
from app.image_exposure.service import ImageExposureStore, scan_exposure, merge_photo_result
from tests.test_image_exposure import photo


def test_pipeline_interests_photos_findings_and_pdf(tmp_path):
    from app.ui.main import report_bytes
    store = ImageExposureStore(tmp_path)
    store.add([photo(tmp_path / 'gps.jpg', True)])
    result = pipeline.run([], image_store=store)
    assert result['behavioral']['interests'] == []
    assert result['photos']['summary']['locationMetadata'] == 1
    ids = {r['id'] for r in result['records']}
    assert result['findings'] and all(set(f['evidence']) <= ids for f in result['findings'])
    if tool := shutil.which('pdftotext'):
        path = tmp_path / 'photos.pdf'
        path.write_bytes(report_bytes(result))
        text = subprocess.run([tool, str(path), '-'], capture_output=True, check=True).stdout.decode('utf-8')
        assert '1 of your photos contain GPS location' in text
        assert 'Photos' in text
    store.clear_images()
    cleared = merge_photo_result(result, scan_exposure(store))
    assert not cleared['records'] and not cleared['findings']
    assert result['records']  # previous view snapshot remains intact


def test_gui_local_tabs_render_with_disabled_ai_and_photo_evidence(tmp_path, monkeypatch):
    # A separate process avoids adding another Tk interpreter to the existing
    # suite's known intermittent Windows Tcl lifetime limitation.
    if os.environ.get('NEXDATA_GUI_CHILD') != '1':
        completed = subprocess.run([sys.executable, '-m', 'pytest', '-q',
            __file__ + '::test_gui_local_tabs_render_with_disabled_ai_and_photo_evidence'],
            env=dict(os.environ, NEXDATA_GUI_CHILD='1'), capture_output=True, text=True, timeout=45)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return
    from app.ui import main as ui
    monkeypatch.setattr(ui, 'ROOT', tmp_path)
    monkeypatch.setattr(ui, 'SETTINGS', tmp_path / 'settings.json')
    for name in ('scan_laptop', 'offer_recent_exports', 'poll_downloads'):
        monkeypatch.setattr(ui.NexDataApp, name, lambda self: None)
    app = ui.NexDataApp()
    app.withdraw()
    try:
        store = app.local_analysis.images
        store.add([photo(tmp_path / 'gps.jpg', True)])
        result = pipeline.run([], image_store=store)
        app.load_complete(result, ui.prepare_charts(result), 0)
        for name in ('Interests (AI optional)', 'Photos'):
            app.tabs.set(name)
            app.update_idletasks()
            assert app.tabs.tab(name).winfo_children()
        assert not app.local_analysis.config.enabled
        assert not app.auto_close_var.get()
        assert 'display error' not in app.error_label.cget('text').lower()
        details = ui.evidence_details(result['records'][0])
        assert any('12.5' in d for d in details)
    finally:
        app.closing = True
        app.clear_figures()
        app.destroy()
