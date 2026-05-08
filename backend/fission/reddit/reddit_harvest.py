# COMP90024 Team 36
# Reddit harvest Fission function - Timer triggered (event-driven)
# This function is invoked automatically by a Fission Timer Trigger every 5 minutes

import os
from elasticsearch8 import Elasticsearch
from reddit_crawler import collect_reddit_realtime

# ElasticSearch index name shared across all platforms
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
    SSL verification is disabled for the internal cluster connection.
    """
    return Elasticsearch(
        read_secret("ES_HOST"),
        basic_auth=(read_secret("ES_USER", "elastic"), read_secret("ES_PASSWORD")),
        verify_certs=False,
        request_timeout=10
    )


def main():
    """
    Main entry point called by Fission Timer Trigger.
    Workflow:
        1. Connect to ElasticSearch
        2. Collect latest Reddit posts via crawler
        3. Index each post into ElasticSearch using URI as document ID
           (ElasticSearch upsert behaviour prevents duplicate documents)
        4. Return a summary result
    """
    es = get_es()

    # Collect the latest page of matching Reddit posts
    docs = collect_reddit_realtime()

    saved, skipped, errors = 0, 0, 0

    for doc in docs:
        # Skip documents missing required fields
        if not doc.get("uri") or not doc.get("created_at"):
            skipped += 1
            continue

        try:
            # Use URI as ElasticSearch document ID for automatic deduplication
            es.index(
                index=INDEX_NAME,
                id=doc["uri"],
                document=doc
            )
            saved += 1
        except Exception as e:
            print(f"[reddit_harvest] ES write error for {doc.get('uri')}: {e}")
            errors += 1

    # Log and return summary for Fission function logs
    result = {
        "status": "ok",
        "platform": "reddit",
        "collected": len(docs),
        "saved": saved,
        "skipped": skipped,
        "errors": errors
    }
    print(result)
    return result