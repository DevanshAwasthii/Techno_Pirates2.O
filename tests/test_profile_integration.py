import json
import shutil
import subprocess
import zipfile

import pytest

from matplotlib.figure import Figure

from app import pipeline
from app.ui.main import report_bytes, TAB_NAMES
from app.ui.profile_views import plot_places, evidence_details
from tests.test_instagram_activity import box


def test_activity_only_pipeline_profile_evidence_and_pdf(tmp_path):
    path = tmp_path / 'synthetic_activity.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('story_interactions/stories_viewed.html', box(Username='fictional_friend', Caption='Cycling #Jaipur', Time='Nov 1, 2026 9:00 pm'))
        z.writestr('your_ads/see_less_topics.html', box(Name='Cars'))
    result = pipeline.run([path])
    assert not result['errors']
    assert len(result['connections']) == 1
    assert result['places'][0]['name'] == 'Jaipur'
    assert result['profile']['interests'][0]['label'] == 'Cycling'
    assert result['extras']['data_age']
    assert {'Profile', 'Connections & places'} <= set(TAB_NAMES)
    ids = {r['id'] for r in result['records']}

    def check(value):
        if isinstance(value, dict):
            if 'evidence' in value:
                assert set(value['evidence']) <= ids
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(result)
    assert json.loads(json.dumps(result))['profile']['interests']
    report = report_bytes(result)
    assert report.startswith(b'%PDF') and b'%%EOF' in report
    (tmp_path / 'synthetic_profile.pdf').write_bytes(report)
    tool = shutil.which('pdftotext')
    if not tool:
        pytest.skip('pdftotext unavailable; PDF format already checked')
    text = subprocess.run([tool, str(tmp_path / 'synthetic_profile.pdf'), '-'], capture_output=True, check=True).stdout.decode('utf-8')
    for expected in ('Your profile as the algorithms see it', 'Cycling', 'Connections and places', 'Jaipur', 'Data age', 'Illustrative ad-targeting preview'):
        assert expected in text


def test_mixed_base_activity_and_unrelated_json(tmp_path):
    path = tmp_path / 'synthetic_mixed.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('connections/followers_and_following/followers_1.html', '<div class="_a6-g"><h2>fictional_friend</h2></div>')
        z.writestr('media/posts.html', box(Caption='Cycling #Jaipur', Latitude='26.9124', Longitude='75.7873'))
        z.writestr('misc.json', '{}')
    result = pipeline.run([path])
    assert not result['errors'] and len(result['records']) == 2
    assert result['coverage']['instagram']['activity'] == 'found'
    assert len({r['id'] for r in result['records']}) == 2


def test_bad_supplemental_page_keeps_base_records_and_marks_partial(tmp_path, monkeypatch):
    from app.parsers import instagram_activity
    monkeypatch.setattr(instagram_activity, 'MAX_MEMBER_BYTES', 20)
    path = tmp_path / 'synthetic_partial.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('connections/followers_and_following/followers_1.html', '<div class="_a6-g"><h2>fictional_friend</h2></div>')
        z.writestr('media/posts.html', box(Caption='x' * 100))
    result = pipeline.run([path])
    assert len(result['records']) == 1
    assert any(error['code'] == 'too_large' for error in result['errors'])
    assert result['sourceCoverage'][0]['status'] == 'partial'


def test_corrupt_supplemental_member_preserves_base_and_other_activity(tmp_path):
    path = tmp_path / 'synthetic_crc.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as z:
        z.writestr('connections/followers_and_following/followers_1.html', '<div class="_a6-g"><h2>fictional_friend</h2></div>')
        z.writestr('media/posts.html', box(Caption='crc-failure-sentinel'))
        z.writestr('story_interactions/stories_viewed.html', box(Username='fictional_friend', Caption='Cycling'))
    damaged = bytearray(path.read_bytes())
    damaged[damaged.index(b'crc-failure-sentinel')] ^= 1
    path.write_bytes(damaged)
    result = pipeline.run([path])
    assert len(result['records']) == 2
    assert any(record['meta'].get('action') == 'story_view' for record in result['records'])
    assert any(error['code'] == 'corrupt_zip' for error in result['errors'])
    assert result['sourceCoverage'][0]['status'] == 'partial'


def test_malformed_advertiser_label_cannot_abort_profile_audit(tmp_path):
    path = tmp_path / 'synthetic_label.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr("instagram_ads_and_businesses/information_you've_submitted_to_advertisers.html",
                   box(Advertiser='https://[broken', Email='fake@example.invalid'))
    result = pipeline.run([path])
    assert not result['errors'] and len(result['records']) == 1
    assert result['profile']['shopping'][0]['evidence'] == [result['records'][0]['id']]


def test_scatter_groups_evidence_offline():
    places = [{'id': 'city:synthetic', 'name': 'Fictional city', 'lat': 10, 'lon': 20, 'evidence': ['a']},
              {'id': 'city:synthetic', 'name': 'Fictional city', 'lat': 10, 'lon': 20, 'evidence': ['b']}]
    fig = Figure()
    dots, values = plot_places(fig.add_subplot(), places)
    assert len(values) == 1 and values[0]['evidence'] == ['a', 'b']
    assert len(dots.get_offsets()) == 1
    assert places[0]['evidence'] == ['a']


def test_new_inference_evidence_exposes_supporting_values_with_bounds():
    values = evidence_details({'meta': {'person': 'fictional_friend', 'caption': 'Cycling #Jaipur',
                                       'feedback': 'Not interested', 'lat': 10, 'lon': 20}})
    assert any('Cycling #Jaipur' in text for text in values)
    assert any('Not interested' in text for text in values)
    assert any('10, 20' in text for text in values)
    bounded = evidence_details({'meta': {'caption': 'x' * 5000}})
    assert len(bounded[0]) < 4100 and 'preview' in bounded[0]


def test_pdf_routine_keeps_inference_confidence_source_and_evidence():
    from app.ui.profile_views import report_sections
    from types import SimpleNamespace
    lines = []
    routine = {'label': 'Fictional routine', 'source': 'NexData-inferred', 'confidence': 0.5, 'evidence': ['routine-proof'],
               'sleep_window': {'label': 'Guess: inactive window', 'source': 'NexData-inferred', 'confidence': 0.3, 'evidence': ['sleep-proof']}}
    report_sections({'profile': {'routine': routine}}, lambda value, *args: lines.append(str(value)), SimpleNamespace())
    assert any('routine-proof' in text for text in lines)
    assert any('sleep-proof' in text for text in lines)
    assert any('NexData-inferred | confidence 30%' in text for text in lines)


def test_gui_profile_connections_and_evidence_synthetic(tmp_path, monkeypatch):
    from app.ui import main as ui
    settings = tmp_path / 'settings.json'
    settings.write_text('{"auto_close_browsers": false}', encoding='utf-8')
    monkeypatch.setattr(ui, 'SETTINGS', settings)
    monkeypatch.setattr(ui.NexDataApp, 'scan_laptop', lambda self: None)
    monkeypatch.setattr(ui.NexDataApp, 'offer_recent_exports', lambda self: None)
    monkeypatch.setattr(ui.NexDataApp, 'poll_downloads', lambda self: None)
    path = tmp_path / 'synthetic_gui.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('story_interactions/stories_viewed.html', box(Username='fictional_friend', Caption='Cycling #Jaipur', Time='Nov 1, 2026 9:00 pm'))
    result = pipeline.run([path])
    app = ui.NexDataApp()
    app.withdraw()
    errors = []
    monkeypatch.setattr(app, 'show_errors', lambda text: errors.append(text) if text else None)
    try:
        app.pending_paths = [str(path)]
        app.source_mode = 'imports'
        app.load_complete(result, ui.prepare_charts(result), 1)
        for name in TAB_NAMES:
            app.tabs.set(name)
            app.update_idletasks()
        from matplotlib.backend_bases import MouseEvent, PickEvent
        picked = []
        original_evidence = app.show_evidence

        def open_picked(value):
            picked.append(value)
            popup = original_evidence(value)
            popup.update_idletasks()
            popup.destroy()

        monkeypatch.setattr(app, 'show_evidence', open_picked)
        canvas = app.canvases[-1]
        dots = canvas.figure.axes[0].collections[0]
        event = PickEvent('pick_event', canvas, MouseEvent('button_press_event', canvas, 0, 0), dots, ind=[0])
        canvas.callbacks.process('pick_event', event)
        assert picked and picked[0]['title'] == 'Jaipur'
        assert set(picked[0]['evidence']) == set(result['places'][0]['evidence'])
        monkeypatch.setattr(app, 'show_evidence', original_evidence)
        popup = app.show_evidence({'title': 'Synthetic inference', 'evidence': result['connections'][0]['evidence']})
        popup.update_idletasks()
        popup.destroy()
        assert not errors
        assert not app.auto_close_var.get()
        assert app.tabs.tab('Profile').winfo_children()
        assert app.tabs.tab('Connections & places').winfo_children()
    finally:
        app.closing = True
        app.clear_figures()
        app.destroy()
