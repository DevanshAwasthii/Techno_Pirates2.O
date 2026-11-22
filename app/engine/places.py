"""Small hand-authored gazetteer; no geocoding service, tiles, downloads or IP lookup."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re

from app.cancellation import check_cancel


@lru_cache(maxsize=1)
def gazetteer():
    return json.loads(Path(__file__).with_name('data').joinpath('places.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _patterns():
    result = []
    for place in gazetteer():
        aliases = [place['name'], *place.get('aliases', [])]
        parts = [re.escape(a).replace(r'\ ', r'[\s_]*') for a in aliases]
        result.append((place, re.compile(r'(?<!\w)(?:' + '|'.join(parts) + r')(?!\w)', re.I)))
    return result


def find_mentions(text):
    found = []
    text = str(text or '')
    for place, pattern in _patterns():
        check_cancel()
        matches = list(pattern.finditer(text))
        if place.get('ambiguous'):
            matches = [m for m in matches if text[max(0, m.start() - 1):m.start()] == '#'
                       or re.search(r'\b(?:in|at|visit|visiting|from|to)\s+$', text[max(0, m.start() - 15):m.start()], re.I)]
        if matches:
            found.append(dict(place))
    return found


def nearest_place(lat, lon, max_km=100):
    try:
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    nearest, distance = None, float('inf')
    for place in gazetteer():
        check_cancel()
        if place['kind'] not in ('city', 'landmark'):
            continue
        p1, p2 = math.radians(lat), math.radians(place['lat'])
        a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(place['lon'] - lon) / 2) ** 2
        km = 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, a))))
        if km < distance:
            nearest, distance = place, km
    return dict(nearest, distance_km=round(distance, 2)) if nearest and distance <= max_km else None


def build_places(records):
    """One evidence-bearing association per record/place. A mention never proves a visit."""
    associations = []
    mention_cache = {}
    coordinate_cache = {}
    for r in records:
        check_cancel()
        m = r.meta
        text = ' '.join(str(x or '') for x in (m.get('caption'), m.get('place'), ' '.join(m.get('hashtags') or [])))
        if text not in mention_cache:
            mention_cache[text] = find_mentions(text) if text.strip() else []
        matches = {p['id']: (p, False) for p in mention_cache[text]}
        coords = (str(m.get('lat')), str(m.get('lon')))
        if m.get('lat') is not None and m.get('lon') is not None:
            if coords not in coordinate_cache:
                coordinate_cache[coords] = nearest_place(m['lat'], m['lon'])
            nearest = coordinate_cache[coords]
            if nearest:
                matches[nearest['id']] = (nearest, True)
        for place, coordinate in matches.values():
            own = bool(m.get('is_own') or (r.category == 'location' and not m.get('person') and m.get('source') != 'location_of_interest'))
            association = ('coordinate recorded' if coordinate else 'your mention (visit unconfirmed)') if own else 'viewed content'
            if m.get('source') == 'location_of_interest':
                association = 'platform location interest (visit unconfirmed)'
            associations.append({**place, 'label': place['name'], 'person': None if own else m.get('person'),
                                 'is_own': own, 'timestamp': r.timestamp, 'association': association,
                                 'confidence': 0.8 if coordinate else 0.45, 'source': 'NexData-inferred',
                                 'inferred': True, 'evidence': [r.id]})
    return associations
