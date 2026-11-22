"""Extensible local taxonomy for explicit content/domain classification."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Topic:
    primary: str
    secondary: str
    name: str
    keywords: tuple[str, ...]
    domains: tuple[str, ...] = ()


TOPICS = (
    Topic("Technology", "Programming", "Python", ("python", "pypi", "django"), ("python.org", "pypi.org")),
    Topic("Technology", "Programming", "Web Development", ("javascript", "typescript", "web development", "html", "css"), ("developer.mozilla.org",)),
    Topic("Technology", "Programming", "Software Development", ("programming", "developer", "coding", "github", "software engineering"), ("github.com", "stackoverflow.com")),
    Topic("Technology", "Artificial Intelligence", "Machine Learning", ("machine learning", "artificial intelligence", "generative ai", "neural network", " ai "), ("huggingface.co",)),
    Topic("Technology", "Artificial Intelligence", "LLMs", ("llm", "large language model", "prompt engineering")),
    Topic("Technology", "Hardware", "Computers", ("hardware", "computer", "laptop", "processor")),
    Topic("Technology", "Hardware", "Robotics", ("robotics", "robot", "electronics", "arduino")),
    Topic("Education", "Learning", "Tutorials", ("course", "tutorial", "learn", "education", "study", "university"), ("coursera.org", "edx.org", "khanacademy.org")),
    Topic("Science", "Astronomy", "Space", ("astronomy", "space", "nasa", "telescope", "planet"), ("nasa.gov",)),
    Topic("Entertainment", "Music", "Music", ("music", "song", "album", "playlist", "artist", "spotify", "jazz", "rock music", "hip hop", "hiphop", "bollywood", "classical", "indie", "pop music"), ("spotify.com",)),
    Topic("Entertainment", "Gaming", "Gaming", ("gaming", "videogames", "video games", "game", "esports", "playstation", "xbox", "steam"), ("store.steampowered.com",)),
    Topic("Travel", "Travel", "Travel", ("travel", "travelling", "traveling", "backpacking", "wanderlust", "trip", "flight", "hotel", "tourism")),
    Topic("Creative Arts", "Photography", "Photography", ("photography", "photographer", "photo editing", "camera gear", "camera", "photo", "image", "lens")),
    Topic("Commerce", "Shopping", "Shopping", ("shopping", "purchase", "product", "store", "deal")),
    Topic("Lifestyle", "Lifestyle", "Lifestyle", ("food", "recipe", "fashion", "home", "wellness")),
    Topic("Business", "Business", "Business", ("business", "startup", "marketing", "entrepreneur", "small business")),
)


# Preserve the desktop profile vocabulary in this shared hierarchy.
TOPICS += (
    Topic('Sports', 'Cycling', 'Cycling', ('cycling', 'bicycle', 'biking', 'cyclist')),
    Topic('Lifestyle', 'Fitness', 'Fitness', ('fitness', 'workout', 'gym', 'bodybuilding', 'strength training')),
    Topic('Sports', 'Running', 'Running', ('running', 'marathon', 'jogging', 'runner')),
    Topic('Lifestyle', 'Yoga', 'Yoga', ('yoga', 'pilates', 'meditation')),
    Topic('Lifestyle', 'Food & cooking', 'Food & cooking', ('cooking', 'recipes', 'foodie', 'baking', 'chef', 'cuisine')),
    Topic('Lifestyle', 'Coffee & tea', 'Coffee & tea', ('coffee', 'espresso', 'barista', 'chai', 'tea brewing')),
    Topic('Creative Arts', 'Dance', 'Dance', ('dance', 'dancing', 'choreography', 'bharatanatyam', 'kathak')),
    Topic('Entertainment', 'Film & television', 'Film & television', ('cinema', 'movies', 'film', 'netflix', 'television', 'anime')),
    Topic('Creative Arts', 'Books & writing', 'Books & writing', ('books', 'reading', 'bookclub', 'book club', 'literature', 'poetry', 'writing')),
    Topic('Technology', 'Technology', 'Technology', ('technology', 'software', 'coding', 'programming', 'artificial intelligence', 'gadgets')),
    Topic('Science', 'Science', 'Science', ('science', 'physics', 'astronomy', 'space exploration', 'chemistry')),
    Topic('Education', 'Education', 'Education', ('education', 'student', 'university', 'college', 'study tips', 'exam', 'learning')),
    Topic('Education', 'Careers', 'Careers', ('career', 'job search', 'interview', 'recruitment', 'resume', 'professional development')),
    Topic('Lifestyle', 'Fashion', 'Fashion', ('fashion', 'outfit', 'streetwear', 'style tips', 'clothing')),
    Topic('Lifestyle', 'Beauty', 'Beauty', ('beauty', 'makeup', 'skincare', 'cosmetics')),
    Topic('Lifestyle', 'Home & design', 'Home & design', ('interior design', 'home decor', 'furniture', 'architecture', 'renovation')),
    Topic('Lifestyle', 'Gardening', 'Gardening', ('gardening', 'houseplants', 'horticulture', 'garden')),
    Topic('Lifestyle', 'Pets & animals', 'Pets & animals', ('pets', 'dogs', 'cats', 'wildlife', 'animal rescue')),
    Topic('Sports', 'Football', 'Football', ('football', 'soccer', 'premier league', 'fifa')),
    Topic('Sports', 'Cricket', 'Cricket', ('cricket', 'ipl', 'batsman', 'bowling', 't20')),
    Topic('Sports', 'Other sports', 'Other sports', ('basketball', 'tennis', 'badminton', 'swimming', 'hockey', 'volleyball')),
    Topic('Sports', 'Outdoors', 'Outdoors', ('hiking', 'trekking', 'camping', 'mountaineering', 'surfing')),
    Topic('Lifestyle', 'Cars', 'Cars', ('cars', 'automotive', 'motorsport', 'formula1', 'formula 1', 'motorcycle')),
    Topic('Creative Arts', 'Art & crafts', 'Art & crafts', ('painting', 'drawing', 'crafts', 'sculpture', 'illustration', 'pottery')),
    Topic('Lifestyle', 'Parenting', 'Parenting', ('parenting', 'baby care', 'childcare', 'newborn', 'motherhood', 'fatherhood')),
    Topic('Lifestyle', 'Weddings', 'Weddings', ('wedding', 'bridal', 'bride', 'groom', 'marriage planning')),
    Topic('Lifestyle', 'Sustainability', 'Sustainability', ('sustainability', 'recycling', 'climate', 'zero waste', 'eco friendly')),
    Topic('Sensitive content', 'Health', 'Health', ('health', 'diabetes', 'therapy', 'mental health', 'nutrition', 'medical', 'depression')),
    Topic('Sensitive content', 'Religion', 'Religion', ('religion', 'hindu', 'muslim', 'christian', 'sikh', 'buddhist', 'prayer', 'spirituality')),
    Topic('Sensitive content', 'Politics', 'Politics', ('politics', 'election', 'elections', 'parliament', 'political', 'democracy')),
    Topic('Sensitive content', 'Finance', 'Finance', ('finance', 'investing', 'investment', 'stocks', 'mutual funds', 'credit', 'loan', 'insurance')),
)

SENSITIVE = {"Health", "Religion", "Politics", "Finance"}
POSITIVE = {'story_view', 'story_like', 'like', 'comment', 'save', 'repost', 'post_view', 'video_view', 'see_more'}

PATTERNS = {}
for topic in TOPICS:
    words = [word for t in TOPICS if t.secondary == topic.secondary for word in t.keywords]
    PATTERNS[topic.secondary] = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(w.strip()) for w in words) + r')(?!\w)', re.I)

KEYWORD_PATTERNS = tuple((topic, tuple((word, re.compile(r'(?<!\w)' + re.escape(word.strip()) + r'(?!\w)', re.I))
                                     for word in topic.keywords)) for topic in TOPICS)


def classify(text: str, domain: str = "") -> list[tuple[Topic, str, float]]:
    """Explicit keyword or weak domain evidence, with word/domain boundaries."""
    text = (text or '').casefold()
    domain = domain.casefold().strip('.')
    results = []
    for topic, patterns in KEYWORD_PATTERNS:
        keyword = next((word for word, pattern in patterns if pattern.search(text)), None)
        domain_hit = next((d for d in topic.domains if domain == d or domain.endswith('.' + d)), None)
        if keyword:
            results.append((topic, f"content keyword '{keyword}'", .60))
        elif domain_hit:
            results.append((topic, f"known domain '{domain_hit}' without content confirmation", .35))
    return results
