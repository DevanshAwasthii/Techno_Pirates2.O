"""Archive age, a conservative deletion directory and illustrative advertising audiences."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path

from app.cancellation import check_cancel
from app.engine.profile import item
from app.engine.services import canonical_service_key


@lru_cache(maxsize=1)
def deletion_directory():
    return json.loads(Path(__file__).with_name('data').joinpath('deletion.json').read_text(encoding='utf-8'))


def build_extras(records, profile):
    dated, accounts = {}, defaultdict(list)
    directory = {}
    for reference in deletion_directory():
        for alias in (reference['service'], *reference['match_domains']):
            directory.setdefault(canonical_service_key(alias), reference)
    for r in records:
        check_cancel()
        if r.timestamp:
            try:
                date = datetime.fromisoformat(r.timestamp.replace('Z', '+00:00')).date().isoformat()
                previous = dated.get(r.platform)
                if previous is None or date < previous[0]:
                    dated[r.platform] = (date, [r.id])
                elif date == previous[0]:
                    previous[1].append(r.id)
            except (TypeError, ValueError, OverflowError):
                pass
        if r.category == 'account' and r.meta.get('domain'):
            accounts[canonical_service_key(r.meta['domain'])].append(r.id)
    ages = []
    for platform, (oldest, evidence) in sorted(dated.items()):
        ages.append(item(f'{platform}: tracked since at least {oldest} (oldest exported record)',
                         evidence, 0.9,
                         platform=platform, oldest=oldest,
                         note='Archive lower bound only; not the actual start of tracking. Export timezones may differ.'))
    deletion = []
    for key, evidence in sorted(accounts.items()):
        reference = directory.get(key, {'service': key, 'url': None, 'status': 'unknown', 'official_domains': []})
        deletion.append(item('Delete account: ' + reference['service'], evidence, 0.9, **reference,
                             note='Offline reference; menu paths and eligibility may change. No account action is performed.'))
    preview = [item('Illustrative audience: ' + affinity['label'], affinity['evidence'], affinity['confidence'],
                    note='Possible category suggested by this export; current advertiser availability and actual targeting are unverified.')
               for affinity in profile.get('interests', [])]
    return {'data_age': ages, 'deletion': deletion, 'ad_targeting': preview,
            'directory': deletion_directory(), 'directory_note': 'Hand-authored offline reference. Unknown routes are deliberately left blank.'}
