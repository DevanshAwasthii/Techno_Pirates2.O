"""WhatsApp 'Export chat' parser (.txt, or .zip containing _chat.txt / 'WhatsApp Chat with X.txt').

Handles Android ("21/11/26, 10:15 pm - Name: text") and iPhone ("[21/11/26, 10:15:32 PM] Name: text"),
12h/24h clocks, D/M vs M/D date order (detected per file), multi-line messages, system lines.
Owner (the exporting user) is not named in the file; the pipeline infers it across chats.
"""
from __future__ import annotations

import re
from datetime import datetime

from app.engine.records import Record, ParseError

PLATFORM = "whatsapp"
LINE = re.compile(
    r"^‎?\[?(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{2,4}),?\s+"
    r"(?P<t>\d{1,2}:\d{2}(?::\d{2})?)(?:[\s ]*(?P<ap>[aApP]\.?\s?[mM]\.?))?\]?\s*(?:-\s*)?"
    r"(?P<rest>.*)$"
)


def looks_like_whatsapp(text: str) -> bool:
    lines = [l for l in text.splitlines()[:30] if l.strip()]
    return sum(bool(LINE.match(l)) for l in lines) >= max(2, len(lines) // 2)


def _day_first(matches) -> bool:
    for d, m in matches:
        if int(d) > 12:
            return True
        if int(m) > 12:
            return False
    return True  # India default


def _ts(g, day_first) -> str | None:
    d, m = (g["d"], g["m"]) if day_first else (g["m"], g["d"])
    y = int(g["y"]); y += 2000 if y < 100 else 0
    t = g["t"] if g["t"].count(":") == 2 else g["t"] + ":00"
    hh, mm, ss = map(int, t.split(":"))
    ap = (g["ap"] or "").lower().replace(".", "").replace(" ", "")
    if ap == "pm" and hh < 12:
        hh += 12
    elif ap == "am" and hh == 12:
        hh = 0
    try:
        return datetime(y, int(m), int(d), hh, mm, ss).strftime("%Y-%m-%dT%H:%M:%S")  # local time, no zone in export
    except ValueError:
        return None


def chat_name(filename: str) -> str:
    m = re.search(r"WhatsApp Chat (?:with|-)\s*(.+?)(?:\.txt)?$", filename)
    return m.group(1).strip() if m else filename.rsplit("/", 1)[-1].removesuffix(".txt")


def parse_text(text: str, src: str, start_id: int = 0):
    """Return (records, chat_meta). Direction is set later by the pipeline once the owner is known."""
    if not looks_like_whatsapp(text):
        raise ParseError("wrong_format", "Not a WhatsApp chat export", src)
    raw = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            raw.append([m.groupdict(), m.group("rest")])
        elif raw:
            raw[-1][1] += "\n" + line  # continuation of a multi-line message
    day_first = _day_first((g["d"], g["m"]) for g, _ in raw)
    name = chat_name(src)
    msgs = []
    for g, rest in raw:
        if ": " not in rest:
            continue  # system line without a sender
        sender, body = rest.split(": ", 1)
        sender = sender.strip().lstrip("‎~ ").strip()
        if len(sender) > 60:  # a sentence, not a name: system line that happened to contain ": "
            continue
        msgs.append((sender, body.strip(), _ts(g, day_first)))
    senders = sorted({s for s, _, _ in msgs})
    is_group = len(senders) > 2
    recs = []
    for i, (sender, body, ts) in enumerate(msgs):
        recs.append(Record(f"wa-mess-{start_id + i + 1:05d}", PLATFORM, "message", f"{sender} in {name}: {body[:80]}", ts,
                           sourceFile=src, recordRef=f"message {i + 1}",
                           meta={"person": sender, "chat": name, "group": is_group, "senders": senders, "text": body}))
    return recs, {"chat": name, "senders": senders, "group": is_group}


def assign_owner(records):
    """Owner = the sender present in the most chats. Sets direction and thread on every WhatsApp record."""
    chats = {}
    for r in records:
        chats.setdefault(r.meta["chat"], set(r.meta["senders"]))
    if not chats:
        return None
    counts = {}
    for s in chats.values():
        for p in s:
            counts[p] = counts.get(p, 0) + 1
    owner = max(counts, key=counts.get) if len(chats) > 1 else None
    for r in records:
        others = [p for p in r.meta["senders"] if p != owner]
        r.meta["thread"] = others
        r.meta["direction"] = "out" if owner and r.meta["person"] == owner else "in"
    return owner
