"""Instagram 'Download your information' parser for the HTML format.

Most people pick HTML (the default), and re-requesting JSON costs hours, so HTML is read directly.
Every Instagram HTML page is a list of item boxes (div class contains '_a6-g'). Each box holds some of:
an <h2> title, links, 'label -> value' table rows (td._a6_q label, value nested or in td._a6_r) and a date
(div._a6-o or a date-looking text). Records use the same meta conventions as the JSON parser.
Structure verified on a real Nov 2026 export.
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from html.parser import HTMLParser

from app.engine.records import Record, ParseError

PLATFORM = "instagram"
DATE_RX = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4},? \d{1,2}:\d{2}(?::\d{2})? ?[ap]m$", re.I)


def parse_date(text: str) -> str | None:
    t = text.replace(",", "").strip().upper()
    for fmt in ("%b %d %Y %I:%M %p", "%b %d %Y %I:%M:%S %p", "%b %d %Y %I:%M%p"):
        try:
            return datetime.strptime(t, fmt).strftime("%Y-%m-%dT%H:%M:%S")  # export shows local time, no zone
        except ValueError:
            pass
    return None


class _Boxes(HTMLParser):
    """Collect outermost item boxes as dicts: title, links, fields, date, texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.boxes, self.box, self.depth = [], None, 0
        self.in_h2 = self.in_a = self.in_date = False
        self.href, self.label, self.td = None, None, None

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if tag == "div":
            if self.box is None and "_a6-g" in cls:
                self.box = {"title": "", "links": [], "fields": {}, "date": None, "texts": []}
                self.depth = 0
            if self.box is not None:
                self.depth += 1
                if "_a6-o" in cls:
                    self.in_date = True
        elif self.box is not None:
            if tag == "h2":
                self.in_h2 = True
            elif tag == "a":
                self.in_a, self.href = True, dict(attrs).get("href")
            elif tag == "td":
                self.td = "label" if "_a6_q" in cls else "value" if "_a6_r" in cls else None
                if self.td == "label":
                    self.label = None

    def handle_endtag(self, tag):
        if self.box is None:
            return
        if tag == "div":
            self.depth -= 1
            self.in_date = False
            if self.depth == 0:
                self.boxes.append(self.box)
                self.box = None
        elif tag == "h2":
            self.in_h2 = False
        elif tag == "a":
            self.in_a = False
        elif tag == "td":
            self.td = None

    def handle_data(self, data):
        t = data.strip()
        if not t or self.box is None:
            return
        b = self.box
        b["texts"].append(t)
        if self.in_h2:
            b["title"] = (b["title"] + " " + t).strip()
        if self.in_a:
            b["links"].append((t, self.href))
        if self.in_date or (DATE_RX.match(t) and not b["date"]):
            b["date"] = b["date"] or parse_date(t)
        if self.td == "label" and self.label is None:
            self.label = t
            b["fields"].setdefault(t, [])
        elif self.td in ("label", "value") and self.label is not None and t != self.label:
            b["fields"][self.label].append(t)


def boxes(html: str) -> list[dict]:
    p = _Boxes()
    p.feed(html)
    return p.boxes


def is_html_export(zf: zipfile.ZipFile) -> bool:
    """HTML when no recognised Instagram JSON data file exists; unrelated .json files don't count."""
    from app.parsers.instagram import INSTAGRAM_JSON
    names = zf.namelist()
    return not any(INSTAGRAM_JSON.search(n) for n in names) and any(n.endswith(".html") for n in names)


def parse(zf: zipfile.ZipFile, src: str = "instagram.zip"):
    names = [n for n in zf.namelist() if n.endswith(".html")]
    recs, n = [], 0
    cov = {"location": "not_assessed", "interest": "not_assessed", "contact": "not_assessed", "activity": "not_assessed"}

    def add(category, item, ts, file, ref, kind="recorded", origin=None, **meta):
        nonlocal n
        n += 1
        recs.append(Record(f"ih-{category[:4]}-{n:05d}", PLATFORM, category, item, ts, kind, origin,
                           file.rsplit("/", 1)[-1], ref, meta))

    def mark(cat, found):
        cov[cat] = "found" if found or cov[cat] == "found" else "not_found"

    def find(rx):
        return [x for x in names if re.search(rx, x)]

    def read(name):
        return boxes(zf.read(name).decode("utf-8", errors="replace"))

    def first(fields, *keys):
        for k in keys:
            v = fields.get(k)
            if v:
                return v[0]
        return None

    owner = None
    for f in find(r"/personal_information\.html$"):
        for b in read(f):
            owner = owner or first(b["fields"], "Name")

    for f in find(r"/followers_\d+\.html$"):
        bs = read(f)
        for i, b in enumerate(bs):
            who = b["links"][0][0] if b["links"] else b["title"]
            if who:
                add("contact", f"Follower: @{who}", b["date"], f, f"item {i + 1}", person=who, relation="follower")
        mark("contact", bool(bs))
    for f in find(r"/following\.html$"):
        bs = read(f)
        for i, b in enumerate(bs):
            who = b["links"][0][0] if b["links"] else b["title"]
            if who:
                add("contact", f"You follow @{who}", b["date"], f, f"item {i + 1}", person=who, relation="following")
        mark("contact", bool(bs))

    for f in find(r"/liked_posts\.html$"):
        bs = read(f)
        for i, b in enumerate(bs):
            who = first(b["fields"], "Username", "Owner") or b["title"]
            if who:
                add("activity", f"Liked a post by @{who}", b["date"], f, f"item {i + 1}", person=who, action="like")
            elif b["date"]:  # deleted/unavailable post: still a timestamped like for activity patterns
                add("activity", "Liked a post (owner not in export)", b["date"], f, f"item {i + 1}", action="like")
        mark("activity", bool(bs))
    for f in find(r"/post_comments(_\d+)?\.html$"):
        for i, b in enumerate(read(f)):
            who = first(b["fields"], "Media Owner")
            ts = parse_date(first(b["fields"], "Time") or "") or b["date"]
            add("activity", f"Commented on @{who}'s post", ts, f, f"item {i + 1}", person=who, action="comment",
                text=first(b["fields"], "Comment") or "")
            mark("activity", True)

    for f in find(r"/other_categories_used_to_reach_you\.html$"):
        topics = [v for b in read(f) for v in b["fields"].get("Name", [])]
        for i, t in enumerate(topics):
            add("interest", f"Instagram uses this category to reach you: {t}", None, f, f"value {i + 1}",
                "inferred", "platform", topic=t)
        mark("interest", bool(topics))

    for f in find(r"/advertisers_using_your_activity_or_information\.html$"):
        for b in read(f):
            for label, values in b["fields"].items():
                uploaded = "uploaded an audience list containing" in label
                for i, name in enumerate(dict.fromkeys(values)):
                    add("account", f"Advertiser holds your info: {name}", None, f, f"list '{label[:40]}...' entry {i + 1}",
                        domain=name, source="advertiser", uploaded_list=uploaded)

    for f in find(r"apps_and_websites/your_activity_off_meta_technologies\.html$"):
        for i, b in enumerate(read(f)):
            name = b["links"][0][0] if b["links"] else b["title"]
            if not name:
                continue
            detail = [x for x in names if "/your_activity_off_meta_technologies/" in x
                      and x.rsplit("/", 1)[-1].lower().startswith(re.sub(r"\W", "", name.lower())[:8])]
            events = len(read(detail[0])) if detail else 0
            add("account", f"{name} sent Meta {events} events about you" if events else f"{name} sent Meta data about you",
                None, f, f"item {i + 1}", domain=name, source="off_meta", events=events)

    found_loc = False
    for f in find(r"/login_activity\.html$"):
        for i, b in enumerate(read(f)):
            ip = first(b["fields"], "IP Address")
            if ip:
                found_loc = True
                add("location", f"Login from IP {ip}", parse_date(first(b["fields"], "Time") or "") or b["date"], f,
                    f"item {i + 1}", ip=ip, device=first(b["fields"], "User Agent"))
    for f in find(r"/last_known_location\.html$"):
        for b in read(f):
            lat = first(b["fields"], "Precise latitude", "Imprecise latitude")
            lon = first(b["fields"], "Precise longitude", "Imprecise longitude")
            if lat and lon:
                found_loc = True
                precise = bool(first(b["fields"], "Precise latitude"))
                add("location", f"Instagram stores your {'precise ' if precise else ''}last known location ({lat}, {lon})",
                    b["date"], f, "last known location", lat=lat, lon=lon, precise=precise, source="last_known_location")
    for f in find(r"/locations_of_interest\.html$"):
        for b in read(f):
            for i, place in enumerate(b["fields"].get("Locations of interest", [])):
                found_loc = True
                add("location", f"Instagram thinks you're interested in: {place}", None, f, f"value {i + 1}",
                    "inferred", "platform", place=place, source="location_of_interest")
    if find(r"/(login_activity|last_known_location|locations_of_interest)\.html$"):
        mark("location", found_loc)

    threads = {}
    for f in find(r"/inbox/[^/]+/message_\d+\.html$"):
        threads.setdefault(f.split("/inbox/")[1].split("/")[0], []).append((f, read(f)))
    # The profile 'Name' often differs from the display name on messages (verified on a real export),
    # so the owner is the sender present in most threads when the profile name isn't a sender.
    in_threads = {}
    for parts in threads.values():
        for s in {b["title"] for _, bs in parts for b in bs if b["title"]}:
            in_threads[s] = in_threads.get(s, 0) + 1
    if in_threads and owner not in in_threads and len(threads) > 1:
        top = max(in_threads, key=in_threads.get)
        owner = top if in_threads[top] >= max(2, len(threads) // 2) else owner
    for thread, parts in threads.items():
        senders = sorted({b["title"] for _, bs in parts for b in bs if b["title"]})
        for f, bs in parts:
            for i, b in enumerate(bs):
                sender = b["title"]
                body = " ".join(t for t in b["texts"] if t != sender and not DATE_RX.match(t))
                add("message", f"{sender}: {body[:80]}", b["date"], f, f"item {i + 1}", person=sender,
                    thread=[s for s in senders if s != owner], text=body, chat=thread,
                    direction="out" if owner and sender == owner else "in")
        mark("contact", True)

    if not recs:
        raise ParseError("wrong_format", "No Instagram data found in this HTML export", src)
    return recs, cov, owner
