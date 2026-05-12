# COMP90024 Team 36
# Reddit bootstrap function - one-time historical data collection
# This is invoked manually (not by timer) to backfill historical posts.
# Reddit public API only allows access to ~1000 most recent posts per subreddit,
# so this is the maximum historical depth we can achieve via this approach.

import os
from elasticsearch8 import Elasticsearch
from reddit_crawler import collect_reddit_history

INDEX_NAME = "social-posts"


def read_secret(key, default=None):
    """
    Read a secret value from Fission-mounted secret files.
    Falls back to environment variables if the secret file is not found.
    """
    path = f"/secrets/default/es-secret/{key}"
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return os.getenv(key, default)


def get_es():
    """
    Create and return an ElasticSearch client using credentials from secrets.
    """
    return Elasticsearch(
        read_secret("ES_HOST"),
        basic_auth=(read_secret("ES_USER", "elastic"), read_secret("ES_PASSWORD")),
        verify_certs=False,
        request_timeout=30
    )


def main():
    """
    One-time bootstrap collection.
    Walks back through each subreddit up to 10 pages (~1000 posts each).
    Total expected: 6 subreddits * 1000 posts = up to 6000 raw posts,
    but only those matching our query keywords will be saved.

    Should be invoked manually via:
        fission fn test --name reddit-bootstrap --timeout=600s
    """
    es = get_es()

    # Collect historical posts (up to 10 pages per subreddit = ~1000 posts each)
    docs = collect_reddit_history(max_pages=10)

    saved, skipped, errors = 0, 0, 0

    for doc in docs:
        if not doc.get("uri") or not doc.get("created_at"):
            skipped += 1
            continue
        try:
            # Use URI as ElasticSearch document ID for automatic deduplication
            # If a post already exists from realtime harvesting, it gets updated
            es.index(
                index=INDEX_NAME,
                id=doc["uri"],
                document=doc
            )
            saved += 1
        except Exception as e:
            print(f"[reddit_bootstrap] ES write error for {doc.get('uri')}: {e}")
            errors += 1

    result = {
        "status": "ok",
        "platform": "reddit",
        "mode": "bootstrap",
        "collected": len(docs),
        "saved": saved,
        "skipped": skipped,
        "errors": errors
    }
    print(result)
    return result