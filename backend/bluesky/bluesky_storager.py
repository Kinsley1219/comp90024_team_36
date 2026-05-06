
from bluesky_processor import read_secret

### Elasticsearch Connection & Index Setup ###
def get_es():
    try:
        from elasticsearch import Elasticsearch
        host = read_secret("ES_HOST")
        user = read_secret("ES_USER", "elastic")
        pwd = read_secret("ES_PASSWORD")
        if not host:
            raise ValueError("Missing ES_HOST")
        if not pwd:
            raise ValueError("Missing ES_PASSWORD")
        es = Elasticsearch(host, basic_auth=(user, pwd), request_timeout=10, verify_certs=False)
        print("ES_HOST:", host)
        print("ES ping:", es.ping())
        return es
    except Exception as e:
        print("ES connection error:", repr(e))
        return None

def init_index(es, index_name, mapping):
    try:
        if not es.indices.exists(index=index_name):
            es.indices.create(index=index_name, body=mapping)
    except Exception as e:
        print("Init index warning:", e)

def init_all_indexes(es):
    init_index(es, "bluesky-cursors", {
        "mappings": {
            "properties": {
                "last_seen_time": {"type": "date"},
                "next_start": {"type": "integer"},
                "until": {"type": "date"},
                "finished": {"type": "boolean"}
            }
        }
    })
    init_index(es, read_secret("INDEX_NAME", "bluesky-posts"), {
        "mappings": {
            "properties": {
                "uri": {"type": "keyword"},
                "text": {"type": "text"},
                "author": {"type": "keyword"},
                "query": {"type": "keyword"},
                "created_at": {"type": "date"},
                "date": {"type": "date"},
                "platform": {"type": "keyword"},
                "ingested_at": {"type": "date"},
                "like": {"type": "integer"},
                "reply": {"type": "integer"},
                "repost": {"type": "integer"},
                "is_fuel": {"type": "boolean"},
                "is_cost": {"type": "boolean"},
                "is_au": {"type": "boolean"}
            }
        }
    })

def save_posts(es, posts):
    ## Save processed posts to Elasticsearch ##
    saved = 0
    index_name = read_secret("INDEX_NAME", "bluesky-posts")

    for doc in posts:
        try:
            if not doc.get("uri"):
                continue
            es.index(index=index_name, id=doc["uri"], document=doc)
            saved += 1
        except Exception as e:
            print("ES index error:", repr(e))

    return saved

