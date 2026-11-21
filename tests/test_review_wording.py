"""Synthetic evidence must not turn indicators into proven collection or identity."""
import pytest
from app.engine.records import Record
from app.engine.rules import build_findings


def record(i, platform, category, **meta):
    return Record(str(i), platform, category, "Synthetic observation", None, meta=meta)


@pytest.mark.parametrize("live", [False, True])
def test_cookie_wording_is_origin_independent_and_counts_distinct_sites(live):
    records = [record(i, "chrome", "account", source="session_replay", domain="site.test", vendor="Synthetic vendor", live_profile=live) for i in range(3)]
    findings, summary = build_findings(records)
    f = findings[0]
    assert f.metric == {"value": 1, "unit": "sites"}
    assert "may use session-recording tools" in f.title
    assert "1 distinct vendors" in f.detail and "does not prove" in f.detail
    assert summary["sessionRecorders"] == 1


@pytest.mark.parametrize("direction", ["in", "out", None])
def test_chat_patterns_do_not_assign_ownership_or_platform_readability(direction):
    findings, _ = build_findings([record(1, "whatsapp", "message", text="person@example.test", direction=direction)])
    f = next(f for f in findings if f.category == "message")
    assert "pattern appears in imported messages" in f.title
    assert "Your" not in f.title and "yours" not in f.detail
    assert "does not establish platform access to encrypted chats" in f.detail


def test_ip_and_social_claims_are_limited_to_observations():
    records = [record(1, "instagram", "location", ip="192.0.2.1"), record(2, "spotify", "location", ip="192.0.2.1"),
               record(3, "whatsapp", "message", group=True, chat="Synthetic group", senders=["Observer", "Contact"], person="Contact", text="hello"),
               record(4, "instagram", "activity", person="Contact", action="friend_like", capture="ocr"),
               record(5, "whatsapp", "activity", person="Contact", action="status_view")]
    findings, _ = build_findings(records)
    shared = next(f for f in findings if f.layer == 4)
    assert shared.title == "Same IP seen by 2 platforms"
    assert all(word in shared.detail for word in ("inference", "VPN", "shared", "mobile"))
    assert not any(word in shared.detail for word in ("household", "city", "home"))
    group = next(f for f in findings if "observed participants" in f.title)
    assert group.metric["value"] == 2 and "lower bound" in group.detail and "privacy settings" in group.detail
    assert any("Most interactions with" in f.title for f in findings)
    assert all("closest to" not in f.detail and "Every like" not in f.detail and "inner circle" not in f.detail for f in findings)
