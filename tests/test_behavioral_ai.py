import io
import json
from urllib.error import URLError

import pytest

from app.behavioral_intelligence.ai.models import AIConfig, validate_endpoint
from app.behavioral_intelligence.ai.config import AIConfigStore
from app.behavioral_intelligence.ai.colibri_provider import ColibriProvider, generation_payload


@pytest.mark.parametrize('url,lan,allowed', [
    ('http://127.0.0.1:8000/v1', False, True), ('http://localhost/v1', False, True),
    ('http://[::1]:8000/v1', False, True), ('http://192.168.1.2:8000/v1', False, False),
    ('http://10.0.0.1/v1', True, True), ('https://172.16.0.1/v1', True, True),
    ('http://172.31.255.254/v1', True, True), ('http://192.168.1.2/v1', True, True),
    ('http://172.15.1.1/v1', True, False), ('http://172.32.0.1/v1', True, False),
    ('http://8.8.8.8/v1', True, False), ('http://169.254.1.1/v1', True, False),
    ('http://100.64.0.1/v1', True, False), ('http://0.0.0.0/v1', True, False),
    ('http://127.0.0.2/v1', True, False), ('http://[fc00::1]/v1', True, False),
    ('http://[::ffff:127.0.0.1]/v1', True, False), ('http://2130706433/v1', True, False),
    ('http://localhost.evil/v1', True, False), ('http://model.local/v1', True, False),
    ('file://localhost/v1', False, False), ('http://user@localhost/v1', False, False),
    ('http://localhost:99999/v1', False, False), ('http://localhost/v1?url=x', False, False),
    ('http://localhost/v1#x', False, False), ('http://localhost/%2f%2fevil', False, False),
])
def test_endpoint_matrix(url, lan, allowed):
    if allowed:
        assert validate_endpoint(url, lan)
    else:
        with pytest.raises(ValueError):
            validate_endpoint(url, lan)


@pytest.mark.parametrize('fields', [{'enabled': 'false'}, {'allow_lan_model': 1},
    {'timeout_seconds': True}, {'timeout_seconds': float('nan')}, {'timeout_seconds': 0},
    {'max_tokens': 2.5}, {'model': None}, {'base_url': 'https://example.com/v1'}])
def test_strict_config(fields):
    with pytest.raises((ValueError, TypeError)):
        AIConfig.from_dict(fields)


def test_disabled_default_and_config_atomic(tmp_path):
    store = AIConfigStore(tmp_path)
    assert not store.load().enabled
    provider = ColibriProvider(opener=lambda *a, **k: pytest.fail('Network attempted while disabled'))
    assert provider.health().state == 'Disabled'
    assert provider.models() == []
    assert provider.generate({})['status'] == 'UNAVAILABLE'
    store.save(AIConfig(enabled=True))
    assert store.load().enabled
    assert not list(store.path.parent.glob('*.tmp'))
    store.path.write_text('{"enabled":"true"}')
    assert not store.load().enabled


def test_payload_allows_only_compact_taxonomy_aggregates():
    raw = {'interests': [{'category': 'Programming', 'score': 2.4, 'sourceDiversity': 1,
        'evidenceCount': 2, 'evidence': ['tag-ig-private'], 'sources': ['instagram'],
        'explanation': 'secret@example.test', 'caption': 'private text', 'topics': ['Python']}],
        'records': [{'text': 'secret message'}], 'cookies': 'secret cookie', 'path': 'C:/private',
        'signals': [{'evidence_ref': 'tag-ig-private', 'raw': 'raw text'}]}
    payload = generation_payload('local-model', raw, 100)
    encoded = json.dumps(payload)
    assert 'Programming' in encoded
    assert 'E1' in encoded
    assert all(s not in encoded for s in ('secret', 'private', 'raw text', 'caption', 'cookies', 'tag-ig'))


@pytest.mark.parametrize('error', [TimeoutError(), URLError(TimeoutError())])
def test_timeout_handling(error):
    def fail(*a, **k): raise error
    provider = ColibriProvider(AIConfig(enabled=True), opener=fail)
    assert provider.health().state == 'Connection timeout'
    assert provider.generate({})['status'] == 'UNAVAILABLE'


def test_generation_timeout_and_evidence_remapping():
    calls = []
    def respond(request, **kwargs):
        calls.append(request)
        if request.full_url.endswith('/models'):
            return io.BytesIO(b'{"data":[{"id":"local"}]}')
        content = json.dumps({'summary': 'Possible programming affinity', 'evidence_ids': ['E1', 'invented']})
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': content}}]}).encode())
    profile = {'interests': [{'category': 'Programming', 'evidence': ['tag-ig-a'], 'evidenceCount': 1}]}
    provider = ColibriProvider(AIConfig(enabled=True), opener=respond)
    result = provider.generate(profile)
    assert result['evidence_ids'] == ['tag-ig-a']
    assert result['invalidEvidenceIds'] == ['invented']
    assert len(calls) == 2
    def timeout(request, **kwargs):
        if request.full_url.endswith('/models'): return respond(request, **kwargs)
        raise TimeoutError()
    assert ColibriProvider(AIConfig(enabled=True), opener=timeout).generate(profile)['status'] == 'ERROR'
