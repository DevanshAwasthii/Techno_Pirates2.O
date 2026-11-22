from app.engine.profile import build_profile
from app.engine.records import Record


def r(key, **meta):
    return Record(key, 'instagram', 'activity', '', meta.pop('timestamp', None), meta=meta)


def test_profile_sources_negative_feedback_and_sensitive_separation():
    records = [r('a', action='like', person='fictional_cyclist', caption='#Cycling #Photography'),
               r('b', action='not_interested', negative=True, caption='Football'),
               r('c', action='see_less', topic='Cars'),
               r('d', action='post_view', caption='Diabetes and elections, investing'),
               r('e', action='submitted_info', source='submitted_info', domain='fictional_brand', fields={'Email': ['fake@example.invalid']})]
    explicit = Record('f', 'spotify', 'interest', '', None, kind='inferred', inferenceOrigin='platform', meta={'topic': 'Jazz fans'})
    records.append(explicit)
    profile = build_profile(records)
    assert {'Cycling', 'Photography', 'Music'} <= {i['label'] for i in profile['interests']}
    assert not {'Football', 'Cars', 'Health', 'Politics', 'Finance'} & {i['label'] for i in profile['interests']}
    assert {'Health', 'Politics', 'Finance'} <= {i['label'] for i in profile['sensitive']}
    assert all(i['sensitive'] for i in profile['sensitive'])
    assert any(i['source'] == 'platform-inferred' for i in profile['interests'])
    assert len(profile['dislikes']) == 2
    assert profile['shopping'][0]['evidence'] == ['e']
    assert 'fake@example.invalid' not in str(profile['shopping'])
    assert profile['routine']['sleep_window'] is None
    for section in ('interests', 'likes', 'dislikes', 'shopping', 'sensitive', 'life_stage'):
        for item in profile[section]:
            assert {'label', 'confidence', 'source', 'evidence'} <= item.keys()
            assert set(item['evidence']) <= {r.id for r in records}


def test_routine_uses_activity_only_and_does_not_claim_sleep():
    records = [r(str(i), action='post_view', timestamp=f'2026-11-{i // 4 + 1:02}T18:{i % 4:02}:00') for i in range(28)]
    records.append(Record('creation', 'instagram', 'account', '', '2000-01-01T00:00:00'))
    p = build_profile(records)
    assert p['routine']['peak_hours'][0] == 18
    assert p['routine']['sleep_window']['confidence'] <= 0.35
    assert 'guess' in p['routine']['sleep_window']['label'].lower()
    assert 'creation' not in p['routine']['evidence']
    assert build_profile([])['interests'] == []
