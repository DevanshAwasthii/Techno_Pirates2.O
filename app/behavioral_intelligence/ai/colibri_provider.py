"""Optional OpenAI-compatible provider, with no proxy or redirect egress."""
from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from app.cancellation import check_cancel
from .models import AIConfig, AIHealth, validate_endpoint
from .prompts import SYSTEM_PROMPT, user_prompt, compact_profile


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Model endpoint redirects are blocked')


class ColibriProvider:
    def __init__(self, config=None, opener=None):
        self.config = config or AIConfig()
        self.base_url = validate_endpoint(self.config.base_url, self.config.allow_lan_model)
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def _request(self, path, payload=None):
        if not self.config.enabled:
            raise ValueError('Local AI is disabled')
        check_cancel()
        data = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        request = Request(self.base_url + path, data=data, headers={'Content-Type': 'application/json'} if data else {})
        with self._opener(request, timeout=self.config.timeout_seconds) as response:
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise ValueError('Model response exceeded the local size limit')
            check_cancel()
            return json.loads(body.decode('utf-8'))

    def models(self):
        if not self.config.enabled:
            return []
        value = self._request('/models')
        rows = value.get('data') if isinstance(value, dict) else None
        if not isinstance(rows, list):
            raise ValueError('Invalid model list')
        return [r['id'] for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str) and r['id']]

    def health(self):
        if not self.config.enabled:
            return AIHealth('Disabled', detail='Local AI is disabled. Deterministic analysis remains available.')
        try:
            models = self.models()
            model = self.config.model if self.config.model else next(iter(models), '')
            if model not in models or not model:
                return AIHealth('Model unavailable', detail='The configured server did not list a usable model.')
            return AIHealth('Connected', model, self.config.warning or 'Loopback model discovery succeeded.')
        except (TimeoutError, URLError) as exc:
            if isinstance(exc, TimeoutError) or isinstance(getattr(exc, 'reason', None), TimeoutError):
                return AIHealth('Connection timeout', detail='Model discovery timed out.')
            return AIHealth('Server not running', detail='No model server responded at the configured endpoint.')
        except (OSError, ValueError, TypeError):
            return AIHealth('Invalid response', detail='Model discovery failed or returned an invalid response.')

    def generate(self, profile):
        health = self.health()
        if health.state != 'Connected':
            return {'status': 'UNAVAILABLE', 'detail': health.detail, 'health': health.to_dict()}
        try:
            payload = generation_payload(health.model, profile, self.config.max_tokens)
            response = self._request('/chat/completions', payload)
            content = response['choices'][0]['message']['content']
            aliases = compact_profile(profile)[1]
            result = parse_and_validate(content, aliases)
            return dict(result, status='COMPLETED', model=health.model, warning=self.config.warning)
        except (TimeoutError, URLError, OSError, ValueError, KeyError, IndexError, TypeError):
            return {'status': 'ERROR', 'detail': 'Model generation timed out, failed, or returned invalid JSON. Deterministic analysis remains available.'}


def generation_payload(model, profile, max_tokens):
    return {'model': model, 'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_prompt(profile)}], 'temperature': .1, 'max_tokens': max_tokens}


def parse_and_validate(content, aliases):
    if not isinstance(content, str):
        raise ValueError('Model content must be text')
    if content.strip().startswith('```'):
        content = content.strip().split('\n', 1)[-1].rsplit('```', 1)[0]
    value = json.loads(content)
    if not isinstance(value, dict) or not isinstance(value.get('summary'), str):
        raise ValueError('Model JSON requires a summary')
    invalid = []

    def ids(values):
        values = values if isinstance(values, list) else []
        invalid.extend(v for v in values if isinstance(v, str) and v not in aliases)
        return list(dict.fromkeys(aliases[v] for v in values if isinstance(v, str) and v in aliases))

    result = {'summary': value['summary'][:8000], 'evidence_ids': ids(value.get('evidence_ids'))}
    for key in ('observations', 'relationships', 'hypotheses'):
        rows = value.get(key)
        result[key] = [{'text': r['text'][:2000], 'evidence_ids': ids(r.get('evidence_ids'))}
                       for r in (rows[:50] if isinstance(rows, list) else []) if isinstance(r, dict) and isinstance(r.get('text'), str)]
    limits = value.get('limitations')
    result['limitations'] = [r[:1000] for r in limits[:30] if isinstance(r, str)] if isinstance(limits, list) else []
    result['invalidEvidenceIds'] = sorted(set(invalid))
    return result
