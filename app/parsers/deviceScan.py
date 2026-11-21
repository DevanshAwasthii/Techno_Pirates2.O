"""Read local device-scan metadata and counts, never the underlying app files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.engine.records import Record, ParseError, empty_coverage

SENSITIVE = {"android.permission.ACCESS_COARSE_LOCATION": "location", "android.permission.ACCESS_FINE_LOCATION": "location",
             "android.permission.CAMERA": "camera", "android.permission.RECORD_AUDIO": "microphone",
             "android.permission.READ_CONTACTS": "contacts", "android.permission.READ_MEDIA_IMAGES": "photos",
             "android.permission.READ_EXTERNAL_STORAGE": "photos"}


def count(value):
    try:
        return max(0, int(value)) if not isinstance(value, bool) else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def parse(path, data=None):
    path = Path(path)
    if data is None:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise ParseError("wrong_format", f"Invalid device scan JSON: {exc}", path.name) from None
    if not isinstance(data, dict) or not any(isinstance(data.get(k), dict) for k in ("laptop", "android")):
        raise ParseError("wrong_format", "No laptop or Android scan section found", path.name)
    recs, coverage = [], {}
    namespace = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    scanned = data.get("scanned_at") if isinstance(data.get("scanned_at"), str) else None

    def add(platform, category, item, ref, timestamp=scanned, **meta):
        recs.append(Record(f"ds-{namespace}-{len(recs) + 1:05d}", platform, category, item, timestamp,
                           "recorded", None, path.name, ref, meta))

    laptop = data.get("laptop")
    if isinstance(laptop, dict):
        coverage["device"] = empty_coverage("device")
        apps = laptop.get("apps") if isinstance(laptop.get("apps"), list) else []
        apps = sorted(((i, a) for i, a in enumerate(apps) if isinstance(a, dict) and isinstance(a.get("name"), str)), key=lambda pair: -count(pair[1].get("bytes")))[:30]
        for i, app in apps:
            size = count(app.get("bytes"))
            add("device", "device", f"{app['name']} holds {size / 1_000_000_000:.2f} GB of app data", f"laptop.apps[{i}] path={app.get('path', '')}",
                timestamp=app.get("last_modified") if isinstance(app.get("last_modified"), str) else scanned,
                source="laptop_store", app=app["name"], path=str(app.get("path") or ""), bytes=size,
                files=count(app.get("files")), partial=bool(app.get("partial", laptop.get("storage_partial", laptop.get("partial")))))
        logs = laptop.get("logs") if isinstance(laptop.get("logs"), list) else []
        for i, log in enumerate(logs):
            if not isinstance(log, dict):
                continue
            counts = {key: count(log.get(key)) for key in ("emails", "ips", "phones")}
            if not any(counts.values()):
                continue
            add("device", "device", f"{log.get('app', 'App')} log: {counts['emails']} email, {counts['ips']} IP, {counts['phones']} phone matches",
                f"laptop.logs[{i}]", source="device_log", app=str(log.get("app") or "App"), path=str(log.get("path") or ""), **counts)
            if counts["emails"] or counts["phones"]:
                coverage["device"]["contact"] = "found"
        recent = count(laptop.get("recent_files"))
        add("device", "device", f"{recent} recent-file shortcuts on this laptop", "laptop.recent_files", source="device_scan", recent_files=recent)
        if recent:
            coverage["device"]["activity"] = "found"
    android = data.get("android")
    if isinstance(android, dict):
        coverage["android"] = empty_coverage("android")
        apps = android.get("apps") if isinstance(android.get("apps"), list) else []
        for i, app in enumerate(apps):
            if not isinstance(app, dict) or not isinstance(app.get("package"), str) or not app["package"]:
                continue
            package = app["package"]
            grants = app.get("granted") if isinstance(app.get("granted"), list) else []
            sensors = sorted({SENSITIVE[p] for p in grants if isinstance(p, str) and p in SENSITIVE})
            if sensors:
                add("android", "device", f"{package} has sensitive permissions: {', '.join(sensors)}", f"android.apps[{i}].granted",
                    source="android_permissions", app=package, permissions=sensors, device=str(android.get("device") or "Android"))
            if "contacts" in sensors:
                coverage["android"]["contact"] = "found"
            access = app.get("last_access") if isinstance(app.get("last_access"), dict) else {}
            for sensor in ("location", "camera", "microphone", "contacts"):
                timestamp = access.get(sensor)
                if isinstance(timestamp, str) and timestamp:
                    add("android", "location" if sensor == "location" else "device", f"{package} accessed {sensor}",
                        f"android.apps[{i}].last_access.{sensor}", timestamp=timestamp, source="sensor_access", app=package, sensor=sensor)
                    coverage["android"]["activity"] = "found"
                    if sensor == "location":
                        coverage["android"]["location"] = "found"
    return recs, coverage
