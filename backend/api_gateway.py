# 20260511

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from elasticsearch import Elasticsearch
import uvicorn

# 1. Initialize FastAPI with a professional title
app = FastAPI(
    title="COMP90024 Social Posts & Fuel Prices API",
    description="API for analyzing Fuel Prices vs. Social Sentiment",
    version="2.0.0"
)

# 2. Enable CORS for Frontend/UI access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Initialize Elasticsearch Client
es = Elasticsearch(
    "https://127.0.0.1:9200",
    basic_auth=("elastic", "elastic"),
    verify_certs=False
)

@app.get("/api/v1/trends", tags=["Analytics"])
def get_fuel_sentiment_trends():
    """
    Fetches ALL historical data using Server-Side Aggregations.
    This method scales to millions of rows efficiently.
    """
    try:
        # Define Aggregation for Fuel Prices (Processing 4.3M+ rows)
        fuel_aggs = {
            "daily_fuel": {
                "date_histogram": {"field": "publish_date", "calendar_interval": "1d"},
                "aggs": {"avg_price": {"avg": {"field": "product_price"}}}
            }
        }
        
        # Define Aggregation for Social Sentiment
        social_aggs = {
            "daily_social": {
                "date_histogram": {"field": "created_at", "calendar_interval": "1d"},
                "aggs": {
                    "avg_sent": {"avg": {"field": "sentiment_score"}},
                    "platforms": {
                        # 直接改用 platform，去掉 .keyword
                        "terms": {"field": "platform", "missing": "N/A"},
                        "aggs": {"p_avg_sent": {"avg": {"field": "sentiment_score"}}}
                    }
                }
            }
        }

        # Execute Search with size=0 (We only need the aggregated results, not raw docs)
        f_res = es.search(index="fuelwatch-raw", aggs=fuel_aggs, size=0)
        s_res = es.search(index="social-posts", aggs=social_aggs, size=0)

        merged_map = {}

        # Parse Fuel Aggregations
        for bucket in f_res["aggregations"]["daily_fuel"]["buckets"]:
            date_str = bucket["key_as_string"].split("T")[0]
            price = bucket["avg_price"]["value"]
            if price:
                merged_map[date_str] = {
                    "date": date_str,
                    "national_avg_price": round(price, 2),
                    "overall_avg_sentiment": 0,
                    "total_posts": 0,
                    "platforms": {}
                }

        # Parse Social Aggregations and Merge
        for bucket in s_res["aggregations"]["daily_social"]["buckets"]:
            date_str = bucket["key_as_string"].split("T")[0]
            count = bucket["doc_count"]
            if count == 0: continue
            
            if date_str not in merged_map:
                merged_map[date_str] = {
                    "date": date_str, 
                    "national_avg_price": None, 
                    "platforms": {},
                    "total_posts": 0,
                    "overall_avg_sentiment": 0
                }
            
            merged_map[date_str]["total_posts"] = count
            merged_map[date_str]["overall_avg_sentiment"] = round(bucket["avg_sent"]["value"] or 0, 4)
            
            # Map platform breakdowns
            p_data = {}
            for p_bucket in bucket["platforms"]["buckets"]:
                p_data[p_bucket["key"]] = {
                    "avg_sentiment": round(p_bucket["p_avg_sent"]["value"] or 0, 4),
                    "post_count": p_bucket["doc_count"]
                }
            merged_map[date_str]["platforms"] = p_data

        # Return sorted list by date
        return [merged_map[k] for k in sorted(merged_map.keys())]

    except Exception as e:
        return {"error": "Aggregation Failed", "details": str(e)}

if __name__ == "__main__":
    uvicorn.run("api_gateway:app", host="0.0.0.0", port=8000, reload=True)