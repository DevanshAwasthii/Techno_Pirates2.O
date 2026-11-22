"""Deterministic fictional Instagram HTML fixture for the offline profile views."""
from html import escape
from pathlib import Path
import zipfile


def box(**fields):
    return '<div class="_a6-g"><table>' + ''.join(
        f'<tr><td class="_a6_q">{escape(k)}<div>{escape(v)}</div></td></tr>' for k, v in fields.items()
    ) + '</table></div>'


def build(path):
    pages = {
        'personal_information/personal_information/personal_information.html': box(Name='demo.self'),
        'connections/followers_and_following/followers_1.html': '<div class="_a6-g"><h2>demo.friend</h2></div>',
        'connections/followers_and_following/following.html': '<div class="_a6-g"><h2>demo.friend</h2></div>',
        'story_interactions/stories_viewed.html': box(Username='demo.friend', Caption='Cycling #Jaipur', Time='Nov 1, 2026 9:00 pm'),
        'story_interactions/story_likes.html': box(Owner='demo.friend', Time='Nov 1, 2026 9:00 pm'),
        'ads_and_topics/posts_viewed.html': box(Author='demo.photographer', Caption='Photography #Mumbai', Time='Nov 2, 2026 6:00 pm'),
        'ads_and_topics/videos_watched.html': box(Username='demo.chef', Caption='Cooking recipes', Time='Nov 2, 2026 7:00 pm'),
        'saved/saved_posts.html': box(Owner='demo.friend', Caption='Book club', Time='Nov 2, 2026 8:00 pm'),
        'media/reposts.html': box(Owner='demo.friend', Caption='Cycling', Time='Nov 2, 2026 8:15 pm'),
        'media/posts.html': box(Caption='Photography #Jaipur', Latitude='26.9124', Longitude='75.7873', Time='Nov 10, 2026 9:00 am'),
        'media/stories.html': box(Caption='A walk #Jaipur', **{'Date taken': '2026-11-10T08:00:00', 'Device': 'Fictional camera'}),
        "ads_and_topics/posts_you're_not_interested_in.html": box(Caption='Football', Feedback='Not interested'),
        "ads_and_topics/posts_you're_interested_or_not_interested_in.html": box(Caption='Cars', Feedback='Not interested'),
        'your_ads/see_more_topics.html': box(Name='Gardening'),
        'your_ads/see_less_topics.html': box(Name='Cars'),
        "instagram_ads_and_businesses/information_you've_submitted_to_advertisers.html": box(Advertiser='Fictional shop', Email='demo@example.invalid'),
        'past_instagram_insights/audience_insights.html': box(Country='India', Age='25-34'),
        'messages/inbox/demo_friend/message_1.html': '<div class="_a6-g"><h2>demo.friend</h2><p>Hello, fictional friend.</p><div class="_a6-o">Nov 1, 2026 9:00 pm</div></div>',
    }
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, html in pages.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, html)


if __name__ == '__main__':
    build(Path(__file__).with_name('instagram_activity_demo.zip'))
