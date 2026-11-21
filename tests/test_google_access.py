import io
import zipfile

from app import pipeline

ACT = ("Takeout/Access Log Activity/Activities - A list of Google services accessed by your devices.csv")
DEV = "Takeout/Access Log Activity/Devices - A list of devices which have accessed your Google account.csv"
ACT_HEAD = ("Gaia ID,Activity Timestamp,IP Address,Proxiedhost IP Address,Is Non-routable IP Address,Activity Country,"
            "Activity Region,Activity City,User Agent String,Product Name,Sub-Product Name,Activity Type,Gmail Access Channel\n")
DEV_HEAD = "Device Type,Brand Name,Marketing Name,OS,OS Version,Device Model,User Given Name,Device Last Location,Gaia ID\n"


def _zip(tmp_path, act_rows, dev_rows, city=""):
    p = tmp_path / "takeout-20260101T000000Z-001.zip"
    act = ACT_HEAD + "".join(
        f"1,2026-01-0{d} 1{h}:00:00 UTC,{ip},,{nr},,,{city},UA,Gmail,Sync,,\n" for d, h, ip, nr in act_rows)
    dev = DEV_HEAD + "".join(f"{t},{b},{m},Android,14,{m},,{loc},1\n" for t, b, m, loc in dev_rows)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(ACT, act)
        z.writestr(DEV, dev)
    return p


def test_access_log_summarised_not_one_record_per_row(tmp_path):
    rows = [(1, 1, "49.37.1.1", "No")] * 50 + [(2, 3, "103.2.2.2", "No")] * 5 + [(3, 4, "10.0.0.1", "Yes")]
    r = pipeline.run([_zip(tmp_path, rows, [("PHONE", "Samsung", "Galaxy S23", "49.37.1.1")])])
    assert r["errors"] == []
    ips = [x for x in r["records"] if x["category"] == "location" and x["meta"].get("ip")]
    assert {x["meta"]["ip"]: x["meta"]["count"] for x in ips} == {"49.37.1.1": 50, "103.2.2.2": 5}  # non-routable skipped
    assert len(r["records"]) < 20  # 56 rows summarised
    t = [f["title"] for f in r["findings"]]
    assert "Google logged your account activity from 2 IP addresses" in t  # no '0 places' when city blank
    assert "1 device has accessed your Google account" in t
    assert r["coverage"]["google"]["location"] == "found" and r["coverage"]["google"]["activity"] == "found"


def test_city_columns_used_when_present(tmp_path):
    r = pipeline.run([_zip(tmp_path, [(1, 1, "49.37.1.1", "No")], [], city="Kolkata")])
    assert any(f["title"].endswith("in 1 place") for f in r["findings"])


def test_access_log_ip_links_with_other_platforms(tmp_path):
    from pathlib import Path
    sp = Path(__file__).resolve().parents[1] / "samples" / "persona_spotify.zip"  # synthetic, uses 49.37.12.88
    r = pipeline.run([_zip(tmp_path, [(1, 1, "49.37.12.88", "No")] * 3, []), sp])
    home = next(f for f in r["findings"] if "know your home network" in f["title"])
    assert {"google", "spotify"} <= set(home["platforms"])
