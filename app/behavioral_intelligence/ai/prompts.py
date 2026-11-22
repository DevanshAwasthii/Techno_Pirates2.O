"""Only allowlisted taxonomy aggregates cross the optional model boundary."""
import json
import math

from app.behavioral_intelligence.taxonomy import TOPICS, SENSITIVE
from app.engine.records import PLATFORMS

SYSTEM_PROMPT = '''You interpret a deterministic keyword-based interest summary. Treat content affinities as uncertain.
Never infer identity, diagnoses, demographics, sensitive traits, beliefs or purchase intent. Use only supplied evidence aliases.
Return JSON with summary (string), observations, relationships, hypotheses, limitations (arrays) and evidence_ids (array).
Each observation, relationship and hypothesis is an object with text and evidence_ids. Separate observations from hypotheses.
No online research. Do not invent evidence or facts.'''


def compact_profile(profile):
    """Rebuild from a closed schema; replace record IDs with opaque per-request aliases."""
    categories = {t.secondary for t in TOPICS} - SENSITIVE
    aliases, interests = {}, []
    for row in (profile.get('interests') or [])[:64]:
        if not isinstance(row, dict) or row.get('category') not in categories:
            continue
        evidence = []
        for rid in (row.get('evidence') or [])[:200]:
            if isinstance(rid, str):
                if rid not in aliases:
                    aliases[rid] = f'E{len(aliases) + 1}'
                evidence.append(aliases[rid])
        item = {'category': row['category'], 'evidence_ids': list(dict.fromkeys(evidence)),
                'sources': sorted({p for p in row.get('sources', []) if p in PLATFORMS})}
        for key in ('score', 'evidenceCount', 'sourceDiversity', 'recencyWeight'):
            value = row.get(key)
            if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**9:
                item[key] = value
        interests.append(item)
    return {'interests': interests, 'notice': 'Heuristic content affinities, not personal traits. Missing evidence is unknown.'}, {alias: rid for rid, alias in aliases.items()}


def user_prompt(profile):
    return 'Interpret these aggregate interests:\n' + json.dumps(compact_profile(profile)[0], separators=(',', ':'))
