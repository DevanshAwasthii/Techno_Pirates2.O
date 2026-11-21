"""iPhone App Privacy Report NDJSON: access events and network domains only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from app.engine.records import Record, ParseError, empty_coverage

CATEGORIES = {"location", "contacts", "photos", "camera", "microphone"}


def parse(path):
    path = Path(path)
    recs, cov = [], empty_coverage("ios")
    stats = {"bad_lines": 0, "ignored_lines": 0}
    namespace = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    with path.open(encoding="utf-8-sig", errors="replace") as stream:
        for number, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                stats["bad_lines"] += 1
                continue
            if not isinstance(row, dict):
                stats["bad_lines"] += 1
                continue
            timestamp = row.get("timeStamp") if isinstance(row.get("timeStamp"), str) else None
            if row.get("type") == "access":
                if row.get("kind") == "intervalEnd":
                    stats["ignored_lines"] += 1
                    continue
                accessor = row.get("accessor")
                app = accessor.get("identifier") if isinstance(accessor, dict) else None
                sensor = row.get("category")
                if not isinstance(app, str) or not app or not isinstance(sensor, str) or sensor not in CATEGORIES or row.get("kind") != "intervalBegin":
                    stats["bad_lines"] += 1
                    continue
                category = "location" if sensor == "location" else "device"
                item, meta = f"{app} accessed {sensor}", {"source": "sensor_access", "app": app, "sensor": sensor}
                if sensor == "location":
                    cov["location"] = "found"
                elif sensor == "contacts":
                    cov["contact"] = "found"
            elif row.get("type") == "networkActivity":
                app, domain = row.get("bundleID"), row.get("domain")
                if not isinstance(app, str) or not app or not isinstance(domain, str) or not domain:
                    stats["bad_lines"] += 1
                    continue
                try:
                    host = urlparse(domain if "://" in domain else "//" + domain).hostname
                except ValueError:
                    host = None
                if not host or any(c.isspace() for c in host):
                    stats["bad_lines"] += 1
                    continue
                try:
                    hits = max(0, int(row.get("hits", 1)))
                except (TypeError, ValueError, OverflowError):
                    hits = 0
                if not hits:
                    stats["bad_lines"] += 1
                    continue
                category, item = "device", f"{app} contacted {host} ({hits} hits)"
                meta = {"source": "ios_network", "app": app, "domain": host.lower().rstrip("."), "hits": hits}
                if isinstance(row.get("domainOwner"), str):
                    meta["domainOwner"] = row["domainOwner"]
            else:
                stats["ignored_lines"] += 1
                continue
            recs.append(Record(f"ios-{namespace}-{number:06d}", "ios", category, item, timestamp, "recorded", None,
                               path.name, f"line {number}", meta))
            cov["activity"] = "found"
    if not recs:
        raise ParseError("wrong_format", f"No App Privacy Report events found ({stats['bad_lines']} bad lines skipped)", path.name)
    return recs, cov, stats
