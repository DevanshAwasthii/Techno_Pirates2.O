"""Scan local app metadata and optional Android permissions. Uses only stdlib.

Run: python -m scanner.scan [--android] [--output device_scan.json]
Only bounded .log/.txt pattern counts are retained; file text is never exported.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_LOG_FILES = 300
MAX_APPS = 30
WALK_SECONDS = 20
ADB_TIMEOUT = 8
EMAIL = re.compile(rb"(?i)(?<![\w.+-])[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}(?![\w.-])")
OCTET = rb"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
IPV4 = re.compile(rb"(?<![\d.])" + OCTET + rb"(?:\." + OCTET + rb"){3}(?![\d.])")
PHONE = re.compile(rb"(?<![\w+])(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\w)")
OPS = {"COARSE_LOCATION": "location", "FINE_LOCATION": "location", "CAMERA": "camera",
       "RECORD_AUDIO": "microphone", "READ_CONTACTS": "contacts"}


def _iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def scan_laptop(max_seconds=WALK_SECONDS):
    """Measure first-level app folders, without following symlinks or junctions.

    A deadline and inaccessible entries can make sizes lower bounds. The partial
    flag records that limitation instead of claiming a complete inventory.
    """
    start = time.monotonic()
    deadline = start + max(0, max_seconds)
    walk_deadline = start + max(0, max_seconds) * 0.75
    apps, candidates, roots, folders = [], {}, set(), []
    partial, recent = False, 0
    for variable in ("APPDATA", "LOCALAPPDATA"):
        raw = os.environ.get(variable)
        if not raw:
            continue
        root = Path(raw)
        key = os.path.normcase(os.path.abspath(root))
        if key in roots:
            continue
        roots.add(key)
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if time.monotonic() >= walk_deadline:
                        partial = True
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False) and not os.path.isjunction(entry.path):
                            folders.append(Path(entry.path))
                    except OSError:
                        partial = True
        except OSError:
            partial = True
    raw = os.environ.get("APPDATA")
    if raw:
        try:
            with os.scandir(Path(raw) / "Microsoft" / "Windows" / "Recent") as entries:
                for entry in entries:
                    if time.monotonic() >= walk_deadline:
                        partial = True
                        break
                    try:
                        if entry.name.lower().endswith(".lnk") and entry.is_file(follow_symlinks=False):
                            recent += 1
                    except OSError:
                        partial = True
        except OSError:
            pass
    folders.sort(key=lambda p: str(p).lower())
    for index, folder in enumerate(folders):
        now = time.monotonic()
        if now >= walk_deadline:
            partial = True
            break
        # Share the budget across folders and reserve time for bounded log counts.
        folder_deadline = now + (walk_deadline - now) / (len(folders) - index)
        total, count, modified = 0, 0, 0
        logs, stack = [], [folder]
        while stack and time.monotonic() < folder_deadline:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if time.monotonic() >= folder_deadline:
                            partial = True
                            break
                        try:
                            if entry.is_symlink() or os.path.isjunction(entry.path):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                stat = entry.stat(follow_symlinks=False)
                                total += stat.st_size
                                count += 1
                                modified = max(modified, stat.st_mtime)
                                if Path(entry.name).suffix.lower() in {".log", ".txt"} and stat.st_size <= MAX_LOG_BYTES:
                                    if len(logs) < MAX_LOG_FILES:
                                        logs.append(Path(entry.path))
                                    else:
                                        partial = True
                        except OSError:
                            partial = True
            except OSError:
                partial = True
        if stack or time.monotonic() >= folder_deadline:
            partial = True
        apps.append({"name": folder.name, "path": str(folder), "bytes": total,
                     "files": count, "last_modified": _iso(modified) if modified else None})
        candidates[str(folder)] = logs
    apps.sort(key=lambda app: (-app["bytes"], app["path"].lower()))
    apps = apps[:MAX_APPS]
    logs = []
    for app in apps:
        for path in candidates[app["path"]]:
            if len(logs) >= MAX_LOG_FILES or time.monotonic() >= deadline:
                partial = True
                break
            try:
                if path.is_symlink() or path.stat().st_size > MAX_LOG_BYTES:
                    continue
                with path.open("rb") as stream:
                    raw = stream.read(MAX_LOG_BYTES + 1)
                if len(raw) > MAX_LOG_BYTES:
                    continue
                counts = {"emails": sum(1 for _ in EMAIL.finditer(raw)),
                          "ips": sum(1 for _ in IPV4.finditer(raw)),
                          "phones": sum(1 for _ in PHONE.finditer(raw))}
                logs.append({"app": app["name"], "path": str(path), **counts})
                del raw
            except OSError:
                partial = True
    return {"apps": apps, "logs": logs, "recent_files": recent, "partial": partial or time.monotonic() >= deadline,
            "scan_seconds": round(time.monotonic() - start, 3)}


def _adb(*args):
    try:
        result = subprocess.run(["adb", *args], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=ADB_TIMEOUT, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except FileNotFoundError:
        raise RuntimeError("adb was not found. Install Android platform-tools and add adb to PATH.") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("adb timed out. Check the USB connection and unlock your Android device.") from None
    except subprocess.CalledProcessError:
        raise RuntimeError("adb command failed. Check USB debugging and device authorisation.") from None
    return result.stdout


def _access_time(value, now):
    stamp = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?", value)
    if stamp:
        try:
            parsed = datetime.fromisoformat(stamp.group().replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None
    duration = re.search(r"(?:\btime=[+-]?|\(-)(\d+(?:\.\d+)?(?:ms|[dhms])(?:\d+(?:\.\d+)?(?:ms|[dhms]))*)", value)
    if duration:
        parts = re.findall(r"(\d+(?:\.\d+)?)(ms|d|h|m|s)", duration.group(1))
        if parts:
            seconds = sum(float(number) * {"d": 86400, "h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit] for number, unit in parts)
            try:
                return (now - timedelta(seconds=seconds)).isoformat()
            except (ValueError, OverflowError):
                return None
    return None


def parse_appops(output, now=None):
    now = now or datetime.now(timezone.utc)
    access = dict.fromkeys(("location", "camera", "microphone", "contacts"))
    operation = None
    for line in output.splitlines():
        match = re.search(r"\b(" + "|".join(OPS) + r")\b\s*(?:\([^)]*\))?\s*:", line)
        if match:
            operation = OPS[match.group(1)]
        elif re.match(r"\s*[A-Z_]+\s*(?:\([^)]*\))?\s*:", line):
            operation = None
        if operation is None or line.lstrip().startswith("Reject:"):
            continue
        # Ignore duration= and rejectTime=; they are not last-access timestamps.
        when = _access_time(line, now) if "time=" in line or "Access:" in line else None
        if when and (access[operation] is None or when > access[operation]):
            access[operation] = when
    return access


def scan_android():
    try:
        devices = []
        states = []
        for line in _adb("devices").splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0] != "List":
                states.append(fields[1])
                if fields[1] == "device":
                    devices.append(fields[0])
        if not devices:
            reason = "Device is unauthorised; unlock it and accept the USB debugging prompt." if "unauthorized" in states else "No authorised Android device found. Enable USB debugging and connect a USB cable."
            raise RuntimeError(reason)
        device = sorted(devices)[0]
        packages = sorted({line.split(":", 1)[1].strip() for line in _adb("-s", device, "shell", "pm", "list", "packages", "-3").splitlines()
                           if re.fullmatch(r"package:[A-Za-z0-9_.]+", line.strip())})
        apps = []
        for package in packages:
            try:
                dump = _adb("-s", device, "shell", "dumpsys", "package", package)
                granted, runtime_indent = set(), None
                for line in dump.splitlines():
                    if "runtime permissions:" in line:
                        runtime_indent = len(line) - len(line.lstrip())
                        continue
                    if line.strip() and runtime_indent is not None and len(line) - len(line.lstrip()) <= runtime_indent:
                        runtime_indent = None
                    match = re.match(r"\s*(android\.permission\.[A-Z_]+):\s*granted=true\b", line)
                    if runtime_indent is not None and match:
                        granted.add(match.group(1))
                access = parse_appops(_adb("-s", device, "shell", "cmd", "appops", "get", package))
                apps.append({"package": package, "granted": sorted(granted), "last_access": access})
            except RuntimeError as exc:
                print(f"Android package {package}: {exc}", file=sys.stderr)
        return {"device": device, "apps": apps}
    except RuntimeError as exc:
        print(f"Android scan: {exc}", file=sys.stderr)
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android", action="store_true", help="Also scan an authorised adb device")
    parser.add_argument("--output", type=Path, default=Path("device_scan.json"))
    args = parser.parse_args(argv)
    result = {"scanned_at": datetime.now(timezone.utc).isoformat(), "laptop": scan_laptop(),
              "android": scan_android() if args.android else None}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
