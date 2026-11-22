"""Deterministic interest scoring; never classifies raw messages or audience traits."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from app.cancellation import check_cancel
from app.engine.records import Record
from .taxonomy import classify

POSITIVE = {'story_view', 'story_like', 'like', 'comment', 'save', 'repost', 'post_view', 'video_view', 'see_more'}


def _date(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.astimezone(timezone.utc) if date.tzinfo else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def extract_signals(records):
    """One taxonomy signal per record/topic. IDs stay exactly as the pipeline emitted them."""
    signals = {}
    for raw in records:
        check_cancel()
        r = asdict(raw) if isinstance(raw, Record) else raw
        m = r.get('meta') or {}
        if (not r.get('id') or r.get('category') == 'message' or m.get('source') == 'audience_insights'
                or m.get('negative') or m.get('action') in {'not_interested', 'see_less'}):
            continue
        if not (r.get('category') == 'interest' or m.get('action') in POSITIVE or m.get('is_own')
                or r.get('platform') == 'chrome' and m.get('source') == 'history'):
            continue
        # Explicit supported metadata only. No messages, names, source paths or arbitrary meta dump.
        fields = [m.get(k) for k in ('caption', 'topic', 'category', 'genre', 'genres', 'artist', 'title')]
        fields += m.get('hashtags') or []
        if r.get('category') == 'interest':
            fields.append(r.get('item'))
        text = ' '.join(' '.join(map(str, v)) if isinstance(v, (tuple, list)) else str(v or '') for v in fields)
        domain = str(m.get('domain') or '')
        if domain:
            text = text.replace(domain, ' ')
        for topic, reason, confidence in classify(text, domain):
            key = (r['id'], topic.secondary, topic.name)
            signals[key] = {'evidence_ref': r['id'], 'source': r.get('platform', 'unknown'),
                            'category': topic.secondary, 'primary_category': topic.primary, 'topic': topic.name,
                            'timestamp': r.get('timestamp'), 'confidence': confidence, 'provenance': reason}
    return [signals[key] for key in sorted(signals)]


def analyze_behavior(records, *, now=None):
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    signals = extract_signals(records)
    groups = defaultdict(list)
    for signal in signals:
        groups[signal['category']].append(signal)
    interests = []
    for category, rows in sorted(groups.items()):
        check_cancel()
        # Multiple topic matches in the same category are one piece of evidence.
        unique = {r['evidence_ref']: r for r in rows}
        sources = sorted({r['source'] for r in unique.values()})
        weights, months = [], defaultdict(int)
        for row in unique.values():
            date = _date(row['timestamp'])
            age = max(0, (now - date).days) if date else None
            weights.append(.75 if age is None else 1.2 if age <= 30 else 1.0 if age <= 90 else .7 if age <= 365 else .5)
            if date:
                months[date.strftime('%Y-%m')] += 1
        evidence = sorted(unique)
        recency = round(sum(weights) / len(weights), 3)
        score = round(len(evidence) * recency * (1 + .25 * (len(sources) - 1)), 3)
        level = 'Strong Interest' if len(evidence) >= 3 and len(sources) >= 2 else 'Observed Interest' if len(evidence) >= 2 else 'Possible Interest'
        interests.append({'category': category, 'primaryCategories': sorted({r['primary_category'] for r in rows}),
                          'topics': sorted({r['topic'] for r in rows}), 'evidence': evidence, 'evidenceCount': len(evidence),
                          'sources': sources, 'sourceDiversity': len(sources), 'recencyWeight': recency,
                          'score': score, 'level': level, 'timeline': [{'month': m, 'count': n} for m, n in sorted(months.items())],
                          'explanation': 'Score = unique record count × mean recency weight × (1 + 0.25 × additional platforms). Unknown timestamps weigh 0.75; <=30/90/365/older days weigh 1.2/1/0.7/0.5. Strength is heuristic, not a probability.'})
    interests.sort(key=lambda r: (-r['score'], r['category']))
    limitations = ['Keyword/domain matches may miss context. Content affinity does not establish identity, beliefs or a need.',
                   'Source diversity counts platforms, not independent accounts. Sparse or missing dates limit recency scoring.']
    if not signals:
        limitations.insert(0, 'Insufficient direct evidence: no supported interest signals were found.')
    return {'signals': signals, 'interests': interests, 'profile': {'primaryInterests': interests[:5],
            'secondaryInterests': interests[5:], 'analysisLimitations': limitations},
            'context': {'status': 'UNAVAILABLE', 'detail': 'No population dataset or demographic assumptions.'}}
