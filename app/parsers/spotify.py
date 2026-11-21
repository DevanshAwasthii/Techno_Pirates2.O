"""Spotify 'Download your data' parser: Account data zip and Extended streaming history zip."""
from __future__ import annotations

from app.cancellation import check_cancel

import json
import re
import zipfile
from datetime import datetime

from app.engine.records import Record, ParseError

PLATFORM = "spotify"


def is_spotify_zip(zf: zipfile.ZipFile) -> bool:
    return any(re.search(r"(StreamingHistory|Streaming_History_Audio|Inferences\.json|Userdata\.json)", n) for n in zf.namelist())


def clean_segment(s: str) -> str:
    """'1P_Custom_Spotify_Commuters' -> 'Spotify Commuters'; '3P_Bollywood Fans' -> 'Bollywood Fans'."""
    s = re.sub(r"^\d?P_?(Custom_)?", "", s)
    return re.sub(r"[_]+", " ", s).strip()


def parse(zf: zipfile.ZipFile, src: str = "spotify.zip"):
    recs, n = [], 0
    cov = {"location": "not_assessed", "interest": "not_assessed", "contact": "not_assessed", "activity": "not_assessed"}

    def add(category, item, ts, file, ref, kind="recorded", origin=None, **meta):
        nonlocal n
        n += 1
        recs.append(Record(f"sp-{category[:4]}-{n:05d}", PLATFORM, category, item, ts, kind, origin, file, ref, meta))

    names = zf.namelist()
    for f in [x for x in names if x.endswith("Inferences.json")]:
        check_cancel()
        segs = json.load(zf.open(f)).get("inferences", [])
        for i, s in enumerate(segs):
            check_cancel()
            add("interest", f"Spotify ad segment: {clean_segment(s)}", None, f, f"index {i}", "inferred", "platform",
                topic=clean_segment(s), raw=s)
        cov["interest"] = "found" if segs else "not_found"

    for f in [x for x in names if re.search(r"StreamingHistory\w*_\d+\.json$", x)]:
        check_cancel()
        for i, e in enumerate(json.load(zf.open(f))):
            check_cancel()
            ts = datetime.strptime(e["endTime"], "%Y-%m-%d %H:%M").strftime("%Y-%m-%dT%H:%M:00Z")
            add("activity", f"Played {e.get('trackName')} by {e.get('artistName')}", ts, f, f"index {i}",
                artist=e.get("artistName"), ms=e.get("msPlayed"))
        cov["activity"] = "found"

    for f in [x for x in names if re.search(r"Streaming_History_Audio_.*\.json$", x)]:
        check_cancel()
        ips_seen = set()
        for i, e in enumerate(json.load(zf.open(f))):
            check_cancel()
            add("activity", f"Played {e.get('master_metadata_track_name')} on {e.get('platform')}", e.get("ts"), f, f"index {i}",
                artist=e.get("master_metadata_album_artist_name"), ms=e.get("ms_played"))
            ip = e.get("ip_addr") or e.get("ip_addr_decrypted")
            if ip and ip not in ips_seen:  # one location record per distinct IP keeps evidence readable
                ips_seen.add(ip)
                add("location", f"Streamed from IP {ip} ({e.get('conn_country')})", e.get("ts"), f, f"index {i}",
                    ip=ip, country=e.get("conn_country"))
        cov["activity"] = "found"
        cov["location"] = "found" if ips_seen else "not_found"

    if not recs:
        raise ParseError("wrong_format", "No Spotify data found in this zip", src)
    return recs, cov
