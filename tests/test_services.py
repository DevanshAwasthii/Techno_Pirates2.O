from app.engine.records import Record
from app.engine.rules import build_findings, build_graph


def account(i, domain, source='email', platform='gmail'):
    return Record(str(i), platform, 'account', domain, None,
                  meta={'domain': domain, 'source': source})


def test_company_names_domains_and_email_subdomains_merge():
    records = [account(1, 'Myntra', 'advertiser', 'instagram'),
               account(2, 'myntra.com', 'off_meta', 'instagram'),
               account(3, 'e.myntra.com'), account(4, 'www.myntra.com', 'saved_login', 'chrome'),
               account(5, 'Canva', 'google_signin'), account(6, 'canva.com')]
    findings, summary = build_findings(records)
    assert summary['servicesFound'] == 2
    mail = next(f for f in findings if 'services have your email' in f.title)
    assert mail.metric['value'] == 2
    assert set(mail.evidence) == {'3', '6'}
    graph = build_graph(records, summary)
    assert len([n for n in graph['nodes'] if n['id'].startswith('svc:')]) == 2
    assert {e for edge in graph['edges'] for e in edge['evidence']} == {r.id for r in records}
    assert records[2].meta['domain'] == 'e.myntra.com'


def test_aliases_country_suffixes_and_distinct_companies():
    from app.engine.services import canonical_service_key
    for value in ('Facebook', 'mail.facebookmail.com', 'facebook.com'):
        assert canonical_service_key(value) == 'facebook'
    for value in ('Amazon', 'amazon.in', 'email.amazon.com', 'no-reply.amazon.co.in'):
        assert canonical_service_key(value) == 'amazon'
    assert canonical_service_key('https://news.irctc.co.in/') == 'irctc'
    assert canonical_service_key('QuizMaster Pro') == 'quizmasterpro'
    assert canonical_service_key('QuizMaster Pro') != canonical_service_key('QuizMaster')
    assert canonical_service_key('myntra.com') != canonical_service_key('canva.com')
    records = [account(i, v) for i, v in enumerate(('amazon.in', 'amazon.com', 'myntra.com', 'canva.com'))]
    findings, summary = build_findings(records)
    assert summary['servicesFound'] == 3
    assert next(f for f in findings if 'services have your email' in f.title).metric['value'] == 3


import pytest


@pytest.mark.parametrize("domain,login", [("facebook.com", "facebook.com"), ("facebook.net", "facebook.com"),
                                         ("linkedin.com", "linkedin.com"), ("x.com", "twitter.com"),
                                         ("twitter.com", "x.com"), ("bing.com", "bing.com"), ("tiktok.com", "tiktok.com")])
def test_first_party_tracker_excluded_only_with_account_relationship(domain, login):
    tracker = account('t', domain, 'tracker', 'chrome')
    tracker.meta['profile_id'] = 'one'
    assert build_findings([tracker])[1]['trackersFound'] == 1
    saved = account('login', login, 'saved_login', 'chrome')
    saved.meta['profile_id'] = 'one'
    findings, summary = build_findings([tracker, saved])
    assert summary['trackersFound'] == 0
    assert all(f.metric['unit'] != 'trackers' for f in findings)
    graph = build_graph([tracker, saved], summary)
    assert next(n for n in graph['nodes'] if n['id'].startswith('svc:'))['type'] == 'service'
    saved.meta['profile_id'] = 'two'
    assert build_findings([tracker, saved])[1]['trackersFound'] == 1
    email = account('email', login)
    assert build_findings([tracker, email])[1]['trackersFound'] == 0
    # An advertiser listing alone is not proof of a user account.
    advertiser = account('adv', login, 'advertiser', 'instagram')
    assert build_findings([tracker, advertiser])[1]['trackersFound'] == 1
    assert tracker.meta['source'] == 'tracker'
