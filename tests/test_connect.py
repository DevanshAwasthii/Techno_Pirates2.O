import os
import time

from app.connect import DownloadWatcher, matches, PLATFORMS


def test_matches_export_names():
    assert matches("instagram-riya-2026-11-22-abc.zip") == "Instagram"
    assert matches("Takeout-20261122T010101Z-001.zip") == "Google (Mail, Access Log Activity)"
    assert matches("my_spotify_data.zip") == "Spotify"
    assert matches("WhatsApp Chat with Arjun.txt") == "WhatsApp"
    assert matches("instagram-riya.zip.crdownload") is None  # still downloading
    assert matches("holiday.zip") is None


def test_every_platform_has_steps_and_patterns():
    for name, cfg in PLATFORMS.items():
        assert cfg["steps"] and cfg["patterns"], name


def test_waits_for_finished_download_and_reports_once(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    w = DownloadWatcher(tmp_path, now=time.time() - 5)
    f = tmp_path / "instagram-me.zip"
    f.write_bytes(b"x" * 10)
    assert w.poll() == []  # first sight: size not yet confirmed stable
    f.write_bytes(b"x" * 20)
    assert w.poll() == []  # still growing
    clock[0] = 2.99
    assert w.poll() == []
    clock[0] = 3.0
    assert w.poll() == [("Instagram", f)]  # stable for three seconds: report
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


def test_google_requests_only_supported_products_and_labels_exclusions():
    google = PLATFORMS["Google (Mail, Access Log Activity)"]
    assert google["steps"][0] == "Click 'Deselect all', then tick only: Mail and Access Log Activity."
    excluded = next(s for s in google["steps"] if s.startswith("Not analysed:"))
    assert all(product in excluded for product in ("Chrome Takeout", "YouTube", "My Activity", "other Takeout products"))
    assert "Facebook" not in PLATFORMS


def test_equal_size_different_content_both_offered_and_copies_deduplicated(tmp_path):
    from app.connect import recent_exports
    a = tmp_path / "takeout-a.zip"
    b = tmp_path / "takeout-b.zip"
    c = tmp_path / "takeout-c.zip"
    a.write_bytes(b"synthetic A")
    b.write_bytes(b"synthetic B")
    c.write_bytes(a.read_bytes())
    assert {p for _, p in recent_exports(tmp_path, set())} == {a, b}


def test_replaced_file_is_reported_after_new_stability_window(tmp_path, monkeypatch):
    from app.connect import file_key
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    w = DownloadWatcher(tmp_path, now=time.time() - 5)
    p = tmp_path / "spotify.zip"
    p.write_bytes(b"synthetic")
    assert w.poll() == []
    clock[0] = 3
    assert w.poll() == [("Spotify", p)]
    old_key, old_stamp = file_key(p), p.stat().st_mtime_ns
    p.write_bytes(b"different")  # same size, newer mtime
    os.utime(p, ns=(old_stamp + 1_000_000, old_stamp + 1_000_000))
    assert file_key(p) != old_key
    assert w.poll() == []
    clock[0] = 5.99
    assert w.poll() == []
    clock[0] = 6
    assert w.poll() == [("Spotify", p)]
    assert w.poll() == []
    p.write_bytes(b"different and larger")
    assert w.poll() == []
    clock[0] = 9
    assert w.poll() == [("Spotify", p)]

