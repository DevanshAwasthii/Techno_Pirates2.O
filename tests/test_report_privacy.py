from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from app.reporting import export_result, json_report_bytes
from app.ui.main import report_bytes


def synthetic():
    values = 'Alice Example alice@example.test +91 9876543210 192.168.1.42 2001:db8::123'
    return {'records': [{'id': 'tag-ig-a', 'item': values, 'sourceFile': 'C:/Alice Example/archive.zip',
                         'recordRef': values, 'meta': {'person': 'Alice Example', 'text': values}}],
            'summary': {'topPeople': [{'name': 'Alice Example'}]},
            'findings': [{'title': values, 'detail': values, 'evidence': ['tag-ig-a']}],
            'profile': {'interests': [], 'likes': [{'label': 'Creator: Alice Example', 'evidence': ['tag-ig-a'], 'source': 'NexData-inferred', 'confidence': .5}],
                        'shopping': [], 'dislikes': [], 'sensitive': [], 'life_stage': [], 'routine': {}}}


def test_default_json_masks_identifiers_names_paths_and_raw_text_without_mutation():
    result = synthetic()
    original = deepcopy(result)
    report = json_report_bytes(result).decode()
    assert all(value not in report for value in ('Alice Example', 'alice@example.test', '9876543210', '192.168.1.42', '2001:db8::123', 'C:/'))
    assert 'tag-ig-a' in report and '[name]' in report
    assert result == original
    assert export_result(result, include_full_values=True) == result
    assert 'alice@example.test' in json_report_bytes(result, include_full_values=True).decode()


def test_pdf_default_mask_and_explicit_full_export(tmp_path):
    tool = shutil.which('pdftotext')
    if not tool: pytest.skip('pdftotext unavailable')
    for full in (False, True):
        path = tmp_path / f'report-{full}.pdf'
        path.write_bytes(report_bytes(synthetic(), include_full_values=full))
        text = subprocess.run([tool, str(path), '-'], capture_output=True, check=True).stdout.decode('utf-8')
        assert ('alice@example.test' in text) is full
        assert ('Alice Example' in text) is full
        assert ('192.168.1.42' in text) is full


def test_non_latin_names_and_international_phone_variants():
    value = {'connections': [{'name': 'अमित', 'detail': 'अमित +1 (415) 555-0123'}],
             'records': [{'meta': {'person': '李', 'caption': 'Unknown Person said hello'}, 'item': '李'}]}
    encoded = json.dumps(export_result(value), ensure_ascii=False)
    assert 'अमित' not in encoded and '李' not in encoded and '415' not in encoded
    assert 'Unknown Person' not in encoded


def test_short_name_does_not_corrupt_schema_or_other_words():
    result = {'records': [{'id': 'tag-ig-a', 'meta': {'person': 'A'}, 'item': 'A camera'}],
              'summary': {'title': 'A camera'}, 'findings': []}
    masked = export_result(result)
    assert masked['summary']['title'] == '[name] camera'
    assert masked['records'][0]['meta']['person'] == '[name]'
