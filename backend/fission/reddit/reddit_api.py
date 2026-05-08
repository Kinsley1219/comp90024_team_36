# COMP90024 Team 36
# Reddit query API - HTTP triggered Fission function
# Exposes RESTful endpoints for Jupyter Notebook to query Reddit data from ElasticSearch

import os
from flask import request, jsonify
from elasticsearch8 import Elasticsearch

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
    Main entry point called by Fission HTTP Trigger.
    Routes incoming requests based on the X-Fission-Url header (set by Fission router).
    """
    es = get_es()

    # Fission passes the original URL via this header
    full_url = request.headers.get("X-Fission-Full-Url", "") or request.path

    # Route to the appropriate handler based on URL
    if "stats" in full_url:
        return _get_stats(es)
    elif "sentiment" in full_url:
        return _get_sentiment_trend(es)
    else:
        return _search_posts(es)


def _search_posts(es):
    """
    Search Reddit posts by keyword and date range.
    Query parameters:
        keyword  - text to search in post content (optional)
        from     - start date filter, e.g. 2025-01-01 (default: now-7d)
        size     - number of results to return (default: 20)
    Returns posts sorted by most recent first.
    """
    keyword   = request.args.get("keyword", "")
    from_date = request.args.get("from", "now-7d")
    size      = int(request.args.get("size", 20))

    # Base query filters for Reddit platform and date range
    query = {
        "bool": {
            "must": [
                {"term":  {"platform": "reddit"}},
                {"range": {"created_at": {"gte": from_date}}}
            ]
        }
    }

    # Add keyword filter only if provided
    if keyword:
        query["bool"]["must"].append({"match": {"text": keyword}})

    res  = es.search(
        index=INDEX_NAME,
        query=query,
        sort=[{"created_at": "desc"}],
        size=size
    )
    hits = [h["_source"] for h in res["hits"]["hits"]]
    return jsonify({"total": res["hits"]["total"]["value"], "posts": hits})


def _get_stats(es):
    """
    Aggregate Reddit post counts by date and subreddit.
    Used by Jupyter Notebook to plot posting trends over time.
    Returns date histogram and subreddit breakdown aggregations.
    """
    res = es.search(
        index=INDEX_NAME,
        query={"term": {"platform": "reddit"}},
        aggs={
            # Group posts by calendar day
            "by_date": {
                "date_histogram": {
                    "field": "created_at",
                    "calendar_interval": "day"
                }
            },
            # Group posts by subreddit, top 10
            "by_subreddit": {
                "terms": {"field": "subreddit", "size": 10}
            }
        },
        size=0  # We only need aggregations, not individual documents
    )
    return jsonify(res["aggregations"])


def _get_sentiment_trend(es):
    """
    Compare post counts across content categories.
    Used by Jupyter Notebook to visualise fuel vs cost-of-living discussion trends.
    Returns counts for fuel-related, cost-related, and Australia-related posts.
    """
    def count_flag(field):
        """Count Reddit posts where the given boolean flag field is True."""
        return es.count(
            index=INDEX_NAME,
            query={
                "bool": {"must": [
                    {"term": {"platform": "reddit"}},
                    {"term": {field: True}}
                ]}
            }
        )["count"]

    return jsonify({
        "fuel_posts": count_flag("is_fuel"),  # Posts about fuel/petrol
        "cost_posts": count_flag("is_cost"),  # Posts about cost of living
        "au_posts":   count_flag("is_au")     # Posts mentioning Australia
    })