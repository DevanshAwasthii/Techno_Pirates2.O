from app.engine.places import find_mentions, nearest_place, build_places, gazetteer
from app.engine.records import Record


def test_offline_catalog_boundaries_and_ambiguous_words():
    assert len(gazetteer()) >= 480
    names = {p['name'] for p in find_mentions('A trip to NEW DELHI and #Mumbai; Taj Mahal. Nice day reading a book in march.')}
    assert {'New Delhi', 'Mumbai', 'Taj Mahal'} <= names
    assert not {'Nice', 'Reading', 'March'} & names
    assert not find_mentions('Mumbaikar delimumbai nicely')
    assert any(p['name'] == 'New Delhi' for p in find_mentions('#NewDelhi'))
    assert nearest_place(26.9124, 75.7873)['name'] == 'Jaipur'
    assert nearest_place(float('nan'), 0) is None
    assert nearest_place(999, 0) is None
    assert nearest_place(0, -140) is None


def test_place_evidence_does_not_turn_viewed_content_into_visits():
    records = [Record('view', 'instagram', 'activity', '', '2026-01-01', meta={
        'person': 'fictional_friend', 'action': 'story_view', 'caption': '#Jaipur'}),
        Record('own', 'instagram', 'activity', '', '2026-01-10', meta={
            'is_own': True, 'action': 'post', 'lat': 26.9124, 'lon': 75.7873}),
        Record('mention', 'instagram', 'activity', '', None, meta={
            'is_own': True, 'caption': 'Dreaming of Tokyo'})]
    places = build_places(records)
    assert all(p['source'] == 'NexData-inferred' and p['evidence'] for p in places)
    assert next(p for p in places if p['evidence'] == ['view'])['association'] == 'viewed content'
    assert next(p for p in places if p['evidence'] == ['own'])['association'] == 'coordinate recorded'
    assert next(p for p in places if p['evidence'] == ['mention'])['association'] == 'your mention (visit unconfirmed)'


def test_mentions_preserve_overlaps_compound_hashtags_and_unicode_case():
    assert {'India', 'Gateway of India'} <= {p['name'] for p in find_mentions('Gateway of India')}
    for text in ('#NewDelhi', '#New_Delhi', 'NEW\nDELHI', 'NewDelhiIndia'):
        assert 'New Delhi' in {p['name'] for p in find_mentions(text)}
    assert 'India' in {p['name'] for p in find_mentions('İndia')}
    assert 'Istanbul' in {p['name'] for p in find_mentions('ıstanbul')}


def test_ordinary_reading_cannot_create_a_false_shared_place():
    from app.engine.connections import build_connections
    records = [Record('own', 'instagram', 'activity', '', '2026-01-01', meta={
        'is_own': True, 'caption': 'I am interested in reading'}),
        Record('view', 'instagram', 'activity', '', '2026-01-02', meta={
            'person': 'fictional_friend', 'action': 'story_view', 'caption': 'I am interested in reading'})]
    places = build_places(records)
    assert places == []
    assert build_connections(records, places)[0]['shared_places'] == []
    assert 'Nice' in {p['name'] for p in find_mentions('#Nice')}
    tagged = Record('tag', 'instagram', 'activity', '', None, meta={'hashtags': ['Nice']})
    assert build_places([tagged])[0]['name'] == 'Nice'
