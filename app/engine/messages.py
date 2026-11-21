"""Sensitive-data detection in message text and closeness scoring."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# Order matters: longest first. Card (16) before Aadhaar (12) before phone (10); taken spans are not re-counted.
PATTERNS = {
    "Card number": re.compile(r"(?<!\d)(?<!\d[ -])(?:\d{4}[ -]?){3}\d{4}(?![ -]?\d)"),
    "Aadhaar number": re.compile(r"(?<!\d)(?<!\d )[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![ -]?\d)"),
    "PAN number": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "Phone number": re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)"),
    "Email address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "OTP / password": re.compile(r"\b(?:otp|password|passcode|pin)\b\D{0,15}\S{4,}", re.I),
    "Bank account / IFSC": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
}


def scan_text(text: str) -> list[str]:
    """Return labels of sensitive data found in text. Each span counts once (longest pattern first)."""
    if not text:
        return []
    # links carry long digit ids (reels, posts, tracking) that look like phone/card numbers; never scan inside them
    text = re.sub(r"(?:https?://|www\.)\S+", " ", text)
    hits, taken = [], []
    for label, rx in PATTERNS.items():
        for m in rx.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append(m.span())
            hits.append(label)
    return hits


# ponytail: hand-picked weights, tune with real data; a DM signals more closeness than a like
WEIGHTS = {"message": 3, "comment": 2, "like": 1, "tag": 3, "status_view": 2, "friend_like": 1, "status_post": 1}


def person_key(name: str) -> str:
    """'Arjun Das', 'arjun.das' and 'arjun_das' are the same person across platforms.
    ponytail: name-based merge; wrong for two different people with the same name, add a manual merge list if needed."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def closeness(records) -> list[dict]:
    """Rank people by interaction signals across platforms (names merged by person_key)."""
    score = Counter()
    signals = defaultdict(Counter)
    evidence = defaultdict(list)
    display, platforms = {}, defaultdict(set)
    for r in records:
        for n in [r.meta.get("person")] + list(r.meta.get("thread", [])):
            if n:
                display.setdefault(person_key(n), n)
    for r in records:
        person = r.meta.get("person")
        if not person:
            continue
        if r.category == "message" and r.meta.get("direction") == "out":
            targets = r.meta.get("thread", [])
        else:
            targets = [person]
        kind = "message" if r.category == "message" else r.meta.get("action")
        if kind not in WEIGHTS:
            continue
        for p in targets:
            k = person_key(p)
            score[k] += WEIGHTS[kind]; signals[k][kind] += 1; evidence[k].append(r.id); platforms[k].add(r.platform)
    return [{"name": display[k], "score": s, "signals": dict(signals[k]), "platforms": sorted(platforms[k]),
             "evidence": evidence[k][:200]} for k, s in score.most_common(25)]

