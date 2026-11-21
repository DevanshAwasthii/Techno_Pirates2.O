"""Turn records into prioritised findings, each with evidence and exact steps.

Steps reflect app menus as of Nov 2026; the presenter verifies them on real apps.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.engine.records import Finding
from app.engine.services import canonical_service_key, first_party_tracker_ids, service_category
from app.engine.messages import scan_text, closeness
from app.parsers.chrome import TRACKERS

IG_CENTER = "https://accountscenter.instagram.com/"


def build_findings(records, now=None) -> tuple[list[Finding], dict]:
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
            services[canonical_service_key(r.meta["domain"])].append(r.id)
        forgotten = [d for d, ids in services.items() if len(ids) == 1]
        add(layer=1, title=f"{len(services)} services have your email address",
            detail=f"Found from signup, password-reset, receipt and security emails. {len(forgotten)} appear only once - likely forgotten accounts.",
            priority="high", category="account", platforms=["gmail"],
            metric={"value": len(services), "unit": "services"}, evidence=[r.id for r in mail],
            action={"steps": ["Open the evidence list and pick accounts you no longer use",
                              "Log in to each service > Settings > Account > Delete account",
                              "No delete option: email the service's privacy contact asking for erasure under India's DPDP Act 2023",
                              "Change reused passwords on the services you keep"], "link": ""})

    lists = by[("gmail", "account", "newsletter")]
    if lists:
        senders = {r.meta["domain"] for r in lists}
        add(layer=1, title=f"{len(senders)} mailing lists hold your email address",
            detail="Each list sender stores your address and often shares it with marketing partners.",
            priority="low", category="account", platforms=["gmail"],
            metric={"value": len(senders), "unit": "senders"}, evidence=[r.id for r in lists],
            action={"steps": ["Open one email from each sender in the evidence list", "Click 'Unsubscribe' at the bottom",
                              "Gmail: open the email > three-dot menu > Unsubscribe"], "link": ""})

    if by[("gmail", "account", "email")] or lists or any(r.platform == "google" for r in records):
        grants = by[("gmail", "account", "google_signin")]
        apps = sorted({r.meta["domain"] for r in grants})
        evidence = [r.id for r in grants] or [r.id for r in by[("gmail", "account", "email")][:5]]
        add(layer=1,
            title=f"{len(apps)} apps are connected to your Google account" if apps
            else "Check which apps use Sign in with Google",
            detail=("Google security emails show these apps got access: " + ", ".join(apps) + ". " if apps else
                    "Google exports do not list apps you signed into with Google, so check them directly. ")
                   + "Connected apps can keep reading your profile, email or contacts until removed.",
            priority="high" if apps else "low", category="account", platforms=["gmail"],
            metric={"value": len(apps), "unit": "apps"}, evidence=evidence,
            action={"steps": ["Open myaccount.google.com/connections", "Review 'Third-party apps and services'",
                              "Click each app you don't use > Delete all connections"],
                    "link": "https://myaccount.google.com/connections"})

    g_ips = [r for r in records if r.platform == "google" and r.category == "location" and r.meta.get("ip")]
    if g_ips:
        places = {r.meta["place"] for r in g_ips if r.meta.get("place")}
        total = sum(r.meta.get("count", 1) for r in g_ips)
        top = max(g_ips, key=lambda r: r.meta.get("count", 0))
        where = f" in {len(places)} place{'s' if len(places) != 1 else ''}" if places else ""
        add(layer=2, title=f"Google logged your account activity from {len(g_ips)} IP addresses{where}",
            detail=f"{total:,} logged activities. Most from {top.meta['ip']}"
                   + (f" ({top.meta['place']})" if top.meta.get("place") else "") + ". "
                   + ("" if places else "Google's export left the city columns blank, but each IP still maps to an approximate city. ")
                   + "IP addresses reveal where you are and which networks you use.",
            priority="high", category="location", platforms=["google"],
            metric={"value": len(g_ips), "unit": "IP addresses"}, evidence=[r.id for r in g_ips][:500],
            action={"steps": ["Open myaccount.google.com/device-activity and sign out devices you don't recognise",
                              "Turn on 2-Step Verification: myaccount.google.com/signinoptions/two-step-verification",
                              "Use mobile data or a trusted VPN on public Wi-Fi"],
                    "link": "https://myaccount.google.com/device-activity"})
    g_dev = [r for r in records if r.platform == "google" and r.category == "device"]
    if g_dev:
        located = [r for r in records if r.platform == "google" and r.category == "location" and r.meta.get("place") and not r.meta.get("ip")]
        add(layer=5, title=f"{len(g_dev)} device{'s have' if len(g_dev) != 1 else ' has'} accessed your Google account",
            detail=(f"Google keeps a last known location for {len(located)} of them. " if located else "")
                   + "Old phones and shared computers keep access until you remove them.",
            priority="medium", category="device", platforms=["google"],
            metric={"value": len(g_dev), "unit": "devices"}, evidence=[r.id for r in g_dev + located],
            action={"steps": ["Open myaccount.google.com/device-activity", "Select each old or unknown device > Sign out",
                              "Change your password if any device is unfamiliar"],
                    "link": "https://myaccount.google.com/device-activity"})

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
    replay_count = len({r.meta["domain"] for r in replay})
    if replay:
        vendors = sorted({r.meta["vendor"] for r in replay})
        live = any(r.meta.get("live_profile") for r in replay)
        add(layer=1, title=f"{replay_count} sites have session-replay cookie indicators" if live else f"{len(replay)} sites recorded your clicks and typing",
            detail=(f"Cookie names associated with {', '.join(vendors)} were found locally. This indicates a tool may be present; it does not prove your clicks, typing or screen contents were recorded."
                    if live else f"Session-replay tools ({', '.join(vendors)}) record mouse movement, scrolling and what you type, then replay it for the site owner."),
            priority="high", category="activity", platforms=["chrome"],
            metric={"value": replay_count, "unit": "sites"}, evidence=[r.id for r in replay],
            action={"steps": ["Install uBlock Origin and enable the 'EasyPrivacy' filter list",
                              "Chrome > Settings > Privacy and security > Third-party cookies > Block third-party cookies",
                              "Delete existing data: Settings > Privacy > Delete browsing data > Cookies"],
                    "link": "chrome://settings/privacy"})

    first_party = first_party_tracker_ids(records)
    trackers = [r for r in by[("chrome", "account", "tracker")] if r.id not in first_party]
    tracker_count = len({r.meta["domain"] for r in trackers})
    if trackers:
        live = any(r.meta.get("live_profile") for r in trackers)
        add(layer=1, title=f"{tracker_count} known tracker domains appear in browser cookies" if live else f"{len(trackers)} ad and analytics companies track you across sites",
            detail=("Cookie names and domains were observed locally. Their presence alone does not establish what data was sent or whether cross-site tracking occurred."
                    if live else "Their cookies let them follow you from site to site and build an advertising profile."),
            priority="medium", category="activity", platforms=["chrome"],
            metric={"value": tracker_count, "unit": "trackers"}, evidence=[r.id for r in trackers],
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

    feed = [r for r in records if r.meta.get("capture") == "ocr" and r.meta.get("action") == "friend_like"]
    if feed:
        friends = {r.meta["person"] for r in feed}
        add(layer=3, title=f"Instagram showed you what {len(friends)} friends liked",
            detail="Your feed exposes friends' likes to you - and yours to them. Every like is visible to your followers.",
            priority="medium", category="activity", platforms=["instagram"],
            metric={"value": len(friends), "unit": "friends"}, evidence=[r.id for r in feed],
            action={"steps": ["Instagram > Settings > Activity in Friends tab > turn off",
                              "Settings > Likes and shares > Hide like counts"], "link": IG_CENTER})

    viewers = [r for r in records if r.meta.get("action") == "status_view"]
    if viewers:
        who = {r.meta["person"] for r in viewers}
        add(layer=3, title=f"{len(who)} people watch your WhatsApp status",
            detail="Status viewers form your inner circle; each one sees where you are and what you do.",
            priority="medium", category="contact", platforms=["whatsapp"],
            metric={"value": len(who), "unit": "people"}, evidence=[r.id for r in viewers],
            action={"steps": ["WhatsApp > Settings > Privacy > Status", "Choose 'My contacts except...' or 'Only share with...'",
                              "Never post live location or travel plans in status"], "link": ""})

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

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    recent_location = []
    for r in records:
        if r.platform not in {"ios", "android"} or r.meta.get("source") != "sensor_access" or r.meta.get("sensor") != "location":
            continue
        try:
            stamp = datetime.fromisoformat((r.timestamp or "").replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                continue
            if now - timedelta(days=7) <= stamp <= now:
                recent_location.append(r)
        except (ValueError, TypeError, OverflowError):
            continue
    location_apps = {(r.platform, r.meta["app"]) for r in recent_location}
    if location_apps:
        add(layer=5, title=f"{len(location_apps)} apps accessed your location in the last 7 days",
            detail="Observed access events across iOS and Android. The same app on two platforms counts as two app installations; permission alone does not prove use.",
            priority="high", category="location", platforms=sorted({r.platform for r in recent_location}),
            metric={"value": len(location_apps), "unit": "apps"}, evidence=[r.id for r in recent_location],
            action={"steps": ["iPhone: Settings > Privacy & Security > Location Services > select the app",
                              "Choose Never or While Using the App; turn off Precise Location where unnecessary",
                              "Android: Settings > Privacy > Permission manager > Location > select the app",
                              "Choose Don't allow or Allow only while using the app; turn off precise location"], "link": ""})

    tracking_domains = set(TRACKERS) | {"uxcam.com", "smartlook.com", "clarity.ms", "appsflyer.com", "branch.io", "adjust.com"}
    mobile_tracking = [r for r in records if r.platform == "ios" and r.meta.get("source") == "ios_network"
                       and any(r.meta["domain"] == domain or r.meta["domain"].endswith("." + domain) for domain in tracking_domains)]
    tracking_apps = {(r.platform, r.meta["app"]) for r in mobile_tracking}
    if tracking_apps:
        add(layer=5, title=f"{len(tracking_apps)} apps send data to session-recording or tracking services",
            detail="App Privacy Report shows connections to known tracking or session-recording domains. A connection alone does not prove that screen contents were recorded.",
            priority="high", category="device", platforms=["ios"],
            metric={"value": len(tracking_apps), "unit": "apps"}, evidence=[r.id for r in mobile_tracking],
            action={"steps": ["iPhone: Settings > Privacy & Security > App Privacy Report",
                              "Open App Network Activity > select an app > review the listed domains",
                              "Settings > Privacy & Security > Tracking > turn off Allow Apps to Request to Track",
                              "Review the app's privacy settings; uninstall apps whose data sharing you do not accept"], "link": ""})

    stores = [r for r in records if r.platform == "device" and r.meta.get("source") == "laptop_store"]
    data_bytes = sum(r.meta["bytes"] for r in stores)
    if stores:
        partial = any(r.meta.get("partial") for r in stores)
        add(layer=5, title=f"{len(stores)} apps hold {data_bytes / 1_000_000_000:.2f} GB of your data on this laptop",
            detail="Measured data in the largest app folders under AppData. File contents were not collected." +
                   (" The scan was incomplete; sizes are lower bounds." if partial else ""),
            priority="medium", category="device", platforms=["device"],
            metric={"value": len(stores), "unit": "apps"}, evidence=[r.id for r in stores],
            action={"steps": ["Windows: Settings > System > Storage > Cleanup recommendations",
                              "Review Temporary files before selecting Remove files",
                              "Open each listed app > Settings > Storage or Cache > clear data you no longer need",
                              "Settings > Apps > Installed apps > uninstall unused apps; back up needed data first"], "link": ""})

    identifying_logs = [r for r in records if r.platform == "device" and r.meta.get("source") == "device_log"
                        and (r.meta.get("emails", 0) or r.meta.get("ips", 0))]
    log_paths = {r.meta["path"] for r in identifying_logs}
    if log_paths:
        add(layer=5, title=f"{len(log_paths)} log files contain your email or IP address",
            detail="Only email, IPv4 and Indian-phone pattern counts were retained. These are pattern matches, not verified identities; no matched values were saved.",
            priority="high", category="device", platforms=["device"],
            metric={"value": len(log_paths), "unit": "log files"}, evidence=[r.id for r in identifying_logs],
            action={"steps": ["Open each app listed in the evidence > Settings > Privacy or Diagnostics",
                              "Turn off optional diagnostic logging and sharing where available",
                              "Close the app; use its Clear logs or Clear diagnostics option if offered",
                              "Review the listed log paths before sharing support bundles"], "link": ""})

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda f: (order[f.priority], -f.metric["value"]))
    summary = {
        "servicesFound": len({canonical_service_key(r.meta["domain"]) for r in records if r.category == "account" and r.meta.get("domain")
                              and r.meta.get("source") not in ("tracker", "session_replay")}),
        "trackersFound": tracker_count,
        "sessionRecorders": replay_count,
        "topPeople": [{k: p[k] for k in ("name", "score", "signals")} for p in people[:10]],
        "sensitiveHits": sum(len(v) for v in sensitive.values()),
        "recentLocationApps": len(location_apps),
        "mobileTrackingApps": len(tracking_apps),
        "laptopDataApps": len(stores),
        "laptopDataBytes": data_bytes,
        "logsWithIdentifiers": len(log_paths),
    }
    return out, summary


def build_graph(records, summary) -> dict:
    """Bound the overview to eight groups; retain all service records for drill-down."""
    first_party = first_party_tracker_ids(records)
    services = {}
    rank = {"tracker": 0, "advertiser": 1, "service": 2}
    for r in records:
        if r.category != "account" or not r.meta.get("domain"):
            continue
        key = canonical_service_key(r.meta["domain"])
        src = "first_party_cookie" if r.id in first_party else r.meta.get("source")
        kind = "advertiser" if src == "advertiser" else "tracker" if src in ("tracker", "session_replay") else "service"
        service = services.setdefault(key, {"id": "svc:" + key, "label": key, "type": kind, "evidence": []})
        if rank[kind] > rank[service["type"]]:
            service["type"] = kind
        service["evidence"].append(r.id)
    groups = defaultdict(list)
    for key, service in sorted(services.items()):
        groups[service_category(key, service["type"])].append(service)
    nodes = [{"id": "user", "label": "You", "type": "user", "size": 1}]
    edges = []
    for category, members in groups.items():
        nid = "cluster:" + category
        evidence = [rid for member in members for rid in member["evidence"]]
        nodes.append({"id": nid, "label": category, "type": "cluster", "size": len(members), "services": members})
        edges.append({"source": "user", "target": nid, "weight": len(members), "label": category, "evidence": evidence})
    return {"nodes": nodes, "edges": edges}
