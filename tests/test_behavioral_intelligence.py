from datetime import datetime, timezone
from threading import Event

import pytest

from app.cancellation import Cancelled, cancellation
from app.engine.records import Record, to_dict
from app.behavioral_intelligence.service import analyze_behavior
from app.behavioral_intelligence.taxonomy import classify


NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def record(key, platform='instagram', timestamp='2026-11-20T00:00:00Z', **meta):
    return Record(key, platform, 'interest', 'Python programming', timestamp, meta=meta)


def test_hierarchy_scores_unique_evidence_sources_and_recency():
    rows = [record('tag-ig-a'), record('tag-ig-b', 'spotify'), record('tag-ig-c')]
    result = analyze_behavior(rows + rows, now=NOW)
    category = next(r for r in result['interests'] if r['category'] == 'Programming')
    assert category['evidence'] == ['tag-ig-a', 'tag-ig-b', 'tag-ig-c']
    assert category['evidenceCount'] == 3
    assert category['sourceDiversity'] == 2
    assert category['primaryCategories'] == ['Technology']
    assert {'Python', 'Software Development'} <= set(category['topics'])
    old = analyze_behavior([record('tag-ig-a', timestamp='2020-01-01T00:00:00Z')], now=NOW)
    assert result['interests'][0]['score'] > old['interests'][0]['score']
    assert result == analyze_behavior([to_dict(r) for r in reversed(rows)], now=NOW)


def test_ignores_messages_negative_feedback_and_audience():
    rows = [record('negative', action='see_less'), record('audience', source='audience_insights'),
            Record('chat', 'whatsapp', 'message', 'Python programming', None, meta={'text': 'Python'})]
    assert not analyze_behavior(rows, now=NOW)['signals']
    assert analyze_behavior([], now=NOW)['profile']['analysisLimitations']
    assert not classify('notpython')
    assert not classify('', 'evilpython.org')


def test_cancellation():
    event = Event()
    event.set()
    with pytest.raises(Cancelled), cancellation(event):
        analyze_behavior([record('a')], now=NOW)
