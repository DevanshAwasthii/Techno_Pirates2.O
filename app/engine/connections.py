"""Evidence-backed interaction ranking. Scores describe export activity, never friendship quality."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime
import unicodedata

from app.cancellation import check_cancel

WEIGHTS = {'story_view': 1, 'story_like': 3, 'like': 2, 'comment': 4, 'save': 4, 'repost': 5, 'dm': 5}


def identity(platform, person):
    return platform + ':' + unicodedata.normalize('NFC', str(person)).strip().lstrip('@').casefold()


def day(stamp):
    try:
        return datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).date().toordinal()
    except (ValueError, TypeError, OverflowError):
        return None


def build_connections(records, places=()):
    people = {}
    for r in records:
        check_cancel()
        m = r.meta
        person = m.get('person')
        action = m.get('action')
        if m.get('is_own'):
            continue
        if r.category == 'message':
            thread = m.get('thread') or []
            if m.get('group') or len(thread) > 1:
                continue
            if m.get('direction') == 'out':
                person = thread[0] if len(thread) == 1 else None
            action = 'dm'
        relation = m.get('relation')
        if not person or not (action in WEIGHTS or relation in ('follower', 'following')):
            continue
        key = identity(r.platform, person)
        if key not in people:
            people[key] = {'id': key, 'name': str(person), 'platform': r.platform,
                           'counts': Counter(), 'evidence': [], 'follows': set(),
                           'story_directions': Counter(), 'places': [], 'shared_places': []}
        entry = people[key]
        entry['evidence'].append(r.id)
        if action in WEIGHTS:
            entry['counts'][action] += 1
        if relation:
            entry['follows'].add(relation)
        if action == 'story_view':
            entry['story_directions']['in' if m.get('direction') == 'in' else 'out'] += 1
    # Index dates of your own mentions/coordinates once; avoid a pairwise scan across all activity.
    own = defaultdict(list)
    record_platform = {r.id: r.platform for r in records}
    for place in places:
        stamp = day(place.get('timestamp'))
        if place.get('is_own') and stamp is not None:
            own[place['id']].append((stamp, place))
    own_dates = {}
    for key, rows in own.items():
        rows.sort(key=lambda row: row[0])
        own_dates[key] = [row[0] for row in rows]
    shared_seen = set()
    for place in places:
        check_cancel()
        if place.get('is_own') or not place.get('person'):
            continue
        platform = record_platform.get(place['evidence'][0])
        key = identity(platform or '', place['person'])
        if key not in people:
            continue
        entry = people[key]
        entry['places'].append(place)
        stamp = day(place.get('timestamp'))
        rows = own.get(place['id'], [])
        if stamp is None or not rows:
            continue
        index = bisect_left(own_dates[place['id']], stamp - 60)
        if index < len(rows) and rows[index][0] <= stamp + 60:
            _, yours = rows[index]
            pair = (key, place['id'], place['timestamp'], yours['timestamp'])
            if pair in shared_seen:
                continue
            shared_seen.add(pair)
            entry['shared_places'].append({'label': f"Shared mention: {place['name']} (co-location unconfirmed)",
                                          'place': place['name'], 'your_date': yours['timestamp'],
                                          'their_date': place['timestamp'], 'confidence': 0.4,
                                          'source': 'NexData-inferred', 'inferred': True,
                                          'evidence': list(dict.fromkeys(place['evidence'] + yours['evidence']))})
    for entry in people.values():
        follows = entry.pop('follows')
        directions = entry.pop('story_directions')
        entry['score'] = sum(WEIGHTS[k] * n for k, n in entry['counts'].items())
        entry['counts'] = dict(entry['counts'])
        if len(follows) == 2 and entry['counts'].get('dm'):
            entry['relationship'] = 'mutual (follow both ways + chat)'
        elif len(follows) == 2:
            entry['relationship'] = 'follow both ways (chat not observed)'
        elif follows:
            entry['relationship'] = 'one-way follow observed'
        else:
            entry['relationship'] = 'follow relationship unknown'
        entry['labels'] = []
        if directions['out']:
            entry['labels'].append(f"you watch their stories ({directions['out']} exported views)")
        if directions['in']:
            entry['labels'].append(f"watches your stories ({directions['in']} exported views; completeness unknown)")
        entry.update(label=entry['relationship'], confidence=min(0.9, 0.3 + entry['score'] / 100),
                     source='NexData-inferred', inferred=True)
        entry['evidence'] = list(dict.fromkeys(entry['evidence']))
    return sorted(people.values(), key=lambda entry: (-entry['score'], entry['id']))
