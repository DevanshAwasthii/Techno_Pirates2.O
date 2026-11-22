"""Chrome / Edge profile parser: History, Cookies, Login Data, Preferences.

Reads only domains, names and counts. Never reads cookie values or password values.
Databases and SQLite side files are copied to a short-lived local folder and queried read-only.
Copies are removed on success or failure; locked sources are reported.
"""
from __future__ import annotations

from app.cancellation import check_cancel

import json
import os
import hashlib
import sqlite3
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.engine.records import Record, ParseError

PLATFORM = "chrome"
from app.paths import ROOT

TMP = ROOT / ".cache" / "tmp"

# cookie-name prefix -> session replay vendor (records clicks, scrolls, typing)
REPLAY = {"_hj": "Hotjar", "_clck": "Microsoft Clarity", "_clsk": "Microsoft Clarity", "fs_uid": "FullStory",
          "_lr_": "LogRocket", "mf_": "Mouseflow", "_ce.": "Crazy Egg", "SL_C_": "Smartlook", "_uxa": "Contentsquare"}
# ponytail: small hand list of ad/analytics trackers; swap for a full blocklist (e.g. EasyPrivacy) when needed
TRACKERS = ("doubleclick.net", "google-analytics.com", "googletagmanager.com", "googlesyndication.com", "facebook.com",
            "facebook.net", "criteo.com", "criteo.net", "taboola.com", "outbrain.com", "scorecardresearch.com",
            "adnxs.com", "rubiconproject.com", "pubmatic.com", "amazon-adsystem.com", "bing.com", "clarity.ms",
            "hotjar.com", "quantserve.com", "moatads.com", "adsrvr.org", "linkedin.com", "twitter.com", "x.com", "tiktok.com",
            "branch.io", "appsflyer.com", "mixpanel.com", "segment.io", "inmobi.com", "openx.net")
PERMS = {"geolocation": "location", "media_stream_camera": "camera", "media_stream_mic": "microphone",
         "notifications": "notifications"}


def default_profiles() -> list[Path]:
    """Find existing Chrome/Edge Default and numbered profiles on this PC."""
    raw = os.environ.get("LOCALAPPDATA")
    if not raw:
        return []
    profiles = []
    for relative in ("Google/Chrome/User Data", "Microsoft/Edge/User Data"):
        check_cancel()
        try:
            with os.scandir(Path(raw) / relative) as entries:
                for entry in entries:
                    check_cancel()
                    name = entry.name
                    if name != "Default" and not (name.startswith("Profile ") and name[8:].isdigit()):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False) and (Path(entry.path) / "History").is_file():
                            profiles.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(profiles, key=lambda p: str(p).lower())


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
    """Query a local snapshot including committed writes still in SQLite side files."""
    TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="browser-", dir=TMP) as folder:
        snapshot = Path(folder) / db.name
        shutil.copy2(db, snapshot)
        for suffix in ("-wal", "-shm", "-journal"):
            check_cancel()
            side = db.with_name(db.name + suffix)
            if side.exists():
                shutil.copy2(side, snapshot.with_name(snapshot.name + suffix))
        con = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()


def parse(profile: Path, src: str | None = None, warnings=None, source_coverage=None):
    profile = Path(profile)
    live = src is None
    namespace = "ch-" + hashlib.sha256(str(profile.resolve()).encode()).hexdigest()[:12] if live else "ch"
    src = src or profile.name
    recs, n = [], 0
    failed_sources = set()
    states = {}
    browser = "Edge" if "Edge" in profile.parts else "Chrome"
    cov = {"location": "not_assessed", "interest": "not_assessed", "contact": "not_assessed", "activity": "not_assessed"}

    def add(category, item, ts, file, ref, **meta):
        nonlocal n
        n += 1
        source = str(profile / file) if live else file
        meta["profile_id"] = namespace if live else f"{src}/{profile.name}"
        if live:
            meta["live_profile"] = True
        recs.append(Record(f"{namespace}-{category[:4]}-{n:05d}", PLATFORM, category, item, ts, "recorded", None, source, ref, meta))

    def source_row(db, kind):
        key = str(db)
        if key not in states:
            states[key] = {"name": f"{browser} {profile.name} - {db.name}", "source": key,
                           "platform": "chrome", "kind": kind, "status": "not_provided",
                           "records": 0, "metadata_rows": 0, "detail": "Source file was not found."}
        return states[key]

    def query(db, sql):
        kind = {"History": "browser_history", "Cookies": "browser_cookies", "Login Data": "browser_logins"}.get(db.name, "browser_metadata")
        row = source_row(db, kind)
        try:
            rows = _query(db, sql)
            row["status"] = "partial" if str(db) in failed_sources else "scanned"
            row["metadata_rows"] += len(rows)
            if str(db) not in failed_sources:
                row["detail"] = f"{row['metadata_rows']} metadata rows read. " + ("Visit history is summarised to the top 50 domains; downloads are included." if db.name == "History" else "Only supported metadata fields were selected.")
            return rows
        except (OSError, sqlite3.Error) as exc:
            previously_read = row["status"] in {"scanned", "partial"}
            failed_sources.add(str(db))
            row["status"] = "partial" if previously_read else "unavailable"
            row["detail"] = str(exc)
            if warnings is None:
                raise ParseError("unknown", f"Cannot read browser metadata: {exc}", str(db)) from None
            from scanner.browser_access import describe_failure
            warning = {"code": "unknown", "file": str(db), **describe_failure(db, exc)}
            row["detail"] = warning["message"]
            if warning not in warnings:
                warnings.append(warning)
            return []

    hist = profile / "History"
    if hist.exists():
        rows = query(hist, "SELECT url, visit_count, last_visit_time FROM urls")
        per = Counter(); last = {}
        for url, cnt, t in rows:
            check_cancel()
            h = _host(url)
            per[h] += cnt or 0
            last[h] = max(last.get(h, 0), t or 0)
        for h, cnt in per.most_common(50):
            check_cancel()
            add("activity", f"Visited {h} {cnt} times", _webkit(last[h]), "History", f"urls host={h}", domain=h, visits=cnt)
        for target, url, t in query(hist, "SELECT target_path, tab_url, start_time FROM downloads"):
            check_cancel()
            add("activity", f"Downloaded {Path(target).name} from {_host(url or '')}", _webkit(t), "History",
                "downloads", domain=_host(url or ""), action="download")
        cov["activity"] = "found" if rows else "not_assessed" if str(hist) in failed_sources else "not_found"

    cookies = next((p for p in (profile / "Network" / "Cookies", profile / "Cookies") if p.exists()), None)
    if cookies:
        rows = query(cookies, "SELECT host_key, name FROM cookies")
        trackers, replay = {}, {}
        for host, name in rows:
            check_cancel()
            base = _base(host)
            if base in TRACKERS:
                trackers.setdefault(base, set()).add(host)
            for pre, vendor in REPLAY.items():
                check_cancel()
                if name.startswith(pre):
                    replay.setdefault(_host(host), vendor)
        for base, hosts in sorted(trackers.items()):
            check_cancel()
            add("account", f"Tracker cookie from {base}", None, str(cookies.relative_to(profile)) if live else cookies.name, f"cookies host_key in {sorted(hosts)[:3]}",
                domain=base, source="tracker")
        for site, vendor in sorted(replay.items()):
            check_cancel()
            item = f"{site} has a cookie associated with {vendor}; may use session-recording tools"
            add("account", item, None, str(cookies.relative_to(profile)) if live else cookies.name, f"cookies host_key={site}",
                domain=site, source="session_replay", vendor=vendor)

    logins = profile / "Login Data"
    if logins.exists():
        rows = query(logins, "SELECT DISTINCT origin_url FROM logins")  # password_value is never selected
        for (url,) in rows:
            check_cancel()
            if url:
                d = _base(_host(url))
                add("account", f"Saved login for {d}", None, "Login Data", "logins origin_url", domain=d, source="saved_login")

    prefs = profile / "Preferences"
    if prefs.exists():
        row = source_row(prefs, "browser_permissions")
        try:
            data = json.loads(prefs.read_text(encoding="utf-8"))
            exc = data.get("profile", {}).get("content_settings", {}).get("exceptions", {})
            if not isinstance(exc, dict):
                raise ValueError("Browser permission exceptions are not an object")
            skipped = 0
            for key, label in PERMS.items():
                check_cancel()
                values = exc.get(key, {})
                if not isinstance(values, dict):
                    skipped += 1
                    continue
                for pattern, value in values.items():
                    check_cancel()
                    if not isinstance(pattern, str) or not isinstance(value, dict):
                        skipped += 1
                        continue
                    if value.get("setting") == 1:
                        site = _host(pattern.split(",")[0].replace("[*.]", ""))
                        add("device", f"{site} can use your {label}", None, "Preferences", f"content_settings.{key}",
                            domain=site, permission=label)
            row["status"] = "partial" if skipped else "scanned"
            row["detail"] = "Checked location, camera, microphone and notification permissions. Other preferences were not assessed."
            if skipped:
                row["detail"] += f" {skipped} malformed entries skipped."
            if any(r.meta.get("permission") == "location" for r in recs):
                cov["location"] = "found"
        except (OSError, ValueError, AttributeError) as exc:
            row["status"], row["detail"] = "unavailable", f"Browser permissions unavailable: {exc}"
            if warnings is None:
                raise ParseError("unknown", row["detail"], str(prefs)) from None
            warnings.append({"code": "unknown", "file": str(prefs), "message": row["detail"]})
    source_row(hist, "browser_history")
    source_row(cookies or profile / "Network" / "Cookies", "browser_cookies")
    source_row(logins, "browser_logins")
    source_row(prefs, "browser_permissions")
    if source_coverage is not None:
        for row in states.values():
            check_cancel()
            row["records"] = sum(r.sourceFile == row["source"] if live else Path(r.sourceFile).name == Path(row["source"]).name for r in recs)
            source_coverage.append(row)

    if not recs and warnings is None:
        raise ParseError("wrong_format", "No browser data found in this folder", src)
    return recs, cov
