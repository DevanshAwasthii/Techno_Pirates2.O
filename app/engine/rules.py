"""Turn records into prioritised findings, each with evidence and exact steps.

Steps reflect app menus as of Nov 2026; the presenter verifies them on real apps.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from app.engine.records import Finding
from app.engine.messages import scan_text, closeness

IG_CENTER = "https://accountscenter.instagram.com/"


def build_findings(records) -> tuple[list[Finding], dict]:
    by = defaultdict(list)
    for r in records:
        by[(r.platform, r.category, r.meta.get("source"))].append(r)
    out: list[Finding] = []

    def add(**kw):
        out.append(Finding(id=f"F-{len(out) + 1:03d}", **kw))

    off = by[("instagram", "account", "off_meta")]
    if off:
        add(layer=1, title=f"{len(off)} companies sent Meta data about you",
            detail="These businesses shared your website visits, app use or purchases with Meta.",
            priority="high", category="account", platforms=["instagram"],
            metric={"value": len(off), "unit": "companies"}, evidence=[r.id for r in off],
            action={"steps": ["Open Instagram > Settings > Accounts Center", "Your information and permissions",
                              "Your activity off Meta technologies", "Clear previous activity",
                              "Manage future activity > Disconnect future activity"], "link": IG_CENTER})

    adv = by[("instagram", "account", "advertiser")]
    if adv:
        uploaded = [r for r in adv if r.meta.get("uploaded_list")]
        add(layer=1, title=f"{len(adv)} advertisers target you with your own data",
            detail=f"{len(uploaded)} of them uploaded a customer list containing your contact details.",
            priority="high" if uploaded else "medium", category="account", platforms=["instagram"],
            metric={"value": len(adv), "unit": "advertisers"}, evidence=[r.id for r in adv],
            action={"steps": ["Open Instagram > Settings > Accounts Center", "Ad preferences",
                              "Manage info > Activity information from ad partners > turn off",
                              "Ad topics: review and hide topics"], "link": IG_CENTER})

    topics = by[("instagram", "interest", None)]
    if topics:
        add(layer=2, title=f"Instagram labelled you with {len(topics)} interests",
            detail="Instagram inferred these topics from your activity and uses them for ads and recommendations.",
            priority="medium", category="interest", platforms=["instagram"],
            metric={"value": len(topics), "unit": "topics"}, evidence=[r.id for r in topics],
            action={"steps": ["Open Instagram > Settings > Accounts Center > Ad preferences > Ad topics",
                              "Settings > Suggested content > Not interested / Reset suggested content"], "link": IG_CENTER})

    logins = by[("instagram", "location", None)]
    if logins:
        ips = Counter(r.meta["ip"] for r in logins)
        home_ip, home_n = ips.most_common(1)[0]
        add(layer=2, title=f"Logins from {len(ips)} different IP addresses",
            detail=f"Most logins ({home_n}) came from {home_ip}, likely your home network; IPs reveal your approximate city.",
            priority="medium", category="location", platforms=["instagram"],
            metric={"value": len(ips), "unit": "IP addresses"}, evidence=[r.id for r in logins],
            action={"steps": ["Open Instagram > Settings > Accounts Center > Password and security",
                              "Where you're logged in: log out unknown devices", "Turn on two-factor authentication"],
                    "link": IG_CENTER})

    sensitive = defaultdict(list)
    sens_platforms = defaultdict(set)
    for r in records:
        if r.category == "message":
            for label in scan_text(r.meta.get("text", "")):
                sensitive[label].append(r.id)
                sens_platforms[label].add(r.platform)
    for label, ids in sorted(sensitive.items(), key=lambda kv: -len(kv[1])):
        add(layer=3, title=f"Your {label.lower()} appears in {len(ids)} message{'s' if len(ids) != 1 else ''}",
            detail="Anyone with access to these chats, or the platform itself, can read it.",
            priority="high", category="message", platforms=sorted(sens_platforms[label]),
            metric={"value": len(ids), "unit": "messages"}, evidence=ids,
            action={"steps": ["Open each chat in the evidence list", "Long-press the message > Unsend / Delete for everyone",
                              "Turn on disappearing messages for chats where you share details"], "link": ""})

    mail = by[("gmail", "account", "email")]
    if mail:
        services = defaultdict(list)
        for r in mail:
            services[r.meta["domain"]].append(r.id)
        forgotten = [d for d, ids in services.items() if len(ids) == 1]
        add(layer=1, title=f"{len(services)} services have your email address",
            detail=f"Found from signup, password-reset, receipt and security emails. {len(forgotten)} appear only once - likely forgotten accounts.",
            priority="high", category="account", platforms=["gmail"],
            metric={"value": len(services), "unit": "services"}, evidence=[r.id for r in mail],
            action={"steps": ["Open the evidence list and pick accounts you no longer use",
                              "Log in to each service > Settings > Account > Delete account",
                              "No delete option: email the service's privacy contact asking for erasure under India's DPDP Act 2023",
                              "Change reused passwords on the services you keep"], "link": ""})

    segs = by[("spotify", "interest", None)]
    if segs:
        add(layer=2, title=f"Spotify sorted you into {len(segs)} ad segments",
            detail="Segments include: " + ", ".join(r.meta["topic"] for r in segs[:6]) + ". Some come from advertiser data, not your listening.",
            priority="medium", category="interest", platforms=["spotify"],
            metric={"value": len(segs), "unit": "segments"}, evidence=[r.id for r in segs],
            action={"steps": ["spotify.com > Account > Privacy settings", "Turn off 'Process my personal data for tailored ads'",
                              "Turn off 'Process my Facebook data'"], "link": "https://www.spotify.com/account/privacy/"})

    # L4 connection: same IP seen by more than one platform = shared home network
    ip_platforms = defaultdict(set); ip_ids = defaultdict(list)
    for r in records:
        if r.category == "location" and r.meta.get("ip"):
            ip_platforms[r.meta["ip"]].add(r.platform); ip_ids[r.meta["ip"]].append(r.id)
    shared = {ip: ps for ip, ps in ip_platforms.items() if len(ps) > 1}
    if shared:
        ip, ps = max(shared.items(), key=lambda kv: (len(kv[1]), len(ip_ids[kv[0]])))
        add(layer=4, title=f"{len(ps)} platforms know your home network",
            detail=f"IP {ip} appears in {', '.join(sorted(ps))} records. Matching IPs link your accounts to one household and city.",
            priority="high", category="location", platforms=sorted(ps),
            metric={"value": len(ps), "unit": "platforms"}, evidence=ip_ids[ip],
            action={"steps": ["Use a different network (mobile data) for accounts you want kept apart",
                              "Log out unknown sessions on every platform listed", "Consider a trusted VPN on shared Wi-Fi"], "link": ""})

    wa = [r for r in records if r.platform == "whatsapp"]
    groups = defaultdict(set)
    for r in wa:
        if r.meta.get("group"):
            groups[r.meta["chat"]].update(r.meta["senders"])
    if groups:
        everyone = set().union(*groups.values())
        add(layer=3, title=f"{len(everyone)} people can see your number in {len(groups)} WhatsApp group{'s' if len(groups) != 1 else ''}",
            detail="Every group member sees your phone number and profile photo, and can save or forward them.",
            priority="medium", category="contact", platforms=["whatsapp"],
            metric={"value": len(everyone), "unit": "people"}, evidence=[r.id for r in wa if r.meta.get("group")][:200],
            action={"steps": ["WhatsApp > Settings > Privacy > Groups > My contacts", "Privacy > Profile photo > My contacts",
                              "Exit groups you no longer use"], "link": ""})

    replay = by[("chrome", "account", "session_replay")]
    if replay:
        vendors = sorted({r.meta["vendor"] for r in replay})
        add(layer=1, title=f"{len(replay)} sites recorded your clicks and typing",
            detail=f"Session-replay tools ({', '.join(vendors)}) record mouse movement, scrolling and what you type, then replay it for the site owner.",
            priority="high", category="activity", platforms=["chrome"],
            metric={"value": len(replay), "unit": "sites"}, evidence=[r.id for r in replay],
            action={"steps": ["Install uBlock Origin and enable the 'EasyPrivacy' filter list",
                              "Chrome > Settings > Privacy and security > Third-party cookies > Block third-party cookies",
                              "Delete existing data: Settings > Privacy > Delete browsing data > Cookies"],
                    "link": "chrome://settings/privacy"})

    trackers = by[("chrome", "account", "tracker")]
    if trackers:
        add(layer=1, title=f"{len(trackers)} ad and analytics companies track you across sites",
            detail="Their cookies let them follow you from site to site and build an advertising profile.",
            priority="medium", category="activity", platforms=["chrome"],
            metric={"value": len(trackers), "unit": "trackers"}, evidence=[r.id for r in trackers],
            action={"steps": ["Chrome > Settings > Privacy and security > Third-party cookies > Block third-party cookies",
                              "Settings > Privacy > Ad privacy > turn off Ad topics, Site-suggested ads, Ad measurement"],
                    "link": "chrome://settings/adPrivacy"})

    perms = [r for r in records if r.category == "device" and r.meta.get("permission")]
    sensors = [r for r in perms if r.meta["permission"] in ("location", "camera", "microphone")]
    if sensors:
        kinds = Counter(r.meta["permission"] for r in sensors)
        sites = {r.meta["domain"] for r in sensors}
        add(layer=5, title=f"{len(sites)} sites can access your location, camera or microphone",
            detail=", ".join(f"{v} {k}" for k, v in kinds.items()) + " permissions are allowed in your browser.",
            priority="high" if kinds.get("location") else "medium", category="device", platforms=sorted({r.platform for r in sensors}),
            metric={"value": len(sites), "unit": "sites"}, evidence=[r.id for r in sensors],
            action={"steps": ["Chrome > Settings > Privacy and security > Site settings",
                              "Open Location, Camera and Microphone; remove every site you don't trust",
                              "Set the default to 'Don't allow sites to ...'"], "link": "chrome://settings/content"})

    people = closeness(records)
    if people:
        top = people[:5]
        add(layer=3, title=f"Your top {len(top)} people are visible from your activity alone",
            detail="Likes, comments and messages rank who you are closest to: " + ", ".join(p["name"] for p in top) + ".",
            priority="medium", category="contact",
            platforms=sorted({r.platform for r in records if r.meta.get("person")}),
            metric={"value": len(top), "unit": "people"}, evidence=[e for p in top for e in p["evidence"][:20]],
            action={"steps": ["Instagram > Settings > Activity in Friends tab: turn off",
                              "Settings > Story, live and location > Hide story from", "Review close friends list"],
                    "link": IG_CENTER})

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda f: (order[f.priority], -f.metric["value"]))
    summary = {
        "servicesFound": len({r.meta["domain"] for r in records if r.category == "account" and r.meta.get("domain")
                              and r.meta.get("source") not in ("tracker", "session_replay")}),
        "trackersFound": len(trackers),
        "sessionRecorders": len(replay),
        "topPeople": [{k: p[k] for k in ("name", "score", "signals")} for p in people[:10]],
        "sensitiveHits": sum(len(v) for v in sensitive.values()),
    }
    return out, summary


def build_graph(records, summary) -> dict:
    nodes = {"user": {"id": "user", "label": "You", "type": "user", "size": 40}}
    edges = []
    for r in records:
        if r.category == "account" and r.meta.get("domain"):
            nid = "svc:" + r.meta["domain"]
            src = r.meta.get("source")
            typ = "advertiser" if src == "advertiser" else "tracker" if src in ("tracker", "session_replay") else "service"
            nodes.setdefault(nid, {"id": nid, "label": r.meta["domain"], "type": typ, "size": 10})
            edges.append({"source": "user", "target": nid, "weight": 1, "label": r.meta.get("source", ""), "evidence": [r.id]})
    for p in summary["topPeople"]:
        nid = "person:" + p["name"]
        nodes[nid] = {"id": nid, "label": p["name"], "type": "person", "size": 10 + min(p["score"], 30)}
        edges.append({"source": "user", "target": nid, "weight": p["score"], "label": "closeness", "evidence": []})
    return {"nodes": list(nodes.values()), "edges": edges}
