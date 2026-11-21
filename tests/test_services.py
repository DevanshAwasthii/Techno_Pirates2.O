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
