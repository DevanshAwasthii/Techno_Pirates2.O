"""Gmail .mbox (Google Takeout > Mail) service discovery.

Reads headers only (From, Subject, Date) to find every service that has the user's email:
signup, verification, password reset, receipts, security alerts. Streams message by message.
"""
from __future__ import annotations

import mailbox
import re
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from app.engine.records import Record, ParseError

PLATFORM = "gmail"
KINDS = {
    "signup": r"welcome|verify your( \w+)? (email|account)|confirm your( \w+)? (email|account|registration)|thanks for (signing|joining|registering)|activate your account|account (created|registration)",
    "password_reset": r"reset your password|password reset|forgot (your )?password",
    "security": r"new (sign-?in|login)|security alert|unusual (sign-?in|activity)|login attempt",
    "receipt": r"order (has been )?(confirmed|confirmation|placed|#)|your receipt|invoice|payment (received|successful)|booking (confirmed|confirmation)",
    "data_notice": r"privacy policy|data (breach|incident)|terms of service|we've updated our terms",
}
PERSONAL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "icloud.com", "rediffmail.com"}
SECOND_LEVEL = {"co", "com", "net", "org", "ac", "gov", "edu"}


def base_domain(addr: str) -> str:
    host = addr.rsplit("@", 1)[-1].lower().strip(">")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _h(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def classify(subject: str) -> str | None:
    s = subject.lower()
    for kind, rx in KINDS.items():
        if re.search(rx, s):
            return kind
    return None


def parse(path: str, src: str = "mail.mbox"):
    try:
        box = mailbox.mbox(path, create=False)
    except Exception as e:
        raise ParseError("wrong_format", f"Cannot open mailbox: {e}", src)
    recs, n = [], 0
    for i, msg in enumerate(box):
        subject = _h(msg.get("Subject"))
        kind = classify(subject)
        if not kind:
            continue  # newsletters and personal mail are not proof of an account
        name, addr = parseaddr(_h(msg.get("From")))
        if "@" not in addr:
            continue
        dom = base_domain(addr)
        if dom in PERSONAL:
            continue
        try:
            ts = parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            ts = None
        n += 1
        recs.append(Record(f"gm-acco-{n:05d}", PLATFORM, "account", f"{dom}: {subject[:90]}", ts,
                           sourceFile=src, recordRef=f"message {i + 1}",
                           meta={"domain": dom, "source": "email", "email_kind": kind, "sender": name or addr}))
    box.close()
    if not recs:
        raise ParseError("wrong_format", "No account emails found in this mailbox", src)
    cov = {"location": "not_assessed", "interest": "not_assessed", "contact": "not_assessed", "activity": "found"}
    return recs, cov
