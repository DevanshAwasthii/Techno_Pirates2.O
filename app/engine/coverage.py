"""Source-level scan coverage. A finished check is not a whole-device audit."""
from __future__ import annotations

from math import isfinite


STATUS_LABELS = {"scanned": "Scanned", "partial": "Partial", "unavailable": "Unavailable",
                 "not_provided": "Not provided", "not_assessed": "Not assessed"}


def laptop_sources(path, data):
    rows = []
    laptop = data.get("laptop")
    if isinstance(laptop, dict):
        raw_scope = laptop.get("scope") if isinstance(laptop.get("scope"), dict) else {}
        scope = {}
        for key, value in raw_scope.items():
            if isinstance(value, bool):
                scope[key] = value
            elif isinstance(value, (int, float)) and isfinite(value) and value >= 0:
                scope[key] = value
        raw_apps = laptop.get("apps") if isinstance(laptop.get("apps"), list) else []
        raw_logs = laptop.get("logs") if isinstance(laptop.get("logs"), list) else []
        apps = [app for app in raw_apps if isinstance(app, dict) and isinstance(app.get("name"), str)][:30]
        logs = [log for log in raw_logs if isinstance(log, dict) and isinstance(log.get("path"), str) and log["path"]]
        storage_partial = bool(laptop.get("storage_partial", laptop.get("partial")))
        logs_partial = bool(laptop.get("logs_partial", laptop.get("partial")))
        reported = len(apps)
        measured = scope.get("folders_measured")
        selected = measured is not None and reported < measured
        storage_status = "partial" if storage_partial or selected else "scanned"
        detail = f"{reported} app folders reported. "
        if scope:
            detail += f"{scope.get('folders_complete', 0)} of {scope.get('folders_discovered', 0)} discovered folders fully measured; up to {scope.get('folder_limit', 30)} reported. "
            if scope.get("storage_time_limited"):
                detail += "Folder measurement reached its time budget. "
            if scope.get("storage_errors"):
                detail += f"{scope['storage_errors']} metadata access errors. "
            if not scope.get("roots_provided") or (not apps and scope.get("storage_errors")):
                storage_status = "unavailable"
            detail += f"Budget: {scope.get('budget_seconds', 20)}s. Symlinks/junctions are excluded."
        else:
            detail += "Original collection limits were not included in this report."
        if len(apps) < len(raw_apps):
            storage_status = "partial"
            detail += " Invalid or unreported app entries were excluded."
        if storage_partial:
            detail += " Storage sizes are lower bounds."
        rows.append({"name": "Laptop app-folder storage", "source": str(path), "platform": "device",
                     "kind": "device_storage", "status": storage_status, "records": reported, "detail": detail})
        detail = f"{len(logs)} log files checked for pattern counts; no matched values retained. "
        if scope:
            detail += f"Limits: {scope.get('log_limit', 300)} files, {scope.get('log_max_bytes', 2097152) / 1048576:g} MB each, within the reported app folders. "
            for key, label in (("logs_skipped_limit", "over the file-count limit"), ("logs_skipped_large", "over the size limit"),
                               ("logs_errors", "unreadable")):
                if scope.get(key):
                    detail += f"{scope[key]} files {label}. "
            if scope.get("logs_time_limited"):
                detail += "Log checks reached their time budget. "
            if storage_partial:
                detail += "Folder discovery was incomplete, so additional logs may exist."
        else:
            detail += "Original log-selection limits were not included in this report."
        if len(logs) < len(raw_logs):
            logs_partial = True
            detail += " Invalid log entries were excluded."
        rows.append({"name": "Laptop log pattern checks", "source": str(path), "platform": "device",
                     "kind": "device_logs", "status": "unavailable" if storage_status == "unavailable" else "partial" if logs_partial else "scanned",
                     "records": len(logs), "detail": detail})
        rows.append({"name": "Recent-file shortcut count", "source": str(path), "platform": "device",
                     "kind": "recent_files", "status": "partial" if scope.get("recent_errors") else "scanned" if scope.get("recent_checked") else "not_assessed",
                     "records": laptop.get("recent_files", 0),
                     "detail": "Shortcut count only; target files were not opened." if scope.get("recent_checked") else "The Recent folder was absent or a complete count was not recorded."})
    android = data.get("android")
    if isinstance(android, dict):
        apps = android.get("apps") if isinstance(android.get("apps"), list) else []
        rows.append({"name": "Android permission/access report", "source": str(path), "platform": "android",
                     "kind": "phone", "status": "partial" if android.get("partial") or android.get("errors") else "scanned", "records": len(apps),
                     "detail": f"Metadata for {len(apps)} apps imported. " +
                               (f"{len(android['errors'])} package checks failed. " if isinstance(android.get("errors"), list) and android["errors"] else "") +
                               "Null access times mean unknown; permission grants alone do not prove use."})
    return rows


def coverage_rows(result):
    rows = list(result.get("sourceCoverage") or [])
    records = result.get("records") or []
    expected = [
        ("Browser metadata", "chrome", any(r.get("platform") == "chrome" for r in rows),
         "No Chrome/Edge profile or supported browser export was provided or detected. Other browsers are not assessed."),
        ("Social interests", "interests", any(r.get("category") == "interest" for r in records),
         "Import your genuine account export to assess interests. This PC scan does not guess them."),
        ("People and relationships", "people", any((r.get("meta") or {}).get("person") for r in records),
         "Import your genuine social/chat exports to assess people. No relationships are guessed from PC metadata."),
        ("Chat-content checks", "messages", any(r.get("category") == "message" for r in records),
         "No chat contents were provided. A zero sensitive-hit count does not mean your chats contain no sensitive data."),
        ("Android sensor-access data", "android", "android" in (result.get("coverage") or {}),
         "No readable Android scan is available. An authorised ADB scan is optional."),
        ("iPhone privacy data", "ios", "ios" in (result.get("coverage") or {}),
         "No readable iPhone App Privacy Report was imported."),
    ]
    if not rows:
        rows.append({"name": "Source details", "source": "", "platform": "", "kind": "legacy",
                     "status": "not_assessed", "records": None,
                     "detail": "This result does not include source-level collection coverage. Run a fresh scan for details."})
    for name, platform, present, detail in expected:
        if not present and not any(row.get("name") == name and row.get("kind") == "missing" for row in rows):
            rows.append({"name": name, "source": "", "platform": platform, "kind": "missing",
                         "status": "not_provided", "records": None, "detail": detail})
    return rows


def audit_is_partial(result):
    if result.get("errors"):
        return True
    if any(row.get("status") in {"partial", "unavailable"} for row in result.get("sourceCoverage") or []):
        return True
    return any((r.get("meta") or {}).get("source") == "laptop_store" and (r.get("meta") or {}).get("partial")
               for r in result.get("records") or [])


def tracker_display(result):
    cookies = [row for row in result.get("sourceCoverage") or [] if row.get("kind") == "browser_cookies"]
    if not any(row.get("status") in {"scanned", "partial"} for row in cookies):
        return "Not assessed"
    value = str((result.get("summary") or {}).get("trackersFound", 0))
    return value + ("+" if any(row.get("status") != "scanned" for row in cookies) else "")


def chat_display(result):
    if not any(r.get("category") == "message" for r in result.get("records") or []):
        return "Not provided"
    return str((result.get("summary") or {}).get("sensitiveHits", 0))


def storage_display(result):
    storage = [row for row in result.get("sourceCoverage") or [] if row.get("kind") == "device_storage"]
    if not storage or all(row.get("status") in {"unavailable", "not_assessed"} for row in storage):
        return "Not assessed"
    size = (result.get("summary") or {}).get("laptopDataBytes", 0)
    partial = any(row.get("status") == "partial" for row in storage)
    if partial:
        return f"{size // 10_000_000 / 100:.2f}+"
    return f"{size / 1_000_000_000:.2f}"
