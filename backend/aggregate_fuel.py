"""
FuelWatch Raw Data Aggregation Pipeline
================================================================
Author: Hanyue Li
Course: COMP90024 Cluster and Cloud Computing
Date: May 2026

Description:
    This serverless function serves as a scheduled data processing job.
    It is triggered daily at 03:00 UTC by a Fission Timer, and performs
    an incremental aggregation of the previous day's raw fuel price data
    from the 'fuelwatch-raw' index into the pre-aggregated summary index
    'fuel-daily-summary'.

    By processing only the previous day's records rather than the full
    historical dataset, the function avoids duplicate writes and minimises
    compute overhead on the Elasticsearch cluster.

Architecture:
    Trigger:     Fission Timer (cron: "0 3 * * *")
    Source:      fuelwatch-raw       (raw ingestion index, 4.3M+ records)
    Destination: fuel-daily-summary  (pre-aggregated summary index)
    Credentials: Mounted via Kubernetes Secret (es-secret)
    Network:     Internal cluster DNS (no port-forwarding required)
"""

from elasticsearch import Elasticsearch, helpers
import urllib3
import os
import sys
from datetime import datetime, timedelta

# Suppress insecure HTTPS warnings for internal cluster traffic
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ES_HOST     = "https://elasticsearch-es-http.elastic.svc.cluster.local:9200"
ES_USER     = "elastic"
RAW_INDEX     = "fuelwatch-raw"
SUMMARY_INDEX = "fuel-daily-summary"


def get_es_client() -> Elasticsearch:
    
    secret_path = "/secrets/es-secret/password"

    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            es_pass = f.read().strip()
    else:
        # Fallback for local development and manual testing
        es_pass = os.environ.get("ES_PASSWORD", "elastic")

    try:
        es = Elasticsearch(
            [ES_HOST],
            basic_auth=(ES_USER, es_pass),
            verify_certs=False,
            ssl_show_warn=False,
            request_timeout=120  # Extended timeout for aggregation on large datasets
        )
        if not es.ping():
            raise ConnectionError("Elasticsearch cluster did not respond to ping.")
        return es

    except Exception as e:
        print(f"[-] Connection failed: {e}")
        sys.exit(1)


def get_date_range() -> tuple[str, str]:
    """
    Calculate the date range for yesterday's data window.
    """
    today     = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    return yesterday, today


def run_aggregation(es: Elasticsearch) -> None:
    """
    Execute the incremental daily aggregation pipeline.
    """
    date_from, date_to = get_date_range()
    print(f"[*] Aggregation window: {date_from} to {date_to} (exclusive)")

    # Step 1 & 2: Filtered aggregation query
    query = {
        "size": 0,
        "query": {
            "range": {
                "publish_date": {
                    "gte": date_from,
                    "lt":  date_to
                }
            }
        },
        "aggs": {
            "daily_avg": {
                "date_histogram": {
                    "field": "publish_date",
                    "calendar_interval": "1d"
                },
                "aggs": {
                    "price": {
                        "avg": {
                            "field": "product_price"
                        }
                    }
                }
            }
        }
    }

    try:
        print(f"[*] Executing aggregation on index: {RAW_INDEX} ...")
        response = es.search(index=RAW_INDEX, body=query)
        buckets  = (response
                    .get("aggregations", {})
                    .get("daily_avg", {})
                    .get("buckets", []))

        if not buckets:
            print("[!] No records found for the target date window. Exiting.")
            return

        # Step 3: Transform buckets into bulk indexing actions
        actions = []
        for bucket in buckets:
            if bucket["doc_count"] > 0 and bucket["price"]["value"] is not None:
                actions.append({
                    "_index": SUMMARY_INDEX,
                    "_source": {
                        "date":      bucket["key_as_string"],
                        "avg_price": round(bucket["price"]["value"], 2)
                    }
                })

        # Step 4: Bulk write to summary index
        if actions:
            print(f"[*] Writing {len(actions)} summarised record(s) "
                  f"to index: {SUMMARY_INDEX} ...")
            success, _ = helpers.bulk(es, actions, stats_only=True)
            print(f"[+] Aggregation complete. Records indexed: {success}")
        else:
            print("[!] No valid price data found for the target window.")

    except Exception as e:
        print(f"[-] Aggregation pipeline failed: {e}")
        raise


def main(context=None):
    """
    Fission serverless function entry point.
    This function is invoked by a Fission Timer trigger on a daily cron schedule (0 3 * * * — 03:00 UTC). 
    """
    print("[*] Fuel aggregation job started.")
    try:
        es = get_es_client()
        run_aggregation(es)
        print("[+] Job finished successfully.")
        return "Aggregation completed successfully.", 200

    except Exception as e:
        print(f"[-] Job failed: {e}")
        return f"Aggregation failed: {e}", 500


# ---------------------------------------------------------------------------
# Local development entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    """
    Local execution mode for development and manual testing.
    """
    main()