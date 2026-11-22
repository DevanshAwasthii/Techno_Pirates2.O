from urllib.parse import urlsplit

from app.engine.extras import build_extras, deletion_directory
from app.engine.records import Record


def test_age_directory_matching_and_ad_preview():
    records = [Record('old', 'instagram', 'activity', '', '2020-02-01T12:00:00'),
               Record('new', 'instagram', 'activity', '', '2026-01-01T12:00:00Z'),
               Record('bad', 'spotify', 'activity', '', 'not a date'),
               Record('account', 'gmail', 'account', '', None, meta={'domain': 'mail.instagram.com'}),
               Record('unknown', 'gmail', 'account', '', None, meta={'domain': 'fictional.invalid'})]
    profile = {'interests': [{'label': 'Cycling', 'confidence': 0.6, 'source': 'NexData-inferred', 'evidence': ['new']}],
               'sensitive': [{'label': 'Health', 'evidence': ['old']}]}
    extras = build_extras(records, profile)
    assert extras['data_age'][0]['oldest'] == '2020-02-01'
    assert extras['data_age'][0]['evidence'] == ['old']
    assert 'oldest exported record' in extras['data_age'][0]['label']
    assert next(d for d in extras['deletion'] if d['service'] == 'Instagram')['evidence'] == ['account']
    assert next(d for d in extras['deletion'] if d['service'] == 'fictional')['status'] == 'unknown'
    assert len(extras['ad_targeting']) == 1 and 'Cycling' in extras['ad_targeting'][0]['label']
    assert all('Health' not in x['label'] for x in extras['ad_targeting'])
    assert len(deletion_directory()) >= 95
    for entry in deletion_directory():
        assert entry['status'] in ('official route (offline reference)', 'unknown')
        if entry['url']:
            assert urlsplit(entry['url']).scheme == 'https'
            assert any(urlsplit(entry['url']).hostname == domain or urlsplit(entry['url']).hostname.endswith('.' + domain)
                       for domain in entry['official_domains'])
        else:
            assert entry['status'] == 'unknown'
