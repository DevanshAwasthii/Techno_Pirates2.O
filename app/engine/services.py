"""Conservative company identity for counting; source records stay unchanged.

Uses common country-code second-level suffixes, not a full public suffix list.
Aliases are explicit so unrelated services are never merged by substring.
"""
import re
from urllib.parse import urlsplit

SECOND_LEVEL = {'co', 'com', 'net', 'org', 'ac', 'gov', 'edu'}
ALIASES = {'facebookmail': 'facebook', 'facebook.net': 'facebook', 'x': 'twitter'}


def canonical_service_key(value: str) -> str:
    value = value.strip().lower().strip('.')
    if '://' in value:
        value = urlsplit(value).hostname or value
    if '@' in value:
        value = value.rsplit('@', 1)[-1]
    if '.' in value and not any(c.isspace() for c in value):
        parts = value.split('.')
        index = -3 if len(parts) >= 3 and parts[-2] in SECOND_LEVEL and len(parts[-1]) == 2 else -2
        value = ALIASES.get('.'.join(parts[-2:]), parts[index])
    key = re.sub(r'[^\w]', '', value)
    return ALIASES.get(key, key)


def first_party_tracker_ids(records):
    """Account mail applies across imports; saved logins apply to their own profile."""
    accounts, saved = set(), set()
    for record in records:
        if record.category != "account" or not record.meta.get("domain"):
            continue
        key = canonical_service_key(record.meta["domain"])
        source = record.meta.get("source")
        if source in {"email", "google_signin"}:
            accounts.add(key)
        elif source == "saved_login":
            saved.add((record.meta.get("profile_id", record.sourceFile), key))
    return {record.id for record in records if record.meta.get("source") == "tracker"
            and (canonical_service_key(record.meta["domain"]) in accounts
                 or (record.meta.get("profile_id", record.sourceFile), canonical_service_key(record.meta["domain"])) in saved)}
