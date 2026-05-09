# COMP90024 Team 36
# Reddit historical data import script
# Uses Arctic Shift API to fetch Reddit posts from 2022 to present
# Arctic Shift is a community-maintained Reddit archive (2005 to present)
# API: https://arctic-shift.photon-reddit.com

import requests
import time
import os
from datetime import datetime, timezone
from elasticsearch8 import Elasticsearch
from reddit_crawler import match_query, detect_flags, calculate_sentiment, detect_location, SUBREDDITS

# Arctic Shift API endpoint
ARCTIC_SHIFT_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"

# ElasticSearch index name
INDEX_NAME = "social-posts"

# Date range as Unix timestamps
# 2022-01-01 00:00:00 UTC = 1640995200
# 2025-02-17 00:00:00 UTC = 1739750400 (fill the gap)
# 2026-02-17 00:00:00 UTC = 1771286400 (where our bootstrap data starts)
START_TS = 1640995200   # 2022-01-01 00:00:00 UTC = 1640995200
END_TS   = 1771286400   # 2026-02-17 00:00:00 UTC (correct)

# Number of posts per API request (max 100)
BATCH_SIZE = 100

# Delay between requests to avoid rate limiting
REQUEST_DELAY = 1.0


def read_secret(key, default=None):
    """Read ES credentials from Fission secrets or environment variables."""
    path = f"/secrets/default/es-secret/{key}"
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return os.getenv(key, default)


def get_es():
    """Create and return an ElasticSearch client."""
    return Elasticsearch(
        read_secret("ES_HOST", "https://127.0.0.1:9200"),
        basic_auth=(
            read_secret("ES_USER", "elastic"),
            read_secret("ES_PASSWORD", "elastic")
        ),
        verify_certs=False,
        request_timeout=30
    )


def fetch_arctic_shift_page(subreddit, after_ts, before_ts, after_id=None):
    """
    Fetch one page of posts from Arctic Shift API.
    Uses Unix timestamps for date range and post ID for pagination.
    Returns a list of raw post objects.
    """
    params = {
        "subreddit": subreddit,
        "after":     str(after_ts),
        "before":    str(before_ts),
        "limit":     BATCH_SIZE,
        "sort":      "asc",
    }

    # Add pagination cursor if provided
    if after_id:
        params["after_id"] = f"t3_{after_id}"

    try:
        res = requests.get(ARCTIC_SHIFT_URL, params=params, timeout=30)
        res.raise_for_status()
        data = res.json()
        return data.get("data", [])
    except Exception as e:
        print(f"[arctic_shift] Error fetching {subreddit}: {e}")
        return []


def convert_arctic_post(post, query, subreddit):
    """
    Convert Arctic Shift post format into our normalised ES document schema.
    Arctic Shift uses Reddit's native post format, same as the .json API.
    """
    title    = post.get("title", "") or ""
    selftext = post.get("selftext", "") or ""
    text     = f"{title} {selftext}".strip()

    # Use same flag detection as realtime crawler
    flags = detect_flags(text)
    sentiment = calculate_sentiment(text)
    location  = detect_location(text, subreddit)

    # Convert Unix timestamp to ISO 8601
    created_ts = post.get("created_utc")
    if created_ts:
        created_dt = datetime.fromtimestamp(float(created_ts), tz=timezone.utc)
        created_at = created_dt.isoformat()
        date       = created_dt.strftime("%Y-%m-%d")
    else:
        created_at = None
        date       = None

    permalink = post.get("permalink", "") or ""

    return {
        "uri":         "reddit_" + str(post.get("id")),
        "text":        text,
        "author":      post.get("author"),
        "query":       query,
        "created_at":  created_at,
        "date":        date,
        "platform":    "reddit",
        "subreddit":   subreddit,
        "url":         "https://www.reddit.com" + permalink if permalink else None,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "like":        post.get("score", 0),
        "reply":       post.get("num_comments", 0),
        "repost":      0,
        "is_fuel":     flags["is_fuel"],
        "is_cost":     flags["is_cost"],
        "is_au":       flags["is_au"],
        "sentiment_score": sentiment["sentiment_score"],
        "sentiment_label": sentiment["sentiment_label"],
        "matched_location": location
    }

def import_subreddit_history(es, subreddit, start_ts, end_ts):
    """
    Import all matching posts from a subreddit within the Unix timestamp range.
    Queries month by month to stay within API limits.
    Returns total count of saved posts.
    """
    print(f"\n[{subreddit}] Starting import...")

    saved  = 0
    errors = 0

    # Generate monthly time windows
    # API rejects large date ranges, so we query one month at a time
    from datetime import timedelta
    current = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    end_dt  = datetime.fromtimestamp(end_ts,   tz=timezone.utc)

    while current < end_dt:
        # Calculate end of this month window
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)

        window_end = min(next_month, end_dt)
        window_start_ts = int(current.timestamp())
        window_end_ts   = int(window_end.timestamp())

        month_label = current.strftime("%Y-%m")
        last_id     = None
        page        = 0
        month_saved = 0

        # Paginate through this month
        while True:
            page += 1
            posts = fetch_arctic_shift_page(
                subreddit=subreddit,
                after_ts=window_start_ts,
                before_ts=window_end_ts,
                after_id=last_id
            )

            if not posts:
                break

            for post in posts:
                text  = f"{post.get('title', '')} {post.get('selftext', '')}"
                query = match_query(text)

                if query:
                    doc = convert_arctic_post(post, query, subreddit)
                    if doc.get("uri") and doc.get("created_at"):
                        try:
                            es.index(
                                index=INDEX_NAME,
                                id=doc["uri"],
                                document=doc
                            )
                            saved       += 1
                            month_saved += 1
                        except Exception as e:
                            print(f"[{subreddit}] ES write error: {e}")
                            errors += 1

                last_id = post.get("id")

            if len(posts) < BATCH_SIZE:
                break

            time.sleep(REQUEST_DELAY)

        if month_saved > 0:
            print(f"[{subreddit}] {month_label}: {month_saved} saved")

        current = next_month
        time.sleep(0.5)

    print(f"[{subreddit}] Finished: {saved} saved, {errors} errors")
    return saved

def main():
    """
    Main entry point. Run locally with:
        python3 reddit_history_import.py
    Requires ES port-forward to be active:
        kubectl port-forward service/elasticsearch-es-http -n elastic 9200:9200
    """
    start_dt = datetime.fromtimestamp(START_TS, tz=timezone.utc).strftime("%Y-%m-%d")
    end_dt   = datetime.fromtimestamp(END_TS,   tz=timezone.utc).strftime("%Y-%m-%d")

    print("=" * 60)
    print("Reddit Historical Data Import via Arctic Shift API")
    print(f"Date range: {start_dt} to {end_dt}")
    print(f"Subreddits: {SUBREDDITS}")
    print("=" * 60)

    es = get_es()

    # Verify ES connection before starting
    try:
        count = es.count(index=INDEX_NAME)["count"]
        print(f"ES connected. Current social-posts count: {count}\n")
    except Exception as e:
        print(f"ES connection error: {e}")
        print("Make sure port-forward is running:")
        print("  kubectl port-forward service/elasticsearch-es-http -n elastic 9200:9200")
        return

    total_saved = 0

    for subreddit in SUBREDDITS:
        saved = import_subreddit_history(
            es=es,
            subreddit=subreddit,
            start_ts=START_TS,
            end_ts=END_TS
        )
        total_saved += saved
        # Brief pause between subreddits
        time.sleep(2)

    # Final summary
    print("\n" + "=" * 60)
    print(f"Import complete! Total new posts saved: {total_saved}")
    final_count = es.count(index=INDEX_NAME)["count"]
    print(f"Final social-posts count: {final_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()