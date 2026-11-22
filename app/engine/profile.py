"""Offline, inspectable content-affinity heuristics. These are guesses, not platform internals."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import re

from app.cancellation import check_cancel

# No creator lookup or model call: only terms actually present in imported metadata.
TAXONOMY = {
    'Cycling': 'cycling|bicycle|biking|cyclist',
    'Photography': 'photography|photographer|photo editing|camera gear',
    'Travel': 'travel|travelling|traveling|backpacking|wanderlust|tourism',
    'Fitness': 'fitness|workout|gym|bodybuilding|strength training',
    'Running': 'running|marathon|jogging|runner',
    'Yoga': 'yoga|pilates|meditation',
    'Food & cooking': 'cooking|recipes|foodie|baking|chef|cuisine',
    'Coffee & tea': 'coffee|espresso|barista|chai|tea brewing',
    'Music': 'music|jazz|rock music|hip hop|hiphop|bollywood|classical|indie|spotify|pop music',
    'Dance': 'dance|dancing|choreography|bharatanatyam|kathak',
    'Film & television': 'cinema|movies|film|netflix|television|anime',
    'Books & writing': 'books|reading|bookclub|book club|literature|poetry|writing',
    'Gaming': 'gaming|videogames|video games|esports|playstation|xbox',
    'Technology': 'technology|software|coding|programming|artificial intelligence|gadgets',
    'Science': 'science|physics|astronomy|space exploration|chemistry',
    'Education': 'education|student|university|college|study tips|exam|learning',
    'Careers': 'career|job search|interview|recruitment|resume|professional development',
    'Business': 'business|startup|entrepreneur|marketing|small business',
    'Fashion': 'fashion|outfit|streetwear|style tips|clothing',
    'Beauty': 'beauty|makeup|skincare|cosmetics',
    'Home & design': 'interior design|home decor|furniture|architecture|renovation',
    'Gardening': 'gardening|houseplants|horticulture|garden',
    'Pets & animals': 'pets|dogs|cats|wildlife|animal rescue',
    'Football': 'football|soccer|premier league|fifa',
    'Cricket': 'cricket|ipl|batsman|bowling|t20',
    'Other sports': 'basketball|tennis|badminton|swimming|hockey|volleyball',
    'Outdoors': 'hiking|trekking|camping|mountaineering|surfing',
    'Cars': 'cars|automotive|motorsport|formula1|formula 1|motorcycle',
    'Art & crafts': 'painting|drawing|crafts|sculpture|illustration|pottery',
    'Parenting': 'parenting|baby care|childcare|newborn|motherhood|fatherhood',
    'Weddings': 'wedding|bridal|bride|groom|marriage planning',
    'Sustainability': 'sustainability|recycling|climate|zero waste|eco friendly',
    'Health': 'health|diabetes|therapy|mental health|nutrition|medical|depression',
    'Religion': 'religion|hindu|muslim|christian|sikh|buddhist|prayer|spirituality',
    'Politics': 'politics|election|elections|parliament|political|democracy',
    'Finance': 'finance|investing|investment|stocks|mutual funds|credit|loan|insurance',
}
PATTERNS = {label: re.compile(r'(?<!\w)(?:' + words + r')(?!\w)', re.I) for label, words in TAXONOMY.items()}
SENSITIVE = {'Health', 'Religion', 'Politics', 'Finance'}
POSITIVE = {'story_view', 'story_like', 'like', 'comment', 'save', 'repost', 'post_view', 'video_view', 'see_more'}
LOCAL_ZONE = timezone(timedelta(hours=5, minutes=30))


def item(label, ids, confidence=0.5, source='NexData-inferred', **extra):
    return {'label': label, 'confidence': round(confidence, 2), 'source': source,
            'evidence': list(dict.fromkeys(ids)), **extra}


def _negative(meta):
    return bool(meta.get('negative') or meta.get('action') in {'not_interested', 'see_less'} or
                re.search(r'not interested|see less|dislike', str(meta.get('feedback') or ''), re.I))


def _text(meta):
    values = [meta.get(k) for k in ('caption', 'topic', 'category', 'genre', 'genres', 'person', 'artist')]
    values += meta.get('hashtags') or []
    return ' '.join(' '.join(map(str, v)) if isinstance(v, (tuple, list)) else str(v or '') for v in values)


def daily_routine(records):
    hours, weekdays, weekends, dates, evidence = Counter(), Counter(), Counter(), set(), []
    daysets = {'weekday': set(), 'weekend': set()}
    for r in records:
        check_cancel()
        if r.category not in ('activity', 'message') or not r.timestamp:
            continue
        try:
            stamp = datetime.fromisoformat(r.timestamp.replace('Z', '+00:00'))
        except (TypeError, ValueError, OverflowError):
            continue
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(LOCAL_ZONE)
        hours[stamp.hour] += 1
        (weekends if stamp.weekday() >= 5 else weekdays)[stamp.hour] += 1
        daysets['weekend' if stamp.weekday() >= 5 else 'weekday'].add(stamp.date())
        dates.add(stamp.date())
        evidence.append(r.id)
    sleep = None
    if len(evidence) >= 20 and len(dates) >= 5:
        # Quietest eight-hour interval is an inactivity guess, never proof of actual sleep.
        start = min(range(24), key=lambda h: sum(hours[(h + offset) % 24] for offset in range(8)))
        sleep = item(f'Guess: possible inactive/sleep window {start:02}:00–{(start + 8) % 24:02}:00', evidence, 0.3)
    return {'label': 'Routine inferred from timestamped activity (export coverage may be sparse)',
            'confidence': 0.5 if len(dates) >= 5 else 0.2, 'source': 'NexData-inferred', 'evidence': evidence,
            'peak_hours': [h for h, _ in hours.most_common(3)], 'hour_counts': [hours[h] for h in range(24)],
            'weekday_hours': [weekdays[h] for h in range(24)], 'weekend_hours': [weekends[h] for h in range(24)],
            'weekday_observed_days': len(daysets['weekday']), 'weekend_observed_days': len(daysets['weekend']),
            'sleep_window': sleep, 'timezone_note': 'Aware times converted to Asia/Kolkata; naive export times retained as local. Not continuous monitoring.'}


def build_profile(records, connections=(), places=()):
    topics, likes, dislikes, shopping = defaultdict(list), defaultdict(list), [], []
    for r in records:
        check_cancel()
        m = r.meta
        negative = _negative(m)
        text = _text(m)
        if negative:
            dislikes.append(item(m.get('topic') or m.get('caption') or m.get('feedback') or 'Less of this content', [r.id], 0.85,
                                 'platform-inferred' if r.inferenceOrigin == 'platform' else 'NexData-inferred'))
        # Audience insights describe an audience, not the export owner's demographics.
        if not negative and m.get('source') != 'audience_insights' and (r.category == 'interest' or m.get('action') in POSITIVE or m.get('is_own')):
            source = 'platform-inferred' if r.inferenceOrigin == 'platform' else 'NexData-inferred'
            for label, pattern in PATTERNS.items():
                if pattern.search(text):
                    topics[(label, source)].append(r.id)
        if not negative and m.get('action') in POSITIVE:
            if m.get('person') and not m.get('is_own'):
                likes[('Creator: ' + str(m['person']), r.platform)].append(r.id)
            content = {'story_view': 'Stories', 'story_like': 'Stories', 'post_view': 'Posts', 'like': 'Posts',
                       'video_view': 'Videos', 'save': 'Saved posts', 'repost': 'Reposts'}.get(m.get('action'))
            if content:
                likes[('Content type: ' + content, r.platform)].append(r.id)
            if m.get('brand'):
                likes[('Brand: ' + str(m['brand']), r.platform)].append(r.id)
        if m.get('source') in ('advertiser', 'off_meta', 'submitted_info') or m.get('action') == 'submitted_info':
            source = m.get('source') or m['action']
            label = {'advertiser': 'Advertiser holds information', 'off_meta': 'Off-Meta activity sender',
                     'submitted_info': 'Submitted advertiser information'}.get(source, source)
            if m.get('domain'):
                label += ': ' + str(m['domain'])
            shopping.append(item(label, [r.id], 0.9, information_types=list((m.get('fields') or {}).keys())))
    interests, sensitive = [], []
    for (label, source), ids in topics.items():
        confidence = 0.9 if source == 'platform-inferred' else min(0.85, 0.35 + 0.1 * len(set(ids)))
        value = item(label, ids, confidence, source)
        if label in SENSITIVE:
            value.update(sensitive=True, warning='Sensitive content affinity; does not establish a personal trait or belief.')
            sensitive.append(value)
        else:
            interests.append(value)
    interests.sort(key=lambda x: (-len(x['evidence']), -x['confidence'], x['label']))
    likes = [item(label, ids, min(0.85, 0.35 + 0.05 * len(ids)), platform=platform)
             for (label, platform), ids in sorted(likes.items(), key=lambda p: -len(p[1]))]
    life_stage = [item(f"Guess: {v['label'].lower()} content affinity; life stage unconfirmed", v['evidence'], 0.25)
                  for v in interests if v['label'] in ('Education', 'Careers', 'Parenting', 'Weddings')]
    return {'title': 'Your profile as the algorithms see it',
            'notice': 'An offline approximation from exported evidence. Content affinity is not identity; confidence is heuristic, not a probability.',
            'interests': interests, 'likes': likes, 'dislikes': dislikes, 'shopping': shopping,
            'routine': daily_routine(records), 'places': list(places), 'social_circle': list(connections),
            'life_stage': life_stage, 'sensitive': sensitive}
