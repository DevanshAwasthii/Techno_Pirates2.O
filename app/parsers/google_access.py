"""Google Takeout > Access Log Activity: devices and account activity log (CSV).

The activity log can hold 100k+ rows, so it is summarised instead of one record per row:
one location record per distinct IP, one activity record per Google product, and one activity
record per (date, hour) bucket for the heatmap. Each record keeps its row count and source file.
"""
from __future__ import annotations

from app.cancellation import check_cancel

import csv
import io
import zipfile
from collections import Counter, defaultdict

from app.engine.records import Record

PLATFORM = "google"
ACT = "Activities - "
DEV = "Devices - "


def has_access_logs(zf: zipfile.ZipFile) -> bool:
    return any("Access Log Activity/" in n and n.endswith(".csv") for n in zf.namelist())


def _rows(zf, name):
    with zf.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline=""))


def _iso(ts: str) -> str | None:
    """'2026-11-20 18:22:01 UTC' -> '2026-11-20T18:22:01Z'."""
    ts = (ts or "").strip().removesuffix(" UTC")
    return ts.replace(" ", "T") + "Z" if len(ts) >= 19 else None


def parse(zf: zipfile.ZipFile, src: str = "takeout.zip"):
    recs, n = [], 0
    cov = {"location": "not_found", "interest": "not_assessed", "contact": "not_assessed", "activity": "not_found"}

    def add(category, item, ts, file, ref, **meta):
        nonlocal n
        n += 1
        recs.append(Record(f"go-{category[:4]}-{n:05d}", PLATFORM, category, item, ts, "recorded", None, file, ref, meta))

    for name in [x for x in zf.namelist() if "Access Log Activity/" in x and x.rsplit("/", 1)[-1].startswith(DEV)]:
        check_cancel()
        short = name.rsplit("/", 1)[-1][:40]
        for i, r in enumerate(_rows(zf, name)):
            check_cancel()
            label = " ".join(x for x in (r.get("Brand Name"), r.get("Marketing Name") or r.get("Device Model")) if x) or r.get("Device Type") or "Device"
            add("device", f"{label} ({r.get('OS', '')} {r.get('OS Version', '')}) accessed your Google account".replace("  ", " "),
                None, short, f"row {i + 2}", device=label, device_type=r.get("Device Type"))
            loc = (r.get("Device Last Location") or "").strip()
            if loc:
                add("location", f"Last location of {label}: {loc}", None, short, f"row {i + 2}", place=loc, device=label)
                cov["location"] = "found"

    for name in [x for x in zf.namelist() if "Access Log Activity/" in x and x.rsplit("/", 1)[-1].startswith(ACT)]:
        check_cancel()
        short = name.rsplit("/", 1)[-1][:40]
        ips = defaultdict(lambda: {"n": 0, "first": None, "last": None, "place": "", "row": 0})
        products, hours = Counter(), Counter()
        total = 0
        for i, r in enumerate(_rows(zf, name)):
            check_cancel()
            total += 1
            ts = _iso(r.get("Activity Timestamp"))
            ip = (r.get("IP Address") or "").strip()
            if ip and (r.get("Is Non-routable IP Address") or "").lower() not in ("true", "yes"):
                s = ips[ip]
                s["n"] += 1
                s["row"] = s["row"] or i + 2
                if ts:
                    s["first"] = min(filter(None, (s["first"], ts)))
                    s["last"] = max(filter(None, (s["last"], ts)))
                s["place"] = s["place"] or ", ".join(x for x in (r.get("Activity City"), r.get("Activity Region"), r.get("Activity Country")) if x)
            products[(r.get("Product Name") or "Unknown").strip()] += 1
            if ts:
                hours[ts[:13]] += 1  # 'YYYY-MM-DDTHH'
        for ip, s in sorted(ips.items(), key=lambda kv: -kv[1]["n"]):
            check_cancel()
            add("location", f"Google saw you at IP {ip} ({s['place'] or 'unknown place'}) {s['n']} times", s["last"], short,
                f"first row {s['row']}", ip=ip, place=s["place"], count=s["n"], first=s["first"])
        for prod, c in products.most_common():
            check_cancel()
            add("activity", f"{c} account activities logged for {prod}", None, short, "Product Name column", product=prod, count=c)
        for hour, c in sorted(hours.items()):
            check_cancel()
            add("activity", f"{c} Google account activities in this hour", hour + ":00:00Z", short, "hourly summary", count=c)
        if total:
            cov["activity"] = "found"
        if ips:
            cov["location"] = "found"
    return recs, cov
