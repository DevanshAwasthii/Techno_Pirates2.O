"""Instagram HTML export: synthetic pages shaped like a real Nov 2026 export (no personal data)."""
import os
import time
import zipfile

from app import pipeline
from app.connect import recent_exports, file_key
from app.engine.messages import scan_text

BOX = '<div class="pam _3-95 _2ph- _a6-g uiBoxWhite noborder">{}</div>'
H2 = '<h2 class="_3-95 _2pim _a6-h _a6-i">{}</h2>'
DATE = '<div class="_3-94 _a6-o">{}</div>'


def row(label, value):
    return f'<tr><td class="_2pin _a6_q">{label}<div><div>{value}</div></div></td></tr>'


def page(*boxes):
    return "<html><body>" + "".join(boxes) + "</body></html>"


def msg(sender, text, date):
    return BOX.format(H2.format(sender) + f'<div class="_3-95 _a6-p"><div><div></div><div>{text}</div></div></div>' + DATE.format(date))


def build(tmp_path):
    p = tmp_path / "instagram-tester-2026-11-21-abc.zip"
    ig = "your_instagram_activity"
    files = {
        "personal_information/personal_information/personal_information.html":
            page(BOX.format("<table>" + row("Name", "Profile Name") + "</table>")),
        "connections/followers_and_following/followers_1.html":
            page(BOX.format('<div class="_a6-p"><div><div><a href="https://instagram.com/a">arjun.das</a></div><div>Nov 2, 2026 9:15 pm</div></div></div>')),
        f"{ig}/likes/liked_posts.html": page(
            BOX.format(H2.format("x") + '<div class="_3-95 _a6-p"><table>' + row("Username", "meera_k") + "</table></div>" + DATE.format("Nov 3, 2026 11:40 pm")),
            BOX.format(DATE.format("Nov 4, 2026 1:05 am"))),
        "ads_information/instagram_ads_and_businesses/advertisers_using_your_activity_or_information.html": page(BOX.format(
            "<table>" + row("Advertisers that have uploaded an audience list containing entries that were matched to your Instagram profile",
                            "Myntra</div><div>Swiggy")
            + row("Advertisers who have uploaded an audience list that was matched to your profile based on interactions", "Nykaa") + "</table>")),
        "security_and_login_information/login_and_profile_creation/login_activity.html": page(BOX.format(
            H2.format("2026-11-20") + "<table>" + row("IP Address", "49.37.1.1") + '<tr><td class="_2pin _a6_q">Time</td><td class="_2pin _2piu _a6_r">Nov 20, 2026 10:00 pm</td></tr></table>')),
        "security_and_login_information/login_and_profile_creation/last_known_location.html": page(BOX.format(
            "<table>" + row("Precise latitude", "22.5") + row("Precise longitude", "88.3") + "</table>")),
        f"{ig}/messages/inbox/arjun_1/message_1.html": page(
            msg("Riya S", "my number 9876543210", "Nov 5, 2026 9:00 pm"),
            msg("Arjun", "see https://www.instagram.com/reel/9876543210123 lol", "Nov 5, 2026 9:01 pm")),
        f"{ig}/messages/inbox/meera_2/message_1.html": page(
            msg("Riya S", "hi", "Nov 6, 2026 9:00 pm"), msg("Meera", "hey", "Nov 6, 2026 9:02 pm")),
    }
    with zipfile.ZipFile(p, "w") as z:
        for name, html in files.items():
            z.writestr(name, html)
    return p


def test_html_export_parses_like_json(tmp_path):
    r = pipeline.run([build(tmp_path)])
    assert r["errors"] == []
    t = [f["title"] for f in r["findings"]]
    assert "3 advertisers target you with your own data" in t
    assert "Instagram stores your precise last known location" in t
    assert any(x.startswith("Your phone number appears in 1 message") for x in t)  # reel id in link not counted
    recs = r["records"]
    assert sum(1 for x in recs if x["meta"].get("action") == "like") == 2  # incl. like with deleted owner
    adv = {x["meta"]["domain"]: x["meta"]["uploaded_list"] for x in recs if x["meta"].get("source") == "advertiser"}
    assert adv == {"Myntra": True, "Swiggy": True, "Nykaa": False}
    login = next(x for x in recs if x["meta"].get("ip") == "49.37.1.1")
    assert login["timestamp"] == "2026-11-20T22:00:00"


def test_owner_inferred_when_profile_name_differs(tmp_path):
    r = pipeline.run([build(tmp_path)])
    d = {(x["meta"]["person"], x["meta"]["direction"]) for x in r["records"] if x["category"] == "message"}
    assert ("Riya S", "out") in d and ("Arjun", "in") in d


def test_links_never_scanned_for_numbers():
    assert scan_text("https://instagram.com/reel/98765432101 and www.x.com/9123456789") == []
    assert scan_text("call 9123456789") == ["Phone number"]


def test_recent_exports_offer(tmp_path):
    a = tmp_path / "takeout-1.zip"; a.write_bytes(b"x" * 5)
    dup = tmp_path / "takeout-1 (1).zip"; dup.write_bytes(b"x" * 5)
    old = tmp_path / "instagram-old.zip"; old.write_bytes(b"x")
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    found = recent_exports(tmp_path, set())
    assert [p.name for _, p in found] == ["takeout-1 (1).zip"] or [p.name for _, p in found] == ["takeout-1.zip"]
    assert len(found) == 1  # duplicate download offered once, old file skipped
    assert recent_exports(tmp_path, {file_key(found[0][1])} | {file_key(dup), file_key(a)}) == []
