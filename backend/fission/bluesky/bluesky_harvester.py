
import time
from datetime import datetime, timezone, timedelta

from bluesky_processor import (
    EARLIEST_DATE, QUERIES, get_requests, read_secret, query_id, make_doc
)
from bluesky_storager import get_es, init_all_indexes, save_posts

### Cursor management ###
# Use ES to store crawling progress (realtime + history + query rotation)
CURSOR_INDEX = "bluesky-cursors"  # store all crawling state in ES

def get_cursor(es, cursor_id, default=None):  # read cursor state from ES
    try:
        result = es.get(index=CURSOR_INDEX, id=cursor_id)
        return result["_source"]
    except Exception:
        return default or {}

def save_cursor(es, cursor_id, data): # write/update cursor state in ES
    try:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        es.index(index=CURSOR_INDEX, id=cursor_id, document=data)
    except Exception as e:
        print(f"Cursor update error ({cursor_id}):", e)

def get_last_seen_time(es):  # get last realtime crawl timestamp
    default_since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cursor = get_cursor(es, "realtime-last-seen")
    return cursor.get("last_seen_time", default_since)

def update_last_seen_time(es, last_seen_time): # update realtime timestamp
    save_cursor(es, "realtime-last-seen", {"last_seen_time": last_seen_time})

def get_history_until(es, query): # get history crawl boundary for query
    cursor_id = f"history-until-{query_id(query)}"
    cursor = get_cursor(es, cursor_id)
    return cursor.get("until", datetime.now(timezone.utc).isoformat())

def update_history_until(es, query, until): # update history boundary
    cursor_id = f"history-until-{query_id(query)}"
    save_cursor(es, cursor_id, {"query": query, "until": until})

def is_query_history_finished(es, query): # check if history crawl finished
    cursor_id = f"history-finished-{query_id(query)}"
    cursor = get_cursor(es, cursor_id)
    return cursor.get("finished", False)

def mark_query_history_finished(es, query): # mark query history as done
    cursor_id = f"history-finished-{query_id(query)}"
    save_cursor(es, cursor_id, {"query": query, "finished": True})

def get_query_batch(es, batch_size=8): # select a subset of queries each run
    cursor = get_cursor(es, "query-batch-cursor")
    start = int(cursor.get("next_start", 0)) # starting index from last run

    if start >= len(QUERIES): # reset if out of range
        start = 0
    batch = QUERIES[start:start + batch_size] # current batch

    if not batch: # safety fallback
        batch = QUERIES[:batch_size]
        start = 0
    next_start = start + batch_size # next batch position

    if next_start >= len(QUERIES): # loop back to beginning
        next_start = 0
    return batch, next_start

def update_query_cursor(es, next_start): # save next batch position for next run
    save_cursor(es, "query-batch-cursor", {"next_start": next_start})

def all_history_finished(es): # check if all queries have finished history crawling
    return all(is_query_history_finished(es, q) for q in QUERIES)

### Connect Bluesky ###
def login(): # create session and get access token
    try:
        r = get_requests()
        user = read_secret("BSKY_USER")
        pwd = read_secret("BSKY_PASS")
        if not user or not pwd:
            raise ValueError("Missing BSKY_USER / BSKY_PASS")

        resp = r.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": user, "password": pwd},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if "accessJwt" not in data:
            raise ValueError(f"Login failed: {data}")
        return data
    except Exception as e:
        print("Login error:", repr(e))
        return {"error": str(e)}

### Crawling logic ###
def collect_history_posts(es, sess, query_batch): # crawl older posts using "until"
    print("=== Automatically crawl historical data ===")
    posts = []

    if "accessJwt" not in sess:
        print("No session for history")
        return []

    headers = {"Authorization": f"Bearer {sess['accessJwt']}"}
    r = get_requests()

    for q in query_batch:
        if is_query_history_finished(es, q):  # skip if this query already fully crawled
            print(f"Skip finished query: {q}")
            continue

        history_until = get_history_until(es, q) # where we stopped last time
        oldest_time = history_until
        cursor = None
        query_posts = 0
        reached_earliest = False
        print(f"History query: {q}, until={history_until}")

        for _ in range(10): # limit pages per run (avoid long execution)
            try:
                params = {"q": q, "limit": 50, "until": history_until, "sort": "latest"}
                if cursor:
                    params["cursor"] = cursor # Turn the page

                res = r.get(
                    "https://bsky.social/xrpc/app.bsky.feed.searchPosts",
                    headers=headers,
                    params=params,
                    timeout=8
                )
                data = res.json()
                page = data.get("posts", [])
                print(f"[HISTORY] {q}: page_size={len(page)}")

                if not page:
                    break # No more data

                for p in page:
                    doc = make_doc(p, q)
                    ca = doc.get("created_at")

                    if not ca:
                        continue

                    #if parse_time(ca) < parse_time(EARLIEST_DATE):
                    if ca < EARLIEST_DATE:
                        print(f"Reached earliest limit for {q}: {EARLIEST_DATE}")
                        reached_earliest = True
                        break

                    posts.append(doc)
                    query_posts += 1

                    # if parse_time(ca) < parse_time(oldest_time):
                    if ca < oldest_time:
                        oldest_time = ca

                if reached_earliest: # Stop if reached earliest date limit
                    break

                cursor = data.get("cursor")
                if not cursor: # No next page
                    break
                time.sleep(0.2)

            except Exception as e:
                print(f"history err {q}:", repr(e))
                break

        # update cursor state after this query
        if reached_earliest:
            mark_query_history_finished(es, q)
            print(f"Finished history for query by earliest limit: {q}")
        elif query_posts == 0 or oldest_time == history_until:
            mark_query_history_finished(es, q)
            print(f"Finished history for query: {q}")
        else:
            update_history_until(es, q, oldest_time)
            print(f"Updated history cursor for {q}: {oldest_time}")
        time.sleep(0.2)
    return posts

def collect_realtime_posts(es, sess, query_batch): # Get new posts since last_seen_time
    print("=== Real-time incremental crawling ===")
    last_seen = get_last_seen_time(es)
    newest_time = last_seen
    posts = []

    if "accessJwt" not in sess:
        print("No session for realtime")
        return []

    headers = {"Authorization": f"Bearer {sess['accessJwt']}"}
    r = get_requests()

    for q in query_batch:
        try:
            res = r.get(
                "https://bsky.social/xrpc/app.bsky.feed.searchPosts",
                headers=headers,
                params={"q": q, "limit": 50, "since": last_seen, "sort": "latest"},
                timeout=8
            )
            data = res.json()
            for p in data.get("posts", []):
                doc = make_doc(p, q)
                ca = doc.get("created_at")
                # if ca and parse_time(ca) > parse_time(last_seen):
                if ca and ca > last_seen:
                    posts.append(doc)
                    # if parse_time(ca) > parse_time(newest_time):
                    if ca > newest_time:
                        newest_time = ca
            time.sleep(0.2)
        except Exception as e:
            print(f"realtime err {q}:", repr(e))

    if posts:
        update_last_seen_time(es, newest_time)
        print(f"[REALTIME] updated last_seen → {newest_time}")
    return posts

### Fission entrypoint ###
# Main pipeline: collect, process and store Bluesky posts
def run():
    try:
        ## Connect to Bluesky API and Elasticsearch ##
        sess = login()
        if "error" in sess:
            print("Login error:", sess["error"])
            return {"total": 0, "saved": 0}

        es = get_es()
        if not es:
            return {"total": 0, "saved": 0}
        init_all_indexes(es)

        # Select this round's query batch
        query_batch, next_start = get_query_batch(es)
        print("Query batch:", query_batch)

        ## Collect and process data ##
        posts = []

        if not all_history_finished(es):
            history_posts = collect_history_posts(es, sess, query_batch)
            print("History posts:", len(history_posts))
            posts.extend(history_posts)

        realtime_posts = collect_realtime_posts(es, sess, query_batch)
        print("Realtime posts:", len(realtime_posts))
        posts.extend(realtime_posts)

        saved = save_posts(es, posts)

        ## Update query batch cursor ##
        update_query_cursor(es, next_start)
        return len(posts), saved
    except Exception as e:
        print("Run error:", repr(e))
        return 0, 0

### # Fission entrypoint ###
def main():
    try:
        total, saved = run()
        return {"status": "ok", "total": total, "saved": saved}
    except Exception as e:
        return {"status": "error", "msg": str(e)}
