"""Screen-recording / screenshot OCR for what feeds show you about friends.

Video (.mp4 .mov .mkv .avi) or images (.png .jpg) -> 1 frame per second -> skip near-duplicate frames
-> on-device OCR (RapidOCR, offline) -> pattern match:
  Instagram feed / Reels Friends tab: "Liked by X and N others", "X liked this", "X reacted"
  WhatsApp Status: posters in the Updates list, "Viewed by N" and viewer names on your own status
Names are snapped to known people from the other exports (rapidfuzz), fixing OCR typos.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import process, fuzz

from app.engine.records import Record, ParseError

VIDEO = {".mp4", ".mov", ".mkv", ".avi"}
IMAGE = {".png", ".jpg", ".jpeg"}
MAX_SECONDS = 300  # ponytail: tested limit for a phone recording; raise after timing longer clips
_engine = None


def _ocr():
    global _engine
    if _engine is None:  # model load takes a few seconds, do it once
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


THUMB = (90, 160)  # w, h: keeps text strokes visible, unlike a 16x16 whole-screen hash
PIXEL_DELTA = 40  # grey levels; video compression noise stays well below this
CHANGED_FRACTION = 0.001  # ~14 thumbnail pixels: one changed word in a header is enough


def _thumb(frame):
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), THUMB, interpolation=cv2.INTER_AREA)


def _changed(a, b) -> bool:
    """True when any part of the screen changed meaningfully (local text change counts, global noise does not)."""
    return (cv2.absdiff(a, b) > PIXEL_DELTA).mean() > CHANGED_FRACTION


def frames(path: Path):
    """Yield (second, frame) for distinct frames only."""
    if path.suffix.lower() in IMAGE:
        img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)  # fromfile handles non-ASCII paths
        if img is None:
            raise ParseError("wrong_format", "Cannot read this image", path.name)
        yield 0, img
        return
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ParseError("wrong_format", "Cannot open this video", path.name)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    if total > MAX_SECONDS:
        cap.release()
        raise ParseError("too_large", f"Recording is {int(total)} s; keep it under {MAX_SECONDS // 60} minutes", path.name)
    last, sec = None, 0
    try:
        while sec <= total:
            cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
            ok, f = cap.read()
            if not ok:
                break
            t = _thumb(f)
            if last is None or _changed(t, last):
                last = t
                yield sec, f
            sec += 1
    finally:
        cap.release()


def read_lines(frame) -> list[str]:
    result, _ = _ocr()(frame)
    if not result:
        return []
    rows = sorted(result, key=lambda r: (r[0][0][1], r[0][0][0]))  # top-to-bottom, left-to-right
    return [r[1].strip() for r in rows if r[2] > 0.5 and r[1].strip()]


LIKED_BY = re.compile(r"liked by\s+@?([\w.]+)(?:\s+and\s+(\d[\d,]*)\s+others)?", re.I)
X_LIKED = re.compile(r"^@?([\w.]+)\s+(liked|reacted to|commented on|shared)\b", re.I)
VIEWED_BY = re.compile(r"viewed by\s+(\d+)", re.I)
TIME_LINE = re.compile(r"^(today|yesterday|\d+\s*(minutes?|hours?|mins?|h|m)\s*ago|\d{1,2}:\d{2}\s*[ap]m)", re.I)
NOISE = {"my status", "updates", "status", "recent updates", "viewed updates", "channels", "reels", "friends", "home",
         "search", "following", "for you", "today", "yesterday", "liked by", "viewed by"}


def status_name(line: str) -> bool:
    return (1 <= len(line) <= 41 and line[0].isalpha()
            and all(unicodedata.category(c)[0] in "LMN" or c in " .'-\u200c\u200d" for c in line))


def snap(name: str, known: list[str]) -> str:
    if not known:
        return name
    hit = process.extractOne(name, known, scorer=fuzz.WRatio, score_cutoff=85)
    return hit[0] if hit else name


def parse(path: Path, known_people: list[str] | None = None):
    path = Path(path)
    known = list(known_people or [])
    recs, n, seen = [], 0, set()
    # per-source namespace: two recordings of the same platform must not produce the same record id
    tag = hashlib.sha1(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:6]
    all_text = []

    def add(platform, item, sec, **meta):
        nonlocal n
        key = (platform, item)
        if key in seen:  # the same line visible across consecutive frames counts once
            return
        seen.add(key)
        n += 1
        recs.append(Record(f"oc-{platform[:2]}-{tag}-{n:05d}", platform, "activity", item, None, "recorded", None,
                           path.name, f"frame at {sec}s", meta))

    for sec, f in frames(path):
        lines = read_lines(f)
        all_text += lines
        text = " ".join(lines).lower()
        is_status = "viewed by" in text or "my status" in text or "recent updates" in text
        if is_status:
            mine = "viewed by" in text
            for i, line in enumerate(lines):
                if line.lower() in NOISE or TIME_LINE.match(line) or VIEWED_BY.search(line):
                    continue
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if TIME_LINE.match(nxt) and status_name(line):
                    who = snap(line, known)
                    if mine:
                        add("whatsapp", f"{who} viewed your status ({nxt})", sec, person=who, action="status_view", capture="ocr")
                    else:
                        add("whatsapp", f"{who} posted a status ({nxt})", sec, person=who, action="status_post", capture="ocr")
            for m in VIEWED_BY.finditer(text):
                add("whatsapp", f"Your status was viewed by {m.group(1)} people", sec, action="status_views_total",
                    views=int(m.group(1)), capture="ocr")
            continue
        for line in lines:
            m = LIKED_BY.search(line)
            if m:
                who = snap(m.group(1), known)
                others = int(m.group(2).replace(",", "")) if m.group(2) else 0
                add("instagram", f"Feed showed: liked by {who}" + (f" and {others} others" if others else ""), sec,
                    person=who, action="friend_like", others=others, capture="ocr")
                continue
            m = X_LIKED.match(line)
            if m and m.group(1).lower() not in NOISE:
                who = snap(m.group(1), known)
                add("instagram", f"Feed showed: {who} {m.group(2).lower()} a post", sec,
                    person=who, action="friend_like", capture="ocr")

    if not recs:
        raise ParseError("wrong_format", "No friend activity or status text found in this recording", path.name)
    return recs, {"location": "not_assessed", "interest": "not_assessed", "contact": "found", "activity": "found"}
