# Reddit Harvester - Fission Functions

**COMP90024 Team 36 - Cluster and Cloud Computing Assignment 2**

## Overview

This module harvests Reddit posts related to fuel prices and cost-of-living discussions in Australia, and stores them in ElasticSearch for sentiment analysis by other team members.


## Architecture

This Reddit harvester uses an event-driven architecture powered by Fission:

```
┌─────────────────────────┐
│ Fission Timer Trigger   │  fires every 5 minutes
│   (reddit-timer)        │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐         ┌─────────────────────────┐
│ reddit-harvest function │ ──────► │  ElasticSearch          │
│ (Python 3.9)            │         │  (social-posts index)   │
└─────────────────────────┘         └────────────┬────────────┘
                                                 ▲
┌─────────────────────────┐                      │
│ reddit-bootstrap fn     │ ─────────────────────┘
│ (one-time history fill) │
└─────────────────────────┘
                                                 │
                                                 ▼
                                    ┌────────────────────────┐
                                    │ reddit-api function    │
                                    │ (3 REST endpoints      │
                                    │  for Jupyter Notebook) │
                                    └────────────────────────┘
```

## File Structure

```
backend/fission/reddit/
├── reddit_crawler.py       Core crawler logic (fetches posts from Reddit)
├── reddit_harvest.py       Timer-triggered function (real-time, 5-min interval)
├── reddit_bootstrap.py     Manual function (one-time history backfill)
├── reddit_api.py           HTTP-triggered API (REST endpoints for queries)
├── __init__.py             Python package marker (required by Fission)
├── requirements.txt        Python dependencies (elasticsearch8, requests, flask)
├── build.sh                Fission package build script
├── deploy.sh               One-click deployment script
└── README.md               This file

backend/fission/specs/      Fission YAML specifications (infrastructure as code)
├── env-python-39.yaml
├── package-reddit-pkg.yaml
├── function-reddit-harvest.yaml
├── function-reddit-api.yaml
├── timetrigger-reddit-timer.yaml
└── route-reddit-{posts,stats,sentiment}.yaml

database/
└── reddit-social-posts-mapping.json   ElasticSearch index field mappings
```

## Subreddits Harvested

```
r/australia    - General Australian discussion
r/sydney       - NSW capital
r/melbourne    - VIC capital
r/perth        - WA capital (high fuel discussion volume due to FuelWatch)
r/brisbane     - QLD capital
r/AusFinance   - Australian personal finance (most cost-of-living content)
```

## Data Collection Method

Reddit's official OAuth API requires application registration which has become increasingly difficult to obtain. Instead, this harvester uses Reddit's public JSON endpoints, which require only a User-Agent header (no token, no OAuth) for reading public data, subject to a rate limit of 60 requests per minute.

This approach is fully compliant with Reddit's terms of service for public data access. With 6 target subreddits and a 5-minute timer interval, the harvester makes approximately 72 requests per hour, well within the rate limit.

### Limitations

- Reddit's `.json` endpoint returns at most ~1000 most recent posts per subreddit
- Cannot access posts older than this via the public API
- For older historical data (2020+), an offline import from Pushshift archives would be required (planned future work)

## Pre-requirements

- Kubernetes cluster running on NeCTAR Research Cloud
- ElasticSearch installed and running (`kubectl get pods -n elastic`)
- Fission installed and running (`kubectl get pods -n fission`)
- `es-secret` Kubernetes secret with ES_HOST, ES_USER, ES_PASSWORD
- Fission CLI installed locally
- Python 3.9 Fission environment created

## Deployment Steps

### Step 1: Verify cluster environment

```bash
kubectl get nodes
```
Expected: 1 control-plane node + 3 worker nodes, all STATUS = Ready

```bash
kubectl get pods -n elastic
```
Expected: elastic-operator, elasticsearch nodes, kibana - all Running

```bash
kubectl get pods -n fission
```
Expected: All Fission components Running (buildermgr, executor, router,
timer, storagesvc, kubewatcher, mqtrigger, webhook)
Note: timer component is required for event-driven harvesting

```bash
fission version
```
Expected: client and server both v1.22.0

### Step 2: Connect to ElasticSearch and create index

In Terminal 1 (keep running throughout the session):
```bash
kubectl port-forward service/elasticsearch-es-http -n elastic 9200:9200
```

In Terminal 2, navigate to project root and create the index:
```bash
# Adjust path to your local setup
cd /path/to/comp90024_team_36

# Verify ES is reachable
curl -k 'https://127.0.0.1:9200' --user 'elastic:elastic'

# Create the social-posts index with field mappings
curl -XPUT -k 'https://127.0.0.1:9200/social-posts' \
  --user 'elastic:elastic' \
  --header 'Content-Type: application/json' \
  --data @database/reddit-social-posts-mapping.json
```
Expected response: `{"acknowledged":true,"shards_acknowledged":true,"index":"social-posts"}`

Field type decisions:
- keyword: exact match fields (author, platform, subreddit)
- text: full-text search fields (post content)
- date: time-based filtering and histogram aggregations
- boolean: category flags for fuel/cost-of-living filtering

### Step 3: Create Fission Python 3.9 environment

We create a dedicated python-39 environment.

```bash
# Check existing environments first
fission env list

# Create python-39 environment
fission env create --name python-39 \
  --builder fission/python-builder-3.9 \
  --image fission/python-env-3.9
```

### Step 4: Build and deploy the Fission package

```bash
# Step 4a: Ensure build.sh is executable
chmod +x backend/fission/reddit/build.sh

# Step 4b: Create zip from inside the function directory
cd backend/fission/reddit
zip -r reddit.zip .
mv reddit.zip ../
cd /path/to/comp90024_team_36

# Step 4c: Create the Fission package
fission package create \
  --name reddit-pkg \
  --sourcearchive backend/fission/reddit.zip \
  --env python-39 \
  --buildcmd "./build.sh"

# Step 4d: verify
fission package info --name reddit-pkg
```
Expected status: succeeded
Dependencies installed: elasticsearch8==8.14.0, requests, flask

To update the package after code changes:
```bash
# Repackage and update (use --force when other functions reference the pkg)
fission package update \
  --name reddit-pkg \
  --sourcearchive backend/fission/reddit.zip \
  --buildcmd "./build.sh" \
  --force
```

### Step 5: Create Fission functions and triggers

```bash
# Step 5a: Create reddit-harvest function (timer-triggered)
fission fn create \
  --name reddit-harvest \
  --env python-39 \
  --pkg reddit-pkg \
  --entrypoint "reddit_harvest.main" \
  --secret es-secret \
  --fntimeout 120

# Step 5b: Create timer trigger - fires every 5 minutes
fission timer create \
  --name reddit-timer \
  --function reddit-harvest \
  --cron "@every 5m"

# Step 5c: Create reddit-api function (HTTP-triggered)
fission fn create \
  --name reddit-api \
  --env python-39 \
  --pkg reddit-pkg \
  --entrypoint "reddit_api.main" \
  --secret es-secret

# Step 5d: Create three HTTP routes for the API
fission route create --name reddit-posts \
  --method GET --url /api/reddit/posts \
  --function reddit-api

fission route create --name reddit-stats \
  --method GET --url /api/reddit/stats \
  --function reddit-api

fission route create --name reddit-sentiment \
  --method GET --url /api/reddit/sentiment \
  --function reddit-api

# Step 5e: Create bootstrap function for one-time history backfill
fission fn create \
  --name reddit-bootstrap \
  --env python-39 \
  --pkg reddit-pkg \
  --entrypoint "reddit_bootstrap.main" \
  --secret es-secret \
  --fntimeout 600
```

### Step 6: Verify deployment

```bash
# List all created resources
fission fn list
fission timer list
fission route list

# Test harvest function manually (one immediate invocation)
fission fn test --name reddit-harvest --timeout=120s
```
Expected output: `{"collected":N,"errors":0,"saved":N,"status":"ok"}`

```bash
# Verify data is in ElasticSearch
curl -k 'https://127.0.0.1:9200/social-posts/_count' --user 'elastic:elastic'
```
Expected: `{"count":N,...}` with N > 0

### Step 7: Bootstrap historical data (one-time)

```bash
# Pulls up to ~1000 posts per subreddit (~80 days of history)
# This is the maximum depth allowed by Reddit's public JSON API
fission fn test --name reddit-bootstrap --timeout=600s
```
Expected output: `{"collected":~500,"saved":~500,"mode":"bootstrap","status":"ok"}`

### Step 8: Import historical data via Arctic Shift API (2022-2026)

Arctic Shift is a community-maintained Reddit archive covering 2005 to present.
This script fetches posts month by month via HTTP API (no download required).
Run locally before deploying the timer for maximum historical coverage.

Requirements:
```bash
pip3 install elasticsearch8 requests --break-system-packages
```

Make sure ES port-forward is active (Terminal 1):
```bash
kubectl port-forward service/elasticsearch-es-http -n elastic 9200:9200
```

Run the import script from the reddit function directory:
```bash
cd backend/fission/reddit
python3 reddit_history_import.py
```

Expected output:
[australia] 2022-01: N saved
[australia] 2022-02: N saved
...
Import complete! Total new posts saved: XXXX

Note:
- Script queries one month at a time to stay within API rate limits
- Uses URI as ES document ID so re-running is safe (no duplicates)
- Covers 2022-01-01 to 2026-02-17 (where bootstrap data begins)
- reddit_history_import.py is a local script, NOT a Fission function

## API Endpoints

In a separate terminal, port-forward the Fission router:
```bash
kubectl port-forward service/router -n fission 9090:80
```

| Method | URL | Description |
|--------|-----|-------------|
| GET | /api/reddit/posts?keyword=petrol&size=20 | Search posts by keyword |
| GET | /api/reddit/stats | Post counts by date and subreddit |
| GET | /api/reddit/sentiment | Fuel vs cost-of-living post counts |

Example:
```bash
curl 'http://127.0.0.1:9090/api/reddit/sentiment'
```
Returns: `{"au_posts":N,"cost_posts":N,"fuel_posts":N}`

## Visualisation in Kibana

In a separate terminal, port-forward Kibana:
```bash
kubectl port-forward service/kibana-kb-http -n elastic 5601:5601
```

Then in your browser visit `https://localhost:5601` 
(accept the self-signed certificate warning) and log in with `elastic` / `elastic`.

To create a data view:
1. Navigate to Discover (left sidebar menu)
2. Click the data view dropdown, select "Create a data view"
3. Name: `social-posts`, Index pattern: `social-posts`
4. Timestamp field: `created_at`
5. Click "Save data view to Kibana"

Useful KQL filters in Discover:
- `is_fuel : true` - only fuel-related posts
- `is_cost : true` - only cost-of-living posts
- `subreddit : "perth"` - only Perth subreddit
- `query : "petrol Australia"` - posts matching specific keyword

## Sentiment Analysis

This harvester integrates VADER (Valence Aware Dictionary and sEntiment Reasoner)
sentiment analysis into all Reddit posts at ingestion time.

### Why VADER?

VADER is specifically designed for social media short texts and requires no training data or model downloads. 

 Key advantages:
- Works well with informal language, slang, and punctuation emphasis
- No GPU or model training required
- Fast enough to run inline during data ingestion
- Compound score range: -1.0 (most negative) to +1.0 (most positive)

### Scoring Thresholds

Following standard VADER convention (aligned with teammate Bluesky implementation):

| Compound Score | Label |
|----------------|-------|
| >= 0.05 | positive |
| <= -0.05 | negative |
| between -0.05 and 0.05 | neutral |

### Fields Added to ElasticSearch

| Field | Type | Description |
|-------|------|-------------|
| `sentiment_score` | float | VADER compound score (-1.0 to 1.0) |
| `sentiment_label` | keyword | positive / negative / neutral |

### Limitations

- VADER struggles with sarcasm (e.g. "Great, another petrol price rise!") may be scored as positive due to the word "Great"
- Long posts may dilute sentiment signals from key sentences
- Australian slang may not be fully captured in VADER lexicon

## Location Detection

Each Reddit post is assigned a `matched_location` field indicating the most
likely Australian location associated with the post.

### Detection Logic

Location is inferred using a two-stage approach:

1. **Subreddit-based detection (primary signal)**
   - r/sydney → Sydney
   - r/melbourne → Melbourne
   - r/perth → Perth
   - r/brisbane → Brisbane
   - r/australia → Australia
   - r/AusFinance → Australia

2. **Text-based detection (secondary signal)**
   - Scans post title and body for city/state name mentions
   - Covers: Sydney, Melbourne, Perth, Brisbane, Adelaide, Canberra, Darwin, Hobart
   - State abbreviations included: NSW, VIC, WA, QLD, SA, ACT, NT, TAS

### Priority Rules
Specific subreddit location (e.g. Perth) → highest priority
Specific text mention (e.g. "Adelaide")  → second priority
Generic "Australia" mention              → fallback
Unknown                                  → no location signal found

### Field Added to ElasticSearch

| Field | Type | Description |
|-------|------|-------------|
| `matched_location` | keyword | Detected location or "Unknown" |

## Implementation Notes

- ElasticSearch document ID is set to the post URI to prevent duplicates.
  When the timer re-fetches the same posts, ES upserts rather than duplicates.
- Timer trigger fires every 5 minutes, fully event-driven, runs entirely in the cluster (independent of the developer's local terminal).
- Pods are created on-demand and recycled when idle (Fission's serverless design); the timer schedule is unaffected by pod lifecycle.
- The match_query function uses strict relevance rules (topic keyword required + Australian location confirmation) to minimise false positives such as "Victoria Cross medals" matching the query "cost of living Victoria".

## YAML Specifications

All Fission resources have corresponding YAML files under `specs/` for declarative deployment (infrastructure as code). To deploy from specs:

```bash
cd backend/fission
fission spec apply --specdir specs/ --wait
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Package build fails with "permission denied" | `chmod +x backend/fission/reddit/build.sh`, repackage |
| Function returns "Either 'hosts' or 'cloud_id' must be specified" | Add `--secret es-secret` when creating the function |
| Function pod fails to specialize | Check that `__init__.py` exists in the zip; check Python imports |
| `fission package update` blocked by other functions | Add `--force` flag |


