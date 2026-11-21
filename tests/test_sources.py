import glob
from pathlib import Path

import pytest

from app import pipeline
from app.engine.messages import scan_text, person_key
from app.parsers import whatsapp, mbox

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = sorted(glob.glob(str(ROOT / "samples" / "persona_*")))


@pytest.fixture(scope="module")
def full():
    assert len(SAMPLES) >= 6, "run: python -m samples.make_persona"
    return pipeline.run(SAMPLES)


def titles(r):
    return [f["title"] for f in r["findings"]]


def test_all_platforms_parse_cleanly(full):
    assert full["errors"] == []
    assert set(full["coverage"]) == {"instagram", "whatsapp", "spotify", "gmail", "chrome", "device", "ios", "android"}


def test_email_discovery_counts_accounts_not_newsletters(full):
    t = next(x for x in titles(full) if "services have your email" in x)
    assert t.startswith("42 ")  # 41 subject matches + 1 found from the body; newsletters and personal mail excluded
    accounts = {r["meta"]["domain"] for r in full["records"] if r["platform"] == "gmail" and r["meta"]["source"] == "email"}
    assert "medium.com" not in accounts and "gmail.com" not in accounts
    assert "irctc.co.in" in accounts  # co.in handled as a second-level domain
    assert "zeptocafe.in" in accounts  # vague subject, "verify your email" in body


def test_newsletters_and_google_connections(full):
    t = titles(full)
    assert "4 mailing lists hold your email address" in t  # medium, swiggy promo, thehindu, producthunt
    g = next(f for f in full["findings"] if "connected to your Google account" in f["title"])
    assert g["title"].startswith("3 apps") and g["priority"] == "high"
    apps = {r["meta"]["domain"] for r in full["records"] if r["meta"].get("source") == "google_signin"}
    assert apps == {"Truecaller", "Canva", "QuizMaster Pro"}


def test_body_welcome_alone_is_not_an_account(tmp_path):
    p = tmp_path / "m.mbox"
    p.write_text("From a@shop.com Mon Jan 01 00:00:00 2024\nFrom: Shop <a@shop.com>\nSubject: Hi\n\nWelcome to our sale!\n\n"
                 "From b@app.io Mon Jan 01 00:00:00 2024\nFrom: App <b@app.io>\nSubject: Hi\n\nPlease confirm your email\n\n")
    doms = {r.meta["domain"] for r in mbox.parse(str(p))[0]}
    assert doms == {"app.io"}


def test_cross_platform_home_ip(full):
    t = next(x for x in titles(full) if "know your home network" in x)
    f = next(f for f in full["findings"] if f["title"] == t)
    assert set(f["platforms"]) == {"instagram", "spotify"}


def test_spotify_segments_cleaned(full):
    topics = [r["meta"]["topic"] for r in full["records"] if r["platform"] == "spotify" and r["category"] == "interest"]
    assert "Spotify Commuters" in topics and "Budget Conscious Shoppers" in topics


def test_card_not_counted_as_aadhaar():
    assert scan_text("card is 4111 1111 1111 1111 ok") == ["Card number"]
    assert scan_text("4521 8890 1234 is the number") == ["Aadhaar number"]


def test_people_merged_across_platforms(full):
    keys = [person_key(p["name"]) for p in full["summary"]["topPeople"]]
    assert len(keys) == len(set(keys))
    assert "arjundas" in keys[:3]


def test_whatsapp_formats_and_owner():
    android = "21/11/26, 10:15 pm - Arjun: hi\n21/11/26, 10:16 pm - Riya: line one\nline two"
    ios = "[11/21/26, 10:15:32 PM] Arjun: hi\n[11/21/26, 10:16:01 PM] Riya: yo"
    a, _ = whatsapp.parse_text(android, "WhatsApp Chat with Arjun.txt")
    b, _ = whatsapp.parse_text(ios, "_chat.txt")
    assert a[0].timestamp == "2026-11-21T22:15:00" and b[0].timestamp == "2026-11-21T22:15:32"
    assert a[1].meta["text"] == "line one\nline two"
    c, _ = whatsapp.parse_text("01/10/26, 9:00 pm - Riya: x\n01/10/26, 9:01 pm - Meera: y", "WhatsApp Chat with Meera.txt", 10)
    assert whatsapp.assign_owner(a + c) == "Riya"
    assert a[1].meta["direction"] == "out" and a[0].meta["direction"] == "in"


def test_not_whatsapp_rejected(tmp_path):
    p = tmp_path / "notes.txt"; p.write_text("just some notes\nnothing here")
    assert pipeline.run([p])["errors"][0]["code"] == "wrong_format"


def test_mbox_base_domain():
    assert mbox.base_domain("a@mail.instagram.com") == "instagram.com"
    assert mbox.base_domain("x@ticketadmin.irctc.co.in") == "irctc.co.in"
