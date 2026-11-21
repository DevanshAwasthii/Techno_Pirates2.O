"""Gmail .mbox (Google Takeout > Mail) service discovery.

Reads headers only (From, Subject, Date) to find every service that has the user's email:
signup, verification, password reset, receipts, security alerts. Streams message by message.
"""
from __future__ import annotations

from app.cancellation import Cancelled, check_cancel

import csv
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


# Google's own security mail when a third-party app gets account access / Sign in with Google
GOOGLE_GRANT = re.compile(r"(?P<app>[\w .&'-]{2,40}?)\s+(?:was granted access to|now has access to|connected to) your Google Account"
                          r"|signed in to (?P<app2>[\w .&'-]{2,40}) (?:with|using) Google", re.I)
BODY_RX = re.compile(r"verify your( \w+)? (email|account)|confirm your( \w+)? (email|account)|activate your account"
                     r"|reset your password|complete your registration", re.I)
BODY_BYTES = 20_000  # ponytail: first 20 KB of text/plain is enough for "verify your email"; raise if misses appear


def _body(msg) -> str:
    """First text/plain part, decoded, truncated. Attachments and HTML-only mail are skipped."""
    part = next((p for p in msg.walk() if p.get_content_type() == "text/plain" and not p.get_filename()), None)
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    try:
        return raw[:BODY_BYTES].decode(part.get_content_charset() or "utf-8", errors="replace")
    except LookupError:  # unknown charset name in the header
        return raw[:BODY_BYTES].decode("utf-8", errors="replace")


def classify(subject: str) -> str | None:
    s = subject.lower()
    for kind, rx in KINDS.items():
        check_cancel()
        if re.search(rx, s):
            return kind
    return None


def parse(path: str, src: str = "mail.mbox", source_coverage=None):
    try:
        box = mailbox.mbox(path, create=False)
    except Exception as e:
        raise ParseError("wrong_format", f"Cannot open mailbox: {e}", src)
    recs, n, skipped, unreadable = [], 0, 0, 0
    try:
        for i, key in enumerate(box.iterkeys()):
            check_cancel()
            try:  # one malformed message (bad charset, broken MIME) must not drop the whole mailbox
                rec = _record(box[key], i, src)
            except Cancelled:
                raise
            except Exception:
                unreadable += 1
                continue
            if rec == "skipped":
                skipped += 1
            elif rec is not None:
                n += 1
                rec.id = f"gm-acco-{n:05d}"
                recs.append(rec)
    finally:
        box.close()
    if not recs and not skipped:
        raise ParseError("wrong_format", "No account emails found in this mailbox", src)
    if source_coverage is not None:
        source_coverage.append({"name": src, "source": src, "platform": "gmail", "kind": "gmail_mail",
                                "status": "partial" if unreadable else "scanned", "records": len(recs), "skipped_spam_trash": skipped,
                                "detail": f"{len(recs)} account/newsletter records extracted; {skipped} spam/trash emails ignored"
                                          + (f"; {unreadable} unreadable emails skipped" if unreadable else "") + ". Other mail was not assessed."})
    cov = {"location": "not_assessed", "interest": "not_assessed", "contact": "not_assessed", "activity": "found" if recs else "not_found"}
    return recs, cov


def _record(msg, i, src):
    """One message -> account Record, 'skipped' for spam/trash, or None when it is not proof of an account."""
    if True:
        labels = {label.strip().casefold() for header in msg.get_all("X-Gmail-Labels", [])
                  for row in csv.reader([_h(header)]) for label in row}
        if labels & {"spam", "trash"}:
            return "skipped"
        subject = _h(msg.get("Subject"))
        name, addr = parseaddr(_h(msg.get("From")))
        if "@" not in addr:
            return None
        dom = base_domain(addr)
        if dom in PERSONAL:
            return None
        grant = GOOGLE_GRANT.search(subject) if dom == "google.com" else None
        kind = classify(subject)
        if not kind and not grant:
            # vague subject ("Hi Riya"): the body often says "verify your email". Strict list only: promos say "welcome" too.
            kind = "signup" if BODY_RX.search(_body(msg)) else None
        if grant:
            source, kind, dom_out = "google_signin", "signin_with_google", (grant.group("app") or grant.group("app2")).strip()
        elif kind:
            source, dom_out = "email", dom
        elif msg.get("List-Unsubscribe"):
            source, kind, dom_out = "newsletter", "subscription", dom  # on a mailing list: they hold your email
        else:
            return None  # personal mail is not proof of an account
        try:
            ts = parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            ts = None
        return Record("gm-acco-pending", PLATFORM, "account", f"{dom_out}: {subject[:90]}", ts,
                      sourceFile=src, recordRef=f"message {i + 1}",
                      meta={"domain": dom_out, "source": source, "email_kind": kind, "sender": name or addr})
