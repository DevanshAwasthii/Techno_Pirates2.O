"""Instagram JSON export parser (Accounts Center > Download your information, format JSON).

Matches files by name pattern, not fixed path: Meta moves folders between export versions.
Never loads the whole zip; reads only the JSON members it needs.
"""
from __future__ import annotations

from app.cancellation import check_cancel

import json
import re
import zipfile
from datetime import datetime, timezone

from app.engine.records import Record, ParseError

PLATFORM = "instagram"
MAX_MEMBER_BYTES = 200 * 1024 * 1024  # ponytail: per-file cap; raise after testing larger exports


def fix_text(s):
    """Meta exports UTF-8 bytes escaped as latin-1 code points (mojibake). Undo it."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def iso(ts) -> str | None:
    if ts in (None, "", 0):
        return None
    ts = float(ts)
    if ts > 1e11:  # milliseconds
        ts /= 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_instagram_zip(zf: zipfile.ZipFile) -> bool:
    names = zf.namelist()
    return any(re.search(r"(followers_\d+|following|liked_posts|post_comments(_\d+)?|login_activity|your_topics|message_\d+"
                         r"|personal_information|advertisers_using_your_activity_or_information"
                         r"|your_activity_off_meta_technologies|other_categories_used_to_reach_you)\.(json|html)$", n)
               for n in names)


INSTAGRAM_JSON = re.compile(r"(followers_\d+|following|liked_posts|post_comments(_\d+)?|login_activity|your_topics|message_\d+"
                            r"|personal_information|advertisers_using_your_activity_or_information"
                            r"|your_activity_off_meta_technologies)\.json$")


def _load(zf, name):
    info = zf.getinfo(name)
    if info.file_size > MAX_MEMBER_BYTES:
        raise ParseError("too_large", f"{name} is {info.file_size // 2**20} MB", name)
    with zf.open(name) as f:
        return json.load(f)


def _find(names, pattern):
    return [n for n in names if re.search(pattern, n)]


def _sld(entry):
    """First string_list_data item of a Meta list entry."""
    lst = entry.get("string_list_data") or [{}]
    return lst[0] if lst else {}


def parse(zf: zipfile.ZipFile, src: str = "instagram.zip", owner_name: str | None = None):
    """Return (records, coverage, owner_name). Raises ParseError."""
    names = zf.namelist()
    json_files = [n for n in names if n.endswith(".json")]
    if not json_files and any(n.endswith(".html") for n in names):
        raise ParseError("html_export", "Instagram export is HTML; request it again as JSON", src)

    recs: list[Record] = []
    cov = {"location": "not_assessed", "interest": "not_assessed", "contact": "not_assessed", "activity": "not_assessed"}
    n = 0

    def add(category, item, ts, file, ref, kind="recorded", origin=None, **meta):
        nonlocal n
        n += 1
        recs.append(Record(f"ig-{category[:4]}-{n:05d}", PLATFORM, category, item, ts, kind, origin, file, ref, meta))

    def mark(cat, found):
        if found:
            cov[cat] = "found"
        elif cov[cat] != "found":
            cov[cat] = "not_found"

    # owner name: needed to tell incoming from outgoing DMs
    for f in _find(json_files, r"personal_information\.json$"):
        check_cancel()
        try:
            d = _load(zf, f)
            prof = (d.get("profile_user") or [{}])[0].get("string_map_data", {})
            owner_name = owner_name or fix_text((prof.get("Name") or {}).get("value"))
        except (ValueError, KeyError, IndexError):
            pass

    # contacts: followers / following
    found = False
    for f in _find(json_files, r"followers_\d+\.json$"):
        check_cancel()
        for i, e in enumerate(_load(zf, f)):
            check_cancel()
            s = _sld(e)
            who = fix_text(s.get("value") or e.get("title"))
            if who:
                found = True
                add("contact", f"Follower: @{who}", iso(s.get("timestamp")), f, f"index {i}", person=who, relation="follower")
    for f in _find(json_files, r"following\.json$"):
        check_cancel()
        d = _load(zf, f)
        items = d if isinstance(d, list) else d.get("relationships_following", []) if isinstance(d, dict) else []
        for i, e in enumerate(items):
            check_cancel()
            s = _sld(e)
            who = fix_text(e.get("title") or s.get("value"))
            if who:
                found = True
                add("contact", f"You follow @{who}", iso(s.get("timestamp")), f, f"index {i}", person=who, relation="following")
    if _find(json_files, r"(followers_\d+|following)\.json$"):
        mark("contact", found)

    # activity: likes and comments
    found = False
    for f in _find(json_files, r"liked_posts\.json$"):
        check_cancel()
        d = _load(zf, f)
        for i, e in enumerate(d.get("likes_media_likes", [])):
            check_cancel()
            who = fix_text(e.get("title"))
            found = True
            add("activity", f"Liked a post by @{who}", iso(_sld(e).get("timestamp")), f, f"index {i}", person=who, action="like")
    for f in _find(json_files, r"post_comments(_\d+)?\.json$"):
        check_cancel()
        d = _load(zf, f)
        items = d if isinstance(d, list) else d.get("comments_media_comments", [])
        for i, e in enumerate(items):
            check_cancel()
            m = e.get("string_map_data", {})
            who = fix_text((m.get("Media Owner") or {}).get("value"))
            found = True
            add("activity", f"Commented on @{who}'s post", iso((m.get("Time") or {}).get("timestamp")), f, f"index {i}",
                person=who, action="comment", text=fix_text((m.get("Comment") or {}).get("value")))
    if _find(json_files, r"(liked_posts|post_comments(_\d+)?)\.json$"):
        mark("activity", found)

    # interests: Instagram's own inferred topics
    for f in _find(json_files, r"your_topics\.json$"):
        check_cancel()
        d = _load(zf, f)
        topics = d.get("topics_your_topics", [])
        for i, e in enumerate(topics):
            check_cancel()
            name = fix_text((e.get("string_map_data", {}).get("Name") or {}).get("value"))
            if name:
                add("interest", f"Instagram thinks you like: {name}", None, f, f"index {i}", "inferred", "platform", topic=name)
        mark("interest", bool(topics))

    # accounts: advertisers using your data, off-Meta activity
    for f in _find(json_files, r"advertisers_using_your_activity_or_information\.json$"):
        check_cancel()
        d = _load(zf, f)
        for i, e in enumerate(d.get("ig_custom_audiences_all_types", [])):
            check_cancel()
            name = fix_text(e.get("advertiser_name"))
            if name:
                add("account", f"Advertiser holds your info: {name}", None, f, f"index {i}", domain=name, source="advertiser",
                    uploaded_list=bool(e.get("has_data_file_custom_audience")))
    for f in _find(json_files, r"your_activity_off_meta_technologies\.json$"):
        check_cancel()
        d = _load(zf, f)
        for i, e in enumerate(d.get("apps_and_websites_off_meta_activity", [])):
            check_cancel()
            name = fix_text(e.get("name"))
            events = e.get("events", [])
            last = max((ev.get("timestamp", 0) for ev in events), default=None)
            add("account", f"{name} sent Meta {len(events)} events about you", iso(last), f, f"index {i}",
                domain=name, source="off_meta", events=len(events))

    # location: login IPs
    for f in _find(json_files, r"login_activity\.json$"):
        check_cancel()
        d = _load(zf, f)
        logins = d.get("account_history_login_history", [])
        for i, e in enumerate(logins):
            check_cancel()
            m = e.get("string_map_data", {})
            ip = (m.get("IP Address") or {}).get("value")
            ts = (m.get("Time") or {}).get("timestamp")
            if ip:
                add("location", f"Login from IP {ip}", iso(ts), f, f"index {i}", ip=ip,
                    device=(m.get("User Agent") or {}).get("value"))
        mark("location", bool(logins))

    # messages: DMs (end-to-end encrypted chats may be missing from the export)
    for f in _find(json_files, r"inbox/[^/]+/message_\d+\.json$"):
        check_cancel()
        d = _load(zf, f)
        people = [fix_text(p.get("name")) for p in d.get("participants", [])]
        for i, m in enumerate(d.get("messages", [])):
            check_cancel()
            sender = fix_text(m.get("sender_name"))
            text = fix_text(m.get("content") or "")
            add("message", f"{sender}: {text[:80]}", iso(m.get("timestamp_ms")), f, f"index {i}",
                person=sender, thread=[p for p in people if p != owner_name], text=text,
                direction="out" if owner_name and sender == owner_name else "in")
        mark("contact", bool(people))

    if not recs:
        raise ParseError("wrong_format", "No Instagram data found in this zip", src)
    return recs, cov, owner_name
