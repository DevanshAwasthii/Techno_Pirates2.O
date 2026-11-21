"""Build the synthetic demo persona 'Riya Sen' as an Instagram JSON export zip.

    python -m samples.make_persona   ->  samples/persona_instagram.zip

Deterministic (fixed seed). Text is mojibake-encoded like real Meta exports.
"""
import json
import random
import zipfile
from pathlib import Path

random.seed(7)
OUT = Path(__file__).parent / "persona_instagram.zip"
OWNER = "Riya Sen"
FRIENDS = ["arjun.das", "meera_k", "rahul.k", "sneha.b", "kabir.roy", "tanvi.m", "ishaan_g", "pooja.s"]
BASE = 1_760_000_000  # Oct 2025


def moj(s):  # mimic Meta's latin-1-escaped UTF-8
    return s.encode("utf-8").decode("latin-1")


def ts(days_back, hour):
    return BASE + 86400 * 365 - days_back * 86400 + hour * 3600 + random.randint(0, 3599)


def night_hour():
    return random.choice([22, 23, 23, 0, 1, 9, 13, 18, 21, 23])


files = {
    "personal_information/personal_information/personal_information.json": {
        "profile_user": [{"string_map_data": {"Name": {"value": moj(OWNER)}, "Username": {"value": "riya.sen"}}}]},
    "connections/followers_and_following/followers_1.json": [
        {"string_list_data": [{"href": f"https://www.instagram.com/{f}", "value": f, "timestamp": ts(400 - i * 20, 12)}]}
        for i, f in enumerate(FRIENDS + [f"user{n}" for n in range(30)])],
    "connections/followers_and_following/following.json": {"relationships_following": [
        {"title": f, "string_list_data": [{"href": f"https://www.instagram.com/{f}", "timestamp": ts(390 - i * 15, 14)}]}
        for i, f in enumerate(FRIENDS + ["zomato", "nykaa", "kolkata.foodies", "bollywoodbubble"])]},
    "your_instagram_activity/likes/liked_posts.json": {"likes_media_likes": [
        {"title": random.choices(FRIENDS + ["zomato", "kolkata.foodies"], weights=[9, 8, 6, 5, 3, 3, 2, 2, 4, 4])[0],
         "string_list_data": [{"href": "https://www.instagram.com/p/x", "value": "\U0001F44D", "timestamp": ts(random.randint(0, 300), night_hour())}]}
        for _ in range(240)]},
    "preferences/your_topics/your_topics.json": {"topics_your_topics": [
        {"string_map_data": {"Name": {"value": t}}} for t in
        ["Bengali cuisine", "Budget travel", "Skincare", "Bollywood", "Cricket", "Exam preparation", "Street food", "Indie music"]]},
    "ads_information/instagram_ads_and_businesses/advertisers_using_your_activity_or_information.json": {
        "ig_custom_audiences_all_types": [
            {"advertiser_name": a, "has_data_file_custom_audience": i % 3 == 0, "has_remarketing_custom_audience": True}
            for i, a in enumerate(["Myntra", "Swiggy", "Nykaa", "Byju's", "MakeMyTrip", "Meesho", "Unacademy", "Ajio",
                                   "Zomato", "Flipkart", "Tata CLiQ", "Lenskart", "boAt", "Mamaearth", "PhysicsWallah"])]},
    "apps_and_websites_off_of_instagram/apps_and_websites/your_activity_off_meta_technologies.json": {
        "apps_and_websites_off_meta_activity": [
            {"name": n, "events": [{"id": k, "type": random.choice(["PAGE_VIEW", "PURCHASE", "SEARCH", "ADD_TO_CART"]),
                                     "timestamp": ts(random.randint(0, 200), 20)} for k in range(random.randint(3, 40))]}
            for n in ["amazon.in", "flipkart.com", "zomato.com", "swiggy.com", "myntra.com", "makemytrip.com", "bookmyshow.com",
                      "nykaa.com", "practo.com", "olx.in", "naukri.com", "paytm.com", "hdfcbank.com", "irctc.co.in",
                      "lenskart.com", "ajio.com", "meesho.com", "unacademy.com", "cred.club", "dream11.com", "rapido.bike",
                      "uber.com", "spotify.com"]]},
    "security_and_login_information/login_and_profile_creation/login_activity.json": {
        "account_history_login_history": [
            {"title": "login", "string_map_data": {
                "IP Address": {"value": ip}, "Time": {"timestamp": ts(random.randint(0, 300), 9)},
                "User Agent": {"value": ua}}}
            for ip, ua in [("49.37.12.88", "Instagram Android")] * 14 + [("103.21.58.4", "Chrome Windows")] * 4
            + [("157.45.200.17", "Instagram Android")] * 3 + [("27.60.11.90", "Safari iPhone")]]},
}

threads = {
    "arjunda_1": ("arjun.das", ["hey are you coming tonight?", "send me your number again", "ok it's 9876543210 right?",
                                "yes save it", "my aadhaar for the form: 4521 8890 1234", "thanks!"]),
    "meerak_2": ("meera_k", ["did you see the post", "otp is 482913 don't share lol", "haha ok", "mail me at riya.sen@gmail.com"]),
    "rahulk_3": ("rahul.k", ["notes for exam?", "PAN for internship form ABCDE1234F", "sent"]),
    "snehab_4": ("sneha.b", ["আজকে কোথায়?", "college canteen", "coming"]),
}
for folder, (friend, lines) in threads.items():
    msgs = []
    for k, text in enumerate(lines):
        sender = OWNER if k % 2 else friend
        msgs.append({"sender_name": moj(sender), "timestamp_ms": ts(random.randint(0, 60), night_hour()) * 1000, "content": moj(text)})
    files[f"your_instagram_activity/messages/inbox/{folder}/message_1.json"] = {
        "participants": [{"name": moj(friend)}, {"name": moj(OWNER)}], "messages": msgs}

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for name, data in files.items():
        z.writestr(name, json.dumps(data, ensure_ascii=False))
print("wrote", OUT)

# ---- WhatsApp: Android format chats (12h clock with narrow no-break space, like real exports) ----
from datetime import datetime, timedelta  # noqa: E402

DIR = Path(__file__).parent


def wa_line(dt, who, text):
    h = dt.strftime("%I").lstrip("0")
    return f"{dt.day:02d}/{dt.month:02d}/{dt.strftime('%y')}, {h}:{dt.strftime('%M')} {dt.strftime('%p').lower()} - {who}: {text}"


def wa_chat(fname, lines):
    start = datetime(2026, 10, 1, 21, 0)
    out = ["01/10/26, 9:00 pm - Messages and calls are end-to-end encrypted. Only people in this chat can read them."]
    for k, (who, text) in enumerate(lines):
        out.append(wa_line(start + timedelta(days=k // 3, minutes=37 * k, hours=random.choice([0, 1, 2, 3])), who, text))
    (DIR / fname).write_text("\n".join(out), encoding="utf-8")


wa_chat("persona_whatsapp_Arjun.txt", [
    ("Arjun Das", "bro what's your bank ifsc"), ("Riya Sen", "HDFC0001234"), ("Arjun Das", "and account?"),
    ("Riya Sen", "card is 4111 1111 1111 1111 just for the booking"), ("Arjun Das", "ok done"),
    ("Riya Sen", "my number changed: +91 9123456780"), ("Arjun Das", "saved"), ("Riya Sen", "see you at college"),
    ("Arjun Das", "\U0001F44D")])
wa_chat("persona_whatsapp_Meera.txt", [
    ("Meera K", "send aadhaar pic for hostel form"), ("Riya Sen", "4521 8890 1234 is the number"),
    ("Meera K", "ok and PAN?"), ("Riya Sen", "ABCDE1234F"), ("Meera K", "thanks"),
    ("Riya Sen", "password for wifi is riya@2026"), ("Meera K", "lol ok")])
wa_chat("persona_whatsapp_College Gang.txt", [
    (random.choice(["Riya Sen", "Arjun Das", "Meera K", "Kabir Roy", "Tanvi M", "Ishaan G", "Pooja S", "Rahul K"]), t)
    for t in ["party sat?", "yes", "where", "park street", "who's coming", "me", "me too", "send location",
              "live location shared", "ok", "reach by 8", "late by 10", "lol", "bring speaker", "done"] * 2])

# ---- Spotify: account data + extended history in one zip ----
sp = {
    "MyData/Inferences.json": {"inferences": [
        "1P_Custom_Spotify_Commuters", "1P_Custom_Spotify_Students", "3P_Budget Conscious Shoppers", "3P_Bollywood Fans",
        "3P_Online Food Delivery Users", "1P_Custom_Late_Night_Listeners", "3P_Kolkata Residents", "3P_Exam Prep Interest"]},
    "MyData/StreamingHistory_music_0.json": [
        {"endTime": (datetime(2026, 9, 1) + timedelta(hours=7 * k)).strftime("%Y-%m-%d %H:%M"),
         "artistName": random.choice(["Arijit Singh", "Anupam Roy", "Prateek Kuhad", "Shreya Ghoshal", "Taylor Swift"]),
         "trackName": f"Track {k}", "msPlayed": random.randint(30000, 240000)} for k in range(150)],
    "Spotify Extended Streaming History/Streaming_History_Audio_2025-2026.json": [
        {"ts": (datetime(2026, 8, 1) + timedelta(hours=9 * k)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "platform": random.choice(["android", "windows"]), "ms_played": 180000, "conn_country": "IN",
         "ip_addr": random.choice(["49.37.12.88"] * 6 + ["157.45.200.17", "106.51.77.2"]),
         "master_metadata_track_name": f"Track {k}", "master_metadata_album_artist_name": "Arijit Singh"} for k in range(80)],
}
with zipfile.ZipFile(DIR / "persona_spotify.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for name, data in sp.items():
        z.writestr(name, json.dumps(data))

# ---- Gmail mbox: account emails plus newsletters/personal mail that must NOT count ----
services = [
    ("Swiggy", "noreply@swiggy.in", "Welcome to Swiggy!"), ("Zomato", "hello@zomato.com", "Your order #4411 confirmed"),
    ("Myntra", "updates@myntra.com", "Verify your email"), ("IRCTC", "ticketadmin@irctc.co.in", "Booking confirmed PNR 4521"),
    ("Paytm", "no-reply@paytm.com", "Payment successful"), ("Naukri", "info@naukri.com", "Thanks for registering with Naukri"),
    ("Practo", "care@practo.com", "Confirm your account"), ("OLX", "noreply@olx.in", "Reset your password"),
    ("Dream11", "support@dream11.com", "Welcome to Dream11"), ("Canva", "start@canva.com", "Welcome to Canva"),
    ("Duolingo", "hello@duolingo.com", "Verify your email"), ("Coursera", "no-reply@coursera.org", "Welcome to Coursera"),
    ("Unacademy", "hello@unacademy.com", "Activate your account"), ("Lenskart", "orders@lenskart.com", "Order confirmation"),
    ("BookMyShow", "tickets@bookmyshow.com", "Booking confirmation"), ("Uber", "noreply@uber.com", "Your receipt from Uber"),
    ("Rapido", "no-reply@rapido.bike", "Invoice for your ride"), ("CRED", "hello@cred.club", "New sign-in to your account"),
    ("Instagram", "security@mail.instagram.com", "New login to Instagram"), ("Spotify", "no-reply@spotify.com", "Reset your password"),
    ("Discord", "noreply@discord.com", "Verify your email address"), ("Pinterest", "pinbot@pinterest.com", "Welcome to Pinterest"),
    ("Shein", "noreply@shein.com", "Thanks for signing up"), ("Truecaller", "noreply@truecaller.com", "Account created"),
    ("Byju's", "care@byjus.com", "Welcome to BYJU'S"), ("Meesho", "noreply@meesho.com", "Order placed"),
    ("HDFC Bank", "alerts@hdfcbank.net", "Security alert: new login"), ("Amazon", "auto-confirm@amazon.in", "Your order has been placed"),
    ("Flipkart", "no-reply@flipkart.com", "Order confirmed"), ("MakeMyTrip", "noreply@makemytrip.com", "Booking confirmed"),
    ("Netflix", "info@account.netflix.com", "Welcome to Netflix"), ("LinkedIn", "security-noreply@linkedin.com", "Unusual sign-in activity"),
    ("Reddit", "noreply@reddit.com", "Verify your Reddit email"), ("Quora", "noreply@quora.com", "Confirm your email"),
    ("Zepto", "noreply@zeptonow.com", "Welcome to Zepto"), ("Ola", "noreply@olacabs.com", "Your receipt"),
    ("Hotstar", "noreply@hotstar.com", "Welcome to JioHotstar"), ("Udemy", "no-reply@udemy.com", "Welcome to Udemy"),
    ("Grammarly", "hello@grammarly.com", "Verify your email"), ("PhonePe", "noreply@phonepe.com", "Payment received"),
    ("Old forum", "admin@desiforum.co.in", "Activate your account"),
]
noise = [("Arjun Das", "arjun.das@gmail.com", "notes for tomorrow"), ("Medium Daily", "noreply@medium.com", "Top stories for you"),
         ("Swiggy", "promo@swiggy.in", "50% off tonight only!")]
extra = [  # (name, addr, subject, body, list_unsubscribe)
    ("Zepto Cafe", "hello@zeptocafe.in", "Hi Riya", "Please verify your email address to start ordering.", False),
    ("Google", "no-reply@accounts.google.com", "Truecaller was granted access to your Google Account", "", False),
    ("Google", "no-reply@accounts.google.com", "Canva was granted access to your Google Account", "", False),
    ("Google", "no-reply@accounts.google.com", "QuizMaster Pro was granted access to your Google Account", "", False),
    ("The Hindu", "newsletters@thehindu.co.in", "Morning digest", "Today's headlines", True),
    ("Product Hunt", "hello@producthunt.com", "Top products today", "This week's launches", True),
]
mb = []
for k, (name, addr, subj) in enumerate(services + noise):
    d = datetime(2021, 1, 1) + timedelta(days=37 * k)
    unsub = f"List-Unsubscribe: <mailto:unsub@{addr.split('@')[1]}>\n" if addr.startswith(("noreply@medium", "promo@")) else ""
    mb.append(f"From {addr} {d.strftime('%a %b %d %H:%M:%S %Y')}\nFrom: {name} <{addr}>\nTo: riya.sen@gmail.com\n"
              f"Subject: {subj}\nDate: {d.strftime('%a, %d %b %Y %H:%M:%S +0530')}\n{unsub}\nHello Riya,\n\n")
for k, (name, addr, subj, body, unsub) in enumerate(extra):
    d = datetime(2025, 3, 1) + timedelta(days=11 * k)
    hdr = f"List-Unsubscribe: <mailto:unsub@{addr.split('@')[1]}>\n" if unsub else ""
    mb.append(f"From {addr} {d.strftime('%a %b %d %H:%M:%S %Y')}\nFrom: {name} <{addr}>\nTo: riya.sen@gmail.com\n"
              f"Subject: {subj}\nDate: {d.strftime('%a, %d %b %Y %H:%M:%S +0530')}\n{hdr}\n{body}\n\n")
(DIR / "persona_gmail.mbox").write_text("".join(mb), encoding="utf-8")

# ---- Chrome profile (zipped Default folder): History, Network/Cookies, Login Data, Preferences ----
import sqlite3  # noqa: E402
import tempfile  # noqa: E402


def webkit(dt):
    return int((dt - datetime(1601, 1, 1)).total_seconds() * 1_000_000)


with tempfile.TemporaryDirectory(dir=DIR) as d:
    prof = Path(d) / "Default"; (prof / "Network").mkdir(parents=True)
    con = sqlite3.connect(prof / "History")
    con.execute("CREATE TABLE urls(url TEXT, title TEXT, visit_count INT, last_visit_time INT)")
    con.execute("CREATE TABLE downloads(target_path TEXT, tab_url TEXT, start_time INT)")
    sites = ["youtube.com", "instagram.com", "web.whatsapp.com", "amazon.in", "flipkart.com", "zomato.com", "chatgpt.com",
             "geeksforgeeks.org", "github.com", "cricbuzz.com", "myntra.com", "practo.com", "irctc.co.in", "naukri.com"]
    for k, s in enumerate(sites):
        con.execute("INSERT INTO urls VALUES(?,?,?,?)", (f"https://www.{s}/", s, 400 // (k + 1) + 3, webkit(datetime(2026, 11, 1 + k % 20, 22))))
    con.execute("INSERT INTO downloads VALUES(?,?,?)", (r"C:\Users\Riya\Downloads\aadhaar_card.pdf", "https://uidai.gov.in/", webkit(datetime(2026, 6, 3))))
    con.execute("INSERT INTO downloads VALUES(?,?,?)", (r"C:\Users\Riya\Downloads\resume_riya.pdf", "https://docs.google.com/", webkit(datetime(2026, 9, 9))))
    con.commit(); con.close()
    con = sqlite3.connect(prof / "Network" / "Cookies")
    con.execute("CREATE TABLE cookies(host_key TEXT, name TEXT, encrypted_value BLOB)")
    cookie_rows = [(".doubleclick.net", "IDE"), (".google-analytics.com", "_ga"), (".facebook.com", "fr"), (".criteo.com", "uid"),
                   (".taboola.com", "t_gid"), (".scorecardresearch.com", "UID"), (".adnxs.com", "uuid2"), (".amazon-adsystem.com", "ad-id"),
                   (".pubmatic.com", "KTPCACOOKIE"), (".clarity.ms", "MUID"), (".linkedin.com", "bcookie"), (".tiktok.com", "ttwid")]
    replay_sites = [("www.myntra.com", "_hjSessionUser_1"), ("www.zomato.com", "_clck"), ("www.practo.com", "_hjSession_2"),
                    ("www.naukri.com", "_clsk"), ("www.flipkart.com", "_lr_hb"), ("shop.lenskart.com", "fs_uid")]
    for h, nme in cookie_rows + replay_sites:
        con.execute("INSERT INTO cookies VALUES(?,?,?)", (h, nme, b"\x00encrypted"))
    con.commit(); con.close()
    con = sqlite3.connect(prof / "Login Data")
    con.execute("CREATE TABLE logins(origin_url TEXT, username_value TEXT, password_value BLOB)")
    for s in ["https://accounts.zomato.com/", "https://www.irctc.co.in/", "https://www.instagram.com/", "https://www.naukri.com/",
              "https://forum.oldgamesite.net/", "https://www.coursera.org/"]:
        con.execute("INSERT INTO logins VALUES(?,?,?)", (s, "riya.sen", b"\x00encrypted"))
    con.commit(); con.close()
    prefs = {"profile": {"content_settings": {"exceptions": {
        "geolocation": {"https://www.zomato.com:443,*": {"setting": 1}, "https://www.swiggy.com:443,*": {"setting": 1},
                        "https://maps.google.com:443,*": {"setting": 1}, "https://randomquiz.io:443,*": {"setting": 1}},
        "media_stream_camera": {"https://meet.google.com:443,*": {"setting": 1}, "https://omegle-clone.xyz:443,*": {"setting": 1}},
        "media_stream_mic": {"https://meet.google.com:443,*": {"setting": 1}},
        "notifications": {"https://cricbuzz.com:443,*": {"setting": 1}}}}}}
    (prof / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")
    with zipfile.ZipFile(DIR / "persona_chrome.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in prof.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(Path(d)).as_posix())
print("wrote chrome persona")
print("wrote whatsapp, spotify, gmail persona files")
