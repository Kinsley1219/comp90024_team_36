# COMP90024 Team 36
# Reddit crawler - fetches posts from Australian subreddits
# This module handles all data collection from Reddit public JSON API

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime, timezone

# Initialise VADER sentiment analyser (shared across all calls for efficiency)
sentiment_analyzer = SentimentIntensityAnalyzer()

# Query phrases to match against post content - aligned with Bluesky crawler
QUERIES = [
    'petrol Australia', 'fuel Australia', 'diesel Australia', 'petrol prices', 'fuel prices',
    'cost of living Australia', 'inflation Australia', 'groceries Australia', 'rent Australia',
    'electricity Australia', 'energy bills Australia',
    'petrol Sydney', 'petrol Melbourne', 'fuel Brisbane', 'rent Sydney', 'rent Melbourne',
    'cost of living Sydney', 'cost of living Melbourne',
    'petrol Perth', 'fuel Perth', 'petrol Western Australia', 'fuel Western Australia',
    'WA petrol', 'WA fuel', 'FuelWatch',
    'petrol price Australia', 'fuel price Australia', 'diesel price Australia',
    'fuel excise Australia', 'fuel tax Australia',
    'living costs Australia', 'household bills Australia', 'transport costs Australia',
    'cost of living NSW', 'cost of living Victoria'
]

# Australian subreddits to harvest from
SUBREDDITS = [
    "australia", "sydney", "melbourne", "perth", "brisbane", "AusFinance",
    "Adelaide", "Canberra", "AusEcon", "AusPropertyChat",
    "AustralianPolitics", "CasualAU", "australian",
    "AusUnemployed", "AustralianMemes", "AussieFrugal",
    "PersonalFinanceAU", "AskAustralia", "AusSocialMedia"
]

# Topic keywords - a post must contain at least one to be considered relevant
# These prevent false positives where a location word alone (e.g. "Victoria")
# matches a query like "cost of living Victoria" without the topic context
TOPIC_KEYWORDS = [
    "petrol", "fuel", "diesel", "fuelwatch",
    "cost of living", "living costs",
    "inflation", "groceries", "grocery",
    "rent", "rental",
    "electricity", "energy bill", "energy bills", "power bill", "power bills",
    "fuel excise", "fuel tax",
    "household bills", "transport costs"
]

# Australian location keywords - used together with topic keywords
AU_LOCATIONS = [
    "australia", "australian", "sydney", "melbourne", "brisbane",
    "perth", "western australia", "nsw", "victoria",
    "queensland", "qld", "south australia", " sa ",
    "fuelwatch", " wa "
]

def detect_location(text, subreddit):
    """
    Detect the most likely Australian location from post text and subreddit.
    Uses subreddit as primary signal, then scans post text for city mentions.
    Returns a location string or 'Unknown' if no location can be determined.
    """
    # Primary: infer from subreddit name
    subreddit_location_map = {
        "sydney":    "Sydney",
        "melbourne": "Melbourne",
        "perth":     "Perth",
        "brisbane":  "Brisbane",
        "australia": "Australia",
        "ausfinance": "Australia"
    }

    # Check subreddit first (most reliable signal)
    subreddit_location = subreddit_location_map.get(subreddit.lower())

    # Secondary: scan post text for specific city mentions
    text_lower = (text or "").lower()
    text_locations = [
        ("Sydney",           ["sydney", "nsw", "new south wales"]),
        ("Melbourne",        ["melbourne", "victoria", " vic "]),
        ("Perth",            ["perth", "western australia", " wa ", "fuelwatch"]),
        ("Brisbane",         ["brisbane", "queensland", " qld "]),
        ("Adelaide",         ["adelaide", "south australia", " sa "]),
        ("Canberra",         ["canberra", "act", "australian capital territory"]),
        ("Darwin",           ["darwin", "northern territory", " nt "]),
        ("Hobart",           ["hobart", "tasmania", " tas "]),
        ("Australia",        ["australia", "australian"])
    ]

    # Find most specific text match
    matched_from_text = None
    for location, keywords in text_locations:
        if any(kw in text_lower for kw in keywords):
            matched_from_text = location
            break

    # Priority: subreddit location > text location > Unknown
    if subreddit_location and subreddit_location != "Australia":
        return subreddit_location
    elif matched_from_text and matched_from_text != "Australia":
        return matched_from_text
    elif subreddit_location == "Australia" or matched_from_text == "Australia":
        return "Australia"
    else:
        return "Unknown"

def calculate_sentiment(text):
    """
    Calculate sentiment score using VADER (Valence Aware Dictionary and sEntiment Reasoner).
    VADER is optimised for social media short texts.
    
    Scoring thresholds (standard VADER convention):
        compound >= 0.05  → positive
        compound <= -0.05 → negative
        otherwise         → neutral
    
    Returns a dict with sentiment_score (float) and sentiment_label (str).
    """
    if not text or not isinstance(text, str):
        return {
            "sentiment_score": 0.0,
            "sentiment_label": "neutral"
        }

    scores   = sentiment_analyzer.polarity_scores(text)
    compound = scores["compound"]

    if compound >= 0.05:
        label = "positive"
    elif compound <= -0.05:
        label = "negative"
    else:
        label = "neutral"

    return {
        "sentiment_score": compound,
        "sentiment_label": label
    }

def detect_flags(text):
    """
    Detect content category flags from post text.
    Returns a dict with boolean flags for fuel, cost-of-living, and Australia relevance.
    """
    text = (text or "").lower()
    return {
        "is_fuel": any(k in text for k in ["petrol", "fuel", "diesel", "fuelwatch"]),
        "is_cost": any(k in text for k in [
            "cost of living", "living costs", "rent", "bill", "bills",
            "inflation", "grocery", "groceries", "electricity", "energy"
        ]),
        "is_au": any(k in text for k in [
            "australia", "sydney", "melbourne", "brisbane",
            "perth", "western australia", "nsw", "victoria",
            "fuelwatch", " wa "
        ])
    }


def match_query(text, queries=QUERIES):
    """
    Match post text against query list.
    Relaxed matching to maximise data collection volume:
    - Full phrase match (highest confidence)
    - Topic keyword only (no location required)
    - Australian location mention only (no topic required)
    This captures broader cost-of-living and fuel discussions
    on Australian social media platforms.
    """
    text = (text or "").lower()

    # Rule 1: Direct full phrase match (highest confidence)
    for q in queries:
        if q.lower() in text:
            return q

    # Rule 2: Has any topic keyword - fuel/cost related
    has_topic = any(topic in text for topic in TOPIC_KEYWORDS)
    if has_topic:
        for topic in TOPIC_KEYWORDS:
            if topic in text:
                return f"{topic} Australia"

    # Rule 3: Has Australian location mention
    has_au = any(loc in text for loc in AU_LOCATIONS)
    if has_au:
        return "australia general"

    return None


def fetch_reddit_page(subreddit, limit=100, after=None):
    """
    Fetch one page of posts from a subreddit using Reddit public JSON API.
    No OAuth required - uses public .json endpoint.
    Returns a tuple of (list of post items, next page cursor).
    """
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; COMP90024RedditCrawler/0.1)"}
    params = {"limit": limit}

    if after:
        params["after"] = after

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        data = res.json().get("data", {})
        return data.get("children", []), data.get("after")
    except Exception as e:
        print(f"Reddit fetch error ({subreddit}): {e}")
        return [], None


def make_reddit_doc(item, query, subreddit):
    """
    Convert a raw Reddit API item into a normalised document schema.
    Schema is aligned with the Bluesky crawler for consistent ElasticSearch indexing.
    """
    p = item.get("data", {})

    # Combine title and body text for full-text content
    title = p.get("title", "") or ""
    selftext = p.get("selftext", "") or ""
    text = f"{title} {selftext}".strip()

    # Detect content category flags
    flags = detect_flags(text)
    sentiment = calculate_sentiment(text)
    location = detect_location(text, subreddit)

    # Convert Unix timestamp to ISO 8601 format
    created_ts = p.get("created_utc")
    if created_ts:
        created_dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
        created_at = created_dt.isoformat()
        date = created_dt.strftime("%Y-%m-%d")
    else:
        created_at = None
        date = None

    permalink = p.get("permalink")

    return {
        "uri": "reddit_" + str(p.get("id")),
        "text": text,
        "author": p.get("author"),
        "query": query,
        "created_at": created_at,
        "date": date,
        "platform": "reddit",
        "subreddit": subreddit,
        "url": "https://www.reddit.com" + permalink if permalink else None,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "like": p.get("score", 0),
        "reply": p.get("num_comments", 0),
        "repost": 0,
        "is_fuel": flags["is_fuel"],
        "is_cost": flags["is_cost"],
        "is_au": flags["is_au"],
        "sentiment_score": sentiment["sentiment_score"],
        "sentiment_label": sentiment["sentiment_label"],
        "matched_location": location
    }


def collect_reddit_history(max_pages=10):
    """
    One-time bootstrap collection to gather historical Reddit posts.
    Pages backwards through each subreddit up to max_pages pages.
    """
    posts = []

    for subreddit in SUBREDDITS:
        after = None
        for page_num in range(max_pages):
            items, after = fetch_reddit_page(
                subreddit=subreddit,
                limit=100,
                after=after
            )

            if not items:
                break

            for item in items:
                p = item.get("data", {})
                text = f"{p.get('title', '')} {p.get('selftext', '')}"

                query = match_query(text)
                if not query:
                    continue

                doc = make_reddit_doc(item, query, subreddit)

                if doc.get("uri") and doc.get("created_at"):
                    posts.append(doc)

            if not after:
                break

    return posts


def collect_reddit_realtime():
    """
    Collect only the latest page from each subreddit.
    Called by Fission timer trigger every 5 minutes.
    """
    return collect_reddit_history(max_pages=1)


def collect_reddit_posts():
    """
    Backward-compatible alias for collect_reddit_realtime().
    """
    return collect_reddit_realtime()


if __name__ == "__main__":
    print("Testing Reddit crawler...")
    latest_docs = collect_reddit_realtime()
    print("Realtime collected:", len(latest_docs))
    print(latest_docs[:3])