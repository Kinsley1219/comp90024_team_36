
import os
from datetime import datetime, timezone

### Bluesky crawler: collect posts by queries, clean, store in Elasticsearch using cursor tracking ###
EARLIEST_DATE = "2022-01-01T00:00:00Z"
QUERIES = [
    # Australia fuel
    'petrol Australia', 'fuel Australia', 'diesel Australia', 'petrol prices', 'fuel prices',
    # cost of living
    'cost of living Australia', 'inflation Australia', 'groceries Australia', 'rent Australia',
    'electricity Australia', 'energy bills Australia',
    # cities
    'petrol Sydney', 'petrol Melbourne', 'fuel Brisbane', 'rent Sydney', 'rent Melbourne',
    'cost of living Sydney', 'cost of living Melbourne',
    # WA
    'petrol Perth', 'fuel Perth', 'petrol Western Australia', 'fuel Western Australia',
    'WA petrol', 'WA fuel', 'FuelWatch',
    # news
    'petrol price Australia', 'fuel price Australia', 'diesel price Australia',
    'fuel excise Australia', 'fuel tax Australia', 'living costs Australia',
    'household bills Australia', 'transport costs Australia',
    'cost of living NSW', 'cost of living Victoria'
]

### Secrets and ES setup ###
def get_requests():
    import requests
    return requests

def read_secret(key, default=None):
    path = f"/secrets/default/es-secret/{key}"
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return os.getenv(key, default)

# def parse_time(t):
#     return datetime.fromisoformat(t.replace("Z", "+00:00"))

def query_id(query):
    return query.lower().replace(" ", "-").replace('"', "").replace("/", "-")

# Data cleaning and processing
def detect_flags(text):
    text = (text or "").lower()
    return {
        "is_fuel": any(k in text for k in ["petrol", "fuel", "diesel", "fuelwatch"]),
        "is_cost": any(k in text for k in [
            "cost of living", "living costs", "rent", "bill", "bills",
            "inflation", "grocery", "groceries", "electricity", "energy"
        ]),
        "is_au": any(k in text for k in [
            "australia", "sydney", "melbourne", "brisbane", "perth",
            "western australia", "nsw", "victoria", "fuelwatch", " wa "
        ])
    }

def make_doc(post, query):  # Convert raw Bluesky post to structured ES document
    rec = post.get("record", {})
    auth = post.get("author", {})
    flags = detect_flags(rec.get("text"))

    return {
        "url": post.get("uri"),
        "text": rec.get("text"),
        "author": auth.get("handle"),
        "query": query,
        "created_at": rec.get("createdAt"),
        "date": rec.get("createdAt")[:10] if rec.get("createdAt") else None,
        "platform": "bluesky",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "like": post.get("likeCount", 0),
        "reply": post.get("replyCount", 0),
        "repost": post.get("repostCount", 0),
        "is_fuel": flags["is_fuel"],
        "is_cost": flags["is_cost"],
        "is_au": flags["is_au"]
    }
