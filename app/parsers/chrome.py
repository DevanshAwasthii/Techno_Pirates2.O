"""Chrome / Edge profile parser: History, Cookies, Login Data, Preferences.

Reads only domains, names and counts. Never reads cookie values or password values.
Chrome locks these files while running, so they are copied to the project temp folder first.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.engine.records import Record, ParseError

PLATFORM = "chrome"
TMP = Path(__file__).resolve().parents[2] / ".cache" / "tmp"

# cookie-name prefix -> session replay vendor (records clicks, scrolls, typing)
REPLAY = {"_hj": "Hotjar", "_clck": "Microsoft Clarity", "_clsk": "Microsoft Clarity", "fs_uid": "FullStory",
          "_lr_": "LogRocket", "mf_": "Mouseflow", "_ce.": "Crazy Egg", "SL_C_": "Smartlook", "_uxa": "Contentsquare"}
# ponytail: small hand list of ad/analytics trackers; swap for a full blocklist (e.g. EasyPrivacy) when needed
TRACKERS = ("doubleclick.net", "google-analytics.com", "googletagmanager.com", "googlesyndication.com", "facebook.com",
            "facebook.net", "criteo.com", "criteo.net", "taboola.com", "outbrain.com", "scorecardresearch.com",
            "adnxs.com", "rubiconproject.com", "pubmatic.com", "amazon-adsystem.com", "bing.com", "clarity.ms",
            "hotjar.com", "quantserve.com", "moatads.com", "adsrvr.org", "linkedin.com", "twitter.com", "tiktok.com",
            "branch.io", "appsflyer.com", "mixpanel.com", "segment.io", "inmobi.com", "openx.net")
PERMS = {"geolocation": "location", "media_stream_camera": "camera", "media_stream_mic": "microphone",
         "notifications": "notifications"}


def default_profiles() -> list[Path]:
    """Chrome and Edge default profile folders on this Windows machine."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    cands = [local / "Google/Chrome/User Data/Default", local / "Microsoft/Edge/User Data/Default"]
    return [p for p in cands if (p / "History").exists()]


def is_profile(path: Path) -> bool:
    return path.is_dir() and (path / "History").exists()


def _webkit(us) -> str | None:
    if not us:
        return None
    return (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=int(us))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _host(url: str) -> str:
    h = (urlparse(url).hostname or url).lower().lstrip(".")
    return h[4:] if h.startswith("www.") else h


def _base(host: str) -> str:
    parts = host.lstrip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "net", "org", "ac", "gov") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _query(db: Path, sql: str):
    """Copy the (possibly locked) SQLite file, then read the copy."""
    TMP.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=TMP, suffix=".db"); os.close(fd)
    try:
        try:
            shutil.copyfile(db, tmp)
        except PermissionError:
            raise ParseError("unknown", f"{db.name} is locked. Close Chrome/Edge fully and try again.", str(db))
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()
    finally:
        Path(tmp).unlink(missing_ok=True)


def parse(profile: Path, src: str | None = None):
    profile = Path(profile)
    src = src or profile.name
    recs, n = [], 0
    cov = {"location": "not_assessed", "interest": "not_assessed", "contact": "not_assessed", "activity": "not_assessed"}

    def add(category, item, ts, file, ref, **meta):
        nonlocal n
        n += 1
        recs.append(Record(f"ch-{category[:4]}-{n:05d}", PLATFORM, category, item, ts, "recorded", None, file, ref, meta))

    hist = profile / "History"
    if hist.exists():
        rows = _query(hist, "SELECT url, visit_count, last_visit_time FROM urls")
        per = Counter(); last = {}
        for url, cnt, t in rows:
            h = _host(url)
            per[h] += cnt or 0
            last[h] = max(last.get(h, 0), t or 0)
        for h, cnt in per.most_common(50):
            add("activity", f"Visited {h} {cnt} times", _webkit(last[h]), "History", f"urls host={h}", domain=h, visits=cnt)
        for target, url, t in _query(hist, "SELECT target_path, tab_url, start_time FROM downloads"):
            add("activity", f"Downloaded {Path(target).name} from {_host(url or '')}", _webkit(t), "History",
                "downloads", domain=_host(url or ""), action="download")
        cov["activity"] = "found" if rows else "not_found"

    cookies = next((p for p in (profile / "Network" / "Cookies", profile / "Cookies") if p.exists()), None)
    if cookies:
        rows = _query(cookies, "SELECT host_key, name FROM cookies")
        trackers, replay = {}, {}
        for host, name in rows:
            base = _base(host)
            if base in TRACKERS:
                trackers.setdefault(base, set()).add(host)
            for pre, vendor in REPLAY.items():
                if name.startswith(pre):
                    replay.setdefault(_host(host), vendor)
        for base, hosts in sorted(trackers.items()):
            add("account", f"Tracker cookie from {base}", None, cookies.name, f"cookies host_key in {sorted(hosts)[:3]}",
                domain=base, source="tracker")
        for site, vendor in sorted(replay.items()):
            add("account", f"{site} records your session with {vendor}", None, cookies.name, f"cookies host_key={site}",
                domain=site, source="session_replay", vendor=vendor)

    logins = profile / "Login Data"
    if logins.exists():
        rows = _query(logins, "SELECT DISTINCT origin_url FROM logins")  # password_value is never selected
        for (url,) in rows:
            if url:
                d = _base(_host(url))
                add("account", f"Saved login for {d}", None, "Login Data", "logins origin_url", domain=d, source="saved_login")

    prefs = profile / "Preferences"
    if prefs.exists():
        exc = json.loads(prefs.read_text(encoding="utf-8")).get("profile", {}).get("content_settings", {}).get("exceptions", {})
        for key, label in PERMS.items():
            for pattern, v in exc.get(key, {}).items():
                if v.get("setting") == 1:  # 1 = allow
                    site = _host(pattern.split(",")[0].replace("[*.]", ""))
                    add("device", f"{site} can use your {label}", None, "Preferences", f"content_settings.{key}",
                        domain=site, permission=label)
        if any(r.meta.get("permission") == "location" for r in recs):
            cov["location"] = "found"

    if not recs:
        raise ParseError("wrong_format", "No browser data found in this folder", src)
    return recs, cov
