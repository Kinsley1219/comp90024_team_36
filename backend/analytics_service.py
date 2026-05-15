"""
Cloud-Native Fuel and Sentiment Analytics API
=============================================
Author: Hanyue Li
Course: COMP90024 Cluster and Cloud Computing
Date: May 2026

Description:
This Serverless function serves as the primary backend API for the project's
frontend dashboard. It implements a high-performance data retrieval strategy
by querying a pre-aggregated summary index ('fuel-daily-summary') for historical
fuel prices and performing real-time aggregations on social media posts.

Key Features:
1.  Scalable Architecture: Decouples heavy data processing from API response time.
2.  Secure Credential Management: Utilizes Kubernetes Secrets mounted via Fission.
3.  Data Normalization: Merges heterogeneous data sources into a unified JSON schema.
"""

from elasticsearch import Elasticsearch
import urllib3
import json
import os

# Suppress insecure request warnings for internal cluster traffic
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def main():
    """
    Main entry point for the Fission function.
    Returns: A JSON object containing merged fuel and sentiment trends.
    """
    
    # --- 1. Infrastructure Configuration ---
    # Internal cluster address for Elasticsearch
    es_host = "https://elasticsearch-es-http.elastic.svc.cluster.local:9200"
    es_user = "elastic"
    
    # --- 2. Secure Credential Retrieval ---
    # Deployment Command Requirement: --secret es-secret
    secret_path = "/secrets/es-secret/password"
    
    try:
        if os.path.exists(secret_path):
            with open(secret_path, "r") as f:
                es_pass = f.read().strip()
        else:
            # Fallback for local testing environments
            es_pass = os.environ.get("ES_PASSWORD", "elastic")
    except Exception as e:
        return {"status": "error", "message": f"Credential access failed: {str(e)}"}

    # --- 3. Client Initialization ---
    es = Elasticsearch(
        [es_host],
        basic_auth=(es_user, es_pass),
        verify_certs=False,
        ssl_show_warn=False,
        request_timeout=60
    )

    try:
        # --- 4. Retrieve Aggregated Fuel Data ---
        # Fetching from the pre-computed summary index (O(1) search)
        fuel_query = {
            "size": 2000, 
            "query": {"match_all": {}},
            "sort": [{"date": {"order": "asc"}}]
        }
        f_res = es.search(index="fuel-daily-summary", body=fuel_query)

        # --- 5. Aggregate Social Sentiment Data ---
        # Real-time aggregation of sentiment scores grouped by day and platform
        social_aggs = {
            "daily_social": {
                "date_histogram": 
                {"field": "created_at", 
                 "calendar_interval": "1d",
                 "time_zone": "Australia/Melbourne"},
                "aggs": {
                    "avg_sent": {"avg": {"field": "sentiment_score"}},
                    "platforms": {
                        "terms": {"field": "platform.keyword", "missing": "N/A"},
                        "aggs": {"p_avg_sent": {"avg": {"field": "sentiment_score"}}}
                    }
                }
            }
        }
        s_res = es.search(index="social-posts-v1", body={"aggs": social_aggs, "size": 0})

        # --- 6. Data Harmonization & Merging ---
        merged_map = {}

        # 6a. Process Fuel Data (Primary Source)
        for hit in f_res["hits"]["hits"]:
            date_str = hit["_source"]["date"].split("T")[0]
            price = hit["_source"]["avg_price"]
            
            merged_map[date_str] = {
                "date": date_str,
                "national_avg_price": round(price, 2),
                "overall_avg_sentiment": 0,
                "total_posts": 0,
                "platforms": {}
            }

        # 6b. Merge Social Sentiment Data
        for bucket in s_res["aggregations"]["daily_social"]["buckets"]:
            date_str = bucket["key_as_string"].split("T")[0]
            count = bucket["doc_count"]
            if count == 0: continue
            
            # Initialize record if date exists in social data but not in fuel data
            if date_str not in merged_map:
                merged_map[date_str] = {
                    "date": date_str, 
                    "national_avg_price": 0, # Default to 0 for frontend compatibility
                    "platforms": {},
                    "total_posts": 0,
                    "overall_avg_sentiment": 0
                }
            
            merged_map[date_str]["total_posts"] = count
            merged_map[date_str]["overall_avg_sentiment"] = round(bucket["avg_sent"]["value"] or 0, 4)
            
            # Map platform-specific sentiment
            p_data = {}
            for p_bucket in bucket["platforms"]["buckets"]:
                p_data[p_bucket["key"]] = {
                    "avg_sentiment": round(p_bucket["p_avg_sent"]["value"] or 0, 4),
                    "post_count": p_bucket["doc_count"]
                }
            merged_map[date_str]["platforms"] = p_data

        # Sort the final dataset chronologically for time-series visualization
        final_data = [merged_map[k] for k in sorted(merged_map.keys())]
        
        return {
            "status": "success",
            "data": final_data
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Database query failed: {str(e)}"
        }