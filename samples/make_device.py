"""Deterministic laptop/Android scan and iPhone privacy-report demo exports."""
from pathlib import Path
import json

SAMPLES = Path(__file__).resolve().parent
STAMP = "2026-11-21T10:00:00+00:00"


def main():
    scan = {"scanned_at": STAMP, "laptop": {
        "apps": [{"name": name, "path": path, "bytes": size, "files": files, "last_modified": STAMP}
                 for name, path, size, files in (
                     ("WhatsApp", r"C:\Users\Riya\AppData\Local\WhatsApp", 2_400_000_000, 842),
                     ("Google", r"C:\Users\Riya\AppData\Local\Google", 1_800_000_000, 2150),
                     ("Spotify", r"C:\Users\Riya\AppData\Roaming\Spotify", 600_000_000, 530))],
        "logs": [{"app": "WhatsApp", "path": r"C:\Users\Riya\AppData\Local\WhatsApp\logs\app.log", "emails": 4, "ips": 6, "phones": 3},
                 {"app": "Google", "path": r"C:\Users\Riya\AppData\Local\Google\debug.log", "emails": 0, "ips": 12, "phones": 0},
                 {"app": "Spotify", "path": r"C:\Users\Riya\AppData\Roaming\Spotify\client.log", "emails": 0, "ips": 0, "phones": 0}],
        "recent_files": 27, "partial": False},
        "android": {"device": "Demo Android - Riya", "apps": [
            {"package": "in.swiggy.android", "granted": ["android.permission.ACCESS_FINE_LOCATION", "android.permission.CAMERA"],
             "last_access": {"location": "2026-11-20T17:10:00+00:00", "camera": None, "microphone": None, "contacts": None}},
            {"package": "com.truecaller", "granted": ["android.permission.READ_CONTACTS", "android.permission.RECORD_AUDIO", "android.permission.ACCESS_COARSE_LOCATION"],
             "last_access": {"location": "2026-11-19T08:30:00+00:00", "camera": None, "microphone": "2026-11-20T10:30:00+00:00", "contacts": STAMP}},
            {"package": "net.one97.paytm", "granted": ["android.permission.ACCESS_FINE_LOCATION"],
             "last_access": {"location": "2026-10-01T09:00:00+00:00", "camera": None, "microphone": None, "contacts": None}}]}}
    (SAMPLES / "persona_device_scan.json").write_text(json.dumps(scan, indent=1) + "\n", encoding="utf-8")
    rows = []
    for app, sensor in (("com.burbn.instagram", "location"), ("net.whatsapp.WhatsApp", "contacts"),
                        ("in.swiggy.Swiggy", "location"), ("com.truecaller.Truecaller", "contacts"),
                        ("com.burbn.instagram", "camera"), ("net.whatsapp.WhatsApp", "microphone")):
        rows.append({"type": "access", "accessor": {"identifier": app}, "category": sensor, "kind": "intervalBegin", "timeStamp": STAMP})
        rows.append({"type": "access", "accessor": {"identifier": app}, "category": sensor, "kind": "intervalEnd", "timeStamp": STAMP})
    for app, domain, owner, hits in (("com.burbn.instagram", "graph.facebook.com", "Meta", 42),
                                     ("in.swiggy.Swiggy", "api.appsflyer.com", "AppsFlyer", 15),
                                     ("in.swiggy.Swiggy", "events.uxcam.com", "UXCam", 8),
                                     ("com.truecaller.Truecaller", "api.branch.io", "Branch", 11),
                                     ("net.whatsapp.WhatsApp", "whatsapp.net", "WhatsApp", 22)):
        rows.append({"type": "networkActivity", "bundleID": app, "domain": domain, "domainOwner": owner,
                     "hits": hits, "timeStamp": STAMP, "context": "foreground"})
    rows.append({"type": "access", "accessor": {"identifier": "com.old.location"}, "category": "location", "kind": "intervalBegin", "timeStamp": "2026-10-01T09:00:00+00:00"})
    (SAMPLES / "persona_ios_privacy.ndjson").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    print("Created persona_device_scan.json and persona_ios_privacy.ndjson")


if __name__ == "__main__":
    main()
