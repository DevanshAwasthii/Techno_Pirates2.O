"""Synthetic Instagram activity pages; no personal export data."""
import zipfile

from app.parsers import instagram_activity


def box(**fields):
    return '<div class="_a6-g"><table>' + ''.join(
        f'<tr><td class="_a6_q">{k}<div>{v}</div></td></tr>' for k, v in fields.items()
    ) + '</table></div>'


def test_activity_metadata_and_all_sections(tmp_path):
    pages = {
        'story_interactions/stories_viewed': dict(Username='fictional_creator', Caption='Cycling #Jaipur', Time='Nov 1, 2026 9:00 pm'),
        'story_interactions/story_likes': dict(Owner='fictional_creator'),
        'ads_and_topics/posts_viewed': dict(Author='fictional_creator', Caption='Book club'),
        'ads_and_topics/videos_watched': dict(Username='fictional_creator'),
        'saved/saved_posts': dict(Owner='fictional_creator'),
        'media/reposts': dict(Owner='fictional_creator'),
        'media/posts': dict(Caption='A walk #Jaipur', Latitude='26.9124', Longitude='75.7873'),
        'media/stories': {'Caption': 'A walk', 'Date taken': '2026-11-02T06:00:00', 'Device': 'Synthetic camera'},
        "ads_and_topics/posts_you're_not_interested_in": dict(Owner='fictional_brand', Caption='Fitness'),
        "ads_and_topics/posts_you're_interested_or_not_interested_in": dict(Feedback='Not interested', Caption='Football'),
        'your_ads/see_more_topics': dict(Name='Cycling'),
        'your_ads/see_less_topics': dict(Name='Cars'),
        "instagram_ads_and_businesses/information_you've_submitted_to_advertisers": dict(Advertiser='Fictional shop', Email='fake@example.invalid'),
        'past_instagram_insights/audience_insights': dict(Country='India', Age='25-34'),
    }
    archive = tmp_path / 'synthetic.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for name, fields in pages.items():
            z.writestr('your_instagram_activity/' + name + '.html', box(**fields))
        z.writestr('unrelated.html', box(Caption='ignored'))
    with zipfile.ZipFile(archive) as z:
        records, coverage, owner = instagram_activity.parse(z, owner='fictional_self')
    assert len(records) == len(pages)
    assert len({r.id for r in records}) == len(records)
    assert coverage['activity'] == 'found'
    viewed = next(r for r in records if r.meta.get('action') == 'story_view')
    assert viewed.meta['person'] == 'fictional_creator'
    assert viewed.meta['hashtags'] == ['Jaipur']
    assert viewed.timestamp == '2026-11-01T21:00:00'
    post = next(r for r in records if r.meta.get('action') == 'post')
    assert (post.meta['lat'], post.meta['lon']) == (26.9124, 75.7873)
    assert post.meta['is_own'] and post.meta['person'] == owner
    story = next(r for r in records if r.meta.get('action') == 'story')
    assert story.meta['device'] == 'Synthetic camera'
    assert story.timestamp == '2026-11-02T06:00:00'
    assert sum(r.meta.get('negative', False) for r in records) == 3
    assert all('/' in r.sourceFile for r in records)


def test_invalid_coordinates_and_empty_archive(tmp_path):
    archive = tmp_path / 'synthetic.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('media/posts.html', box(Latitude='nan', Longitude='999'))
    with zipfile.ZipFile(archive) as z:
        records, _, _ = instagram_activity.parse(z)
    assert records[0].meta.get('lat') is None
    with zipfile.ZipFile(archive, 'w'):
        pass
    with zipfile.ZipFile(archive) as z:
        assert instagram_activity.parse(z)[0] == []
