"""Additional Instagram HTML activity. Entirely offline; exports describe observations, not intent."""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone

from app.cancellation import check_cancel
from app.engine.records import ParseError, Record
from app.parsers.instagram_html import boxes, parse_date

# Match section + basename so an unrelated posts.html cannot masquerade as Instagram activity.
SECTIONS = {
    'story_interactions/stories_viewed.html': ('activity', 'story_view'),
    'story_interactions/story_likes.html': ('activity', 'story_like'),
    'ads_and_topics/posts_viewed.html': ('activity', 'post_view'),
    'ads_and_topics/videos_watched.html': ('activity', 'video_view'),
    'saved/saved_posts.html': ('activity', 'save'),
    'media/reposts.html': ('activity', 'repost'),
    'media/posts.html': ('activity', 'post'),
    'media/stories.html': ('activity', 'story'),
    "ads_and_topics/posts_you're_not_interested_in.html": ('interest', 'not_interested'),
    "ads_and_topics/posts_you're_interested_or_not_interested_in.html": ('interest', 'feedback'),
    'your_ads/see_more_topics.html': ('interest', 'see_more'),
    'your_ads/see_less_topics.html': ('interest', 'see_less'),
    "instagram_ads_and_businesses/information_you've_submitted_to_advertisers.html": ('account', 'submitted_info'),
    'past_instagram_insights/audience_insights.html': ('account', 'audience_insights'),
}
MAX_MEMBER_BYTES = 32 * 1024 * 1024


def section(name):
    path = name.replace('\\', '/').lower()
    # Some exports put the two topic pages directly under ads_and_topics.
    path = path.replace('/your_ads_see_more/', '/your_ads/').replace('/your_ads_see_less/', '/your_ads/')
    return next((value for suffix, value in SECTIONS.items() if path == suffix or path.endswith('/' + suffix)), None)


def supports(zf):
    return any(section(n) for n in zf.namelist())


def _date(value):
    if not value:
        return None
    parsed = parse_date(value)
    if parsed:
        return parsed
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).isoformat()
    except ValueError:
        try:
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None


def parse(zf, src='instagram.zip', owner=None):
    """Return (records, coverage, owner); an activity-only archive is supported."""
    records = []
    coverage = {k: 'not_assessed' for k in ('activity', 'interest', 'location', 'contact')}
    for name in zf.namelist():
        check_cancel()
        spec = section(name)
        if not spec:
            continue
        if zf.getinfo(name).file_size > MAX_MEMBER_BYTES:
            raise ParseError('too_large', 'Instagram activity page exceeds the local size limit', src)
        category, action = spec
        with zf.open(name) as stream:
            entries = boxes(stream.read().decode('utf-8', errors='replace'))
        if category in coverage:
            coverage[category] = 'found' if entries or coverage[category] == 'found' else 'not_found'
        for index, entry in enumerate(entries):
            check_cancel()
            fields = {k.casefold().strip().rstrip(':'): v for k, v in entry['fields'].items()}

            def first(*keys):
                return next((fields[k][0] for k in keys if fields.get(k)), None)

            own = action in ('post', 'story')
            person = first('username', 'owner', 'media owner', 'author', 'account', 'creator')
            if not person and not own and action in ('story_view', 'story_like', 'post_view', 'video_view', 'save', 'repost'):
                person = entry['title'] or next((text for text, url in entry['links'] if url and 'instagram.com/' in url), None)
            caption = first('caption', 'text', 'description') or ''
            # In media exports the caption is often the heading or an unlabelled body div.
            if own and not caption:
                caption = entry['title'] or ' '.join(t for t in entry['texts'] if t not in {v for vs in fields.values() for v in vs} and t.casefold() not in fields)
            feedback = first('feedback', 'response') or ('Not interested' if action == 'not_interested' else None)
            negative = action in ('not_interested', 'see_less') or bool(feedback and re.search(r'not interested|see less|dislike', feedback, re.I))
            meta = {'action': action, 'person': owner if own else person, 'owner': owner if own else person,
                    'is_own': own, 'caption': caption, 'hashtags': re.findall(r'#(\w+)', caption),
                    'feedback': feedback, 'negative': negative, 'source': action}
            topic = first('name', 'topic', 'category') or (entry['title'] if category == 'interest' else None)
            if topic:
                meta['topic'] = topic
            if action in ('submitted_info', 'audience_insights'):
                meta['fields'] = entry['fields']
                meta['domain'] = first('advertiser', 'business', 'company')
            if action == 'story':
                meta['device'] = first('device', 'camera', 'device name')
            try:
                lat, lon = float(first('latitude')), float(first('longitude'))
                if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                    meta.update(lat=lat, lon=lon)
                    coverage['location'] = 'found'
            except (TypeError, ValueError):
                pass
            timestamp = _date(first('date taken', 'time', 'timestamp', 'date')) or entry['date']
            digest = hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]
            records.append(Record(f'ia-{digest}-{index:06d}', 'instagram', category,
                                  f'Instagram {action.replace("_", " ")}', timestamp,
                                  sourceFile=name, recordRef=f'item {index + 1}', meta=meta))
    return records, coverage, owner
