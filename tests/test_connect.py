import os
import time

from app.connect import DownloadWatcher, matches, PLATFORMS


def test_matches_export_names():
    assert matches("instagram-riya-2026-11-22-abc.zip") == "Instagram"
    assert matches("Takeout-20261122T010101Z-001.zip") == "Google (Gmail, Chrome, YouTube)"
    assert matches("my_spotify_data.zip") == "Spotify"
    assert matches("WhatsApp Chat with Arjun.txt") == "WhatsApp"
    assert matches("instagram-riya.zip.crdownload") is None  # still downloading
    assert matches("holiday.zip") is None


def test_every_platform_has_steps_and_patterns():
    for name, cfg in PLATFORMS.items():
        assert cfg["steps"] and cfg["patterns"], name


def test_waits_for_finished_download_and_reports_once(tmp_path):
    w = DownloadWatcher(tmp_path, now=time.time() - 5)
    f = tmp_path / "instagram-me.zip"
    f.write_bytes(b"x" * 10)
    assert w.poll() == []  # first sight: size not yet confirmed stable
    f.write_bytes(b"x" * 20)
    assert w.poll() == []  # still growing
    assert w.poll() == [("Instagram", f)]  # stable: report
    assert w.poll() == []  # never twice


def test_ignores_old_files_partials_and_empty(tmp_path):
    old = tmp_path / "instagram-old.zip"
    old.write_bytes(b"x")
    past = time.time() - 3600
    os.utime(old, (past, past))
    w = DownloadWatcher(tmp_path, now=time.time() - 60)
    (tmp_path / "takeout-1.zip.crdownload").write_bytes(b"x")
    empty = tmp_path / "takeout-2.zip"
    empty.write_bytes(b"")
    for _ in range(3):
        assert w.poll() == []


def test_missing_folder_is_harmless(tmp_path):
    assert DownloadWatcher(tmp_path / "nope").poll() == []
