from app.engine.records import Record
from app.engine.rules import build_findings, build_graph


def test_cluster_graph_bounds_size_and_keeps_every_service_and_evidence():
    domains = ['myntra.com', 'e.myntra.com', 'swiggy.com', 'hdfcbank.com', 'irctc.co.in',
               'facebook.com', 'naukri.com', 'doubleclick.net'] + [f'unknown{i}.com' for i in range(120)]
    records = [Record(str(i), 'chrome', 'account', domain, None,
                      meta={'domain': domain, 'source': 'tracker' if domain == 'doubleclick.net' else 'saved_login'})
               for i, domain in enumerate(domains)]
    _, summary = build_findings(records)
    graph = build_graph(records, summary)
    clusters = [n for n in graph['nodes'] if n['type'] == 'cluster']
    assert len(clusters) == 8
    assert len(graph['nodes']) == 9
    assert sum(n['size'] for n in clusters) == len(domains) - 1
    members = [s for n in clusters for s in n['services']]
    assert len({s['id'] for s in members}) == len(members)
    assert {e for s in members for e in s['evidence']} == {r.id for r in records}
    shopping = next(n for n in clusters if n['label'] == 'Shopping')
    assert shopping['services'][0]['evidence'] == ['0', '1']
    assert next(n for n in clusters if n['label'] == 'Other')['size'] == 120
    assert {e for edge in graph['edges'] for e in edge['evidence']} == {r.id for r in records}


def test_cluster_services_link_to_matching_findings():
    from app.ui.main import service_findings
    result = {'findings': [{'id': 'F1', 'evidence': ['one']}, {'id': 'F2', 'evidence': ['two']} ]}
    assert service_findings(result, {'evidence': ['one', 'three']}) == [result['findings'][0]]
    assert service_findings(result, {'evidence': []}) == []
