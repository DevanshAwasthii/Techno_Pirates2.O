"""Connect wizard data and Downloads auto-pickup.

No platform offers an API for personal exports, so the wizard opens the exact request page,
shows what to tick, and the watcher imports the export as soon as the browser finishes downloading it.
"""
from __future__ import annotations

import fnmatch
import time
from pathlib import Path

PLATFORMS = {
    "Instagram": {
        "url": "https://accountscenter.instagram.com/info_and_permissions/dyi/",
        "patterns": ["instagram-*.zip", "meta-*.zip"],
        "steps": [
            "Click 'Download or transfer information' and choose your Instagram account.",
            "Choose 'Some of your information' and tick: Your Instagram activity, Connections, Personal information, "
            "Ads information, Apps and websites off of Instagram, Preferences, Security and login information.",
            "Choose 'Download to device'.",
            "Date range: All time. Format: JSON (not HTML). Media quality: Low.",
            "Click 'Create files'. When Meta emails you, download the zip - NexData imports it automatically.",
        ],
    },
    "Google (Mail, Access Log Activity)": {
        "url": "https://takeout.google.com/",
        "patterns": ["takeout-*.zip"],
        "steps": [
            "Click 'Deselect all', then tick only: Mail and Access Log Activity.",
            "Next step: Export once, .zip, 2 GB. Click 'Create export'.",
            "Download the zip from Google's email - NexData imports it automatically.",
            "Not analysed: Chrome Takeout, YouTube and YouTube Music, My Activity, and other Takeout products. Only supported Mail and Access Log Activity contents are analysed.",
        ],
    },
    "Spotify": {
        "url": "https://www.spotify.com/account/privacy/",
        "patterns": ["my_spotify_data*.zip", "spotify*.zip"],
        "steps": [
            "Under 'Download your data' tick 'Account data' (and 'Extended streaming history' for IP addresses).",
            "Click 'Request data', then click the confirmation link Spotify emails you.",
            "Download the zip when it arrives (up to 5 days) - NexData imports it automatically.",
        ],
    },
    "WhatsApp": {
        "url": "",
        "patterns": ["WhatsApp Chat*.txt", "WhatsApp Chat*.zip"],
        "steps": [
            "On your phone open a chat > menu (Android) or contact name (iPhone) > Export chat > Without media.",
            "Send it to this laptop (email, Drive or USB) and save it in Downloads - NexData imports it automatically.",
        ],
    },
}
PARTIAL = (".crdownload", ".part", ".partial", ".tmp", ".download")


def matches(name: str) -> str | None:
    """Platform whose export filename pattern matches, else None. Case-insensitive."""
    low = name.lower()
    if low.endswith(PARTIAL):
        return None
    for platform, cfg in PLATFORMS.items():
        if any(fnmatch.fnmatch(low, p.lower()) for p in cfg["patterns"]):
            return platform
    return None


class DownloadWatcher:
    """Poll a folder; report each export once, only after its size stops changing (download finished).

    Files already present when watching starts are ignored, so old exports are never re-imported unasked.
    ponytail: polling every few seconds, not OS file events; fine for one Downloads folder.
    """

    def __init__(self, folder: Path, now: float | None = None):
        self.folder = Path(folder)
        self.started = time.time() if now is None else now
        self.sizes: dict[Path, int] = {}
        self.reported: set[Path] = set()

    def poll(self) -> list[tuple[str, Path]]:
        ready = []
        try:
            entries = list(self.folder.iterdir())
        except OSError:
            return ready
        for p in entries:
            if p in self.reported or not p.is_file():
                continue
            platform = matches(p.name)
            if not platform:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < self.started:
                continue
            if self.sizes.get(p) == st.st_size and st.st_size > 0:
                self.reported.add(p)
                ready.append((platform, p))
            else:
                self.sizes[p] = st.st_size  # first sight or still growing: check again next poll
        return ready


def file_key(p: Path) -> str:
    """Identity of one downloaded export: same name re-downloaded with new content counts as new."""
    st = p.stat()
    return f"{p.name}|{st.st_size}|{int(st.st_mtime)}"


def recent_exports(folder: Path, imported: set[str], days: int = 7, now: float | None = None) -> list[tuple[str, Path]]:
    """Finished exports downloaded in the last `days` that were never imported. Duplicate copies (same size) once."""
    now = time.time() if now is None else now
    out, sizes = [], set()
    try:
        entries = sorted(Path(folder).iterdir(), key=lambda p: p.name)
    except OSError:
        return out
    for p in entries:
        platform = matches(p.name)
        if not platform or not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size == 0 or now - st.st_mtime > days * 86400 or file_key(p) in imported:
            continue
        if (platform, st.st_size) in sizes:  # 'takeout-x.zip' and 'takeout-x (1).zip' downloaded twice
            continue
        sizes.add((platform, st.st_size))
        out.append((platform, p))
    return out


def downloads_folder() -> Path:
    return Path.home() / "Downloads"
