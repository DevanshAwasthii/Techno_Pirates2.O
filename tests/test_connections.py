from app.engine.connections import build_connections
from app.engine.places import build_places
from app.engine.records import Record


def rec(key, action=None, **meta):
    category = meta.pop('category', 'activity')
    timestamp = meta.pop('timestamp', '2026-01-01T12:00:00')
    return Record(key, 'instagram', category, '', timestamp,
                  meta={'person': 'fictional_friend', 'action': action, **meta})


def test_weighted_mutual_connections_shared_mentions_and_direction():
    records = [rec('f', relation='follower', category='contact'), rec('g', relation='following', category='contact'),
               rec('s', 'story_view', caption='#Jaipur'), rec('l', 'story_like'), rec('p', 'like'),
               rec('c', 'comment'), rec('v', 'save'), rec('r', 'repost'),
               rec('m', category='message', direction='out', person='fictional_self', thread=['fictional_friend']),
               rec('own', 'post', is_own=True, person='fictional_self', caption='#Jaipur', timestamp='2026-02-15T00:00:00')]
    result = build_connections(records, build_places(records))
    assert len(result) == 1
    connection = result[0]
    assert connection['relationship'] == 'mutual (follow both ways + chat)'
    assert connection['counts']['story_view'] == 1 and connection['counts']['dm'] == 1
    assert connection['score'] > 10 and connection['source'] == 'NexData-inferred'
    assert any('you watch their stories' in x for x in connection['labels'])
    assert all('all your' not in x for x in connection['labels'])
    assert connection['places'][0]['timestamp'] == '2026-01-01T12:00:00'
    shared = connection['shared_places'][0]
    assert set(shared['evidence']) == {'s', 'own'}
    assert 'co-location unconfirmed' in shared['label']
    assert set(connection['evidence']) == {r.id for r in records if r.id != 'own'}


def test_groups_platform_identity_and_sixty_day_boundary():
    records = [rec('s', 'story_view', caption='#Jaipur'),
               rec('o', 'post', is_own=True, caption='#Jaipur', timestamp='2026-04-01'),
               rec('group', category='message', group=True, direction='out', thread=['a', 'b'])]
    other = rec('w', 'like')
    other.platform = 'whatsapp'
    records.append(other)
    result = build_connections(records, build_places(records))
    assert len(result) == 2  # no cross-platform identity guessing, no group-DM attribution
    assert all(not c['shared_places'] for c in result)
    assert sum(c['counts'].get('dm', 0) for c in result) == 0
