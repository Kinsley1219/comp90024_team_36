# Bluesky Harvester - Fission Functions

**COMP90024 Team 36 - Cluster and Cloud Computing Assignment 2**

## Overview

This module implements the Bluesky backend data pipeline for collecting Australian fuel price and cost-of-living related posts. The collected posts are cleaned, normalised, and written into Elasticsearch for later analysis and Kibana visualisation.

The pipeline is deployed as a Fission serverless function on Kubernetes. It supports both historical backfill and real-time incremental crawling.

## Architecture

This Bluesky harvester uses an event-driven Fission architecture with Elasticsearch-based cursor tracking.

```text
┌─────────────────────────┐
│ Fission Timer Trigger   │
│   (bluesky-timer)       │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐         ┌─────────────────────────┐
│ bluesky-harvester       │ ──────► │ Elasticsearch           │
│ function (Python 3.9)   │         │ social-posts index      │
└─────────────────────────┘         └────────────┬────────────┘
                                                 │
                             ┌───────────────────┴───────────────────┐
                             ▼                                       ▼
                    bluesky-cursors                         social-posts
                  crawler progress                    shared social media data
```

## File Structure

```text
backend/bluesky/
├── bluesky_harvester.py       Main Fission entry point and crawling workflow
├── bluesky_processor.py       Query list, secret reading, data cleaning, and document formatting
├── bluesky_storager.py        Elasticsearch connection, index creation, and storage logic
├── requirements.txt           Python dependencies
├── bluesky-harvester.zip      Fission deployment package
├── specs/                     Fission YAML specifications
│   ├── README
│   ├── fission-deployment-config.yaml
│   ├── function-bluesky-harvester.yaml
│   ├── package-bluesky-pkg.yaml
│   └── timetrigger-bluesky-timer.yaml
└── README.md
```

## Cluster Setup and Environment Check

After receiving the Kubernetes config file from a teammate, configure the local environment to connect to the cluster.

### Install required tools

```bash
brew install kubectl
brew install helm
brew install fission-cli
```

### Configure kubeconfig

```bash
mkdir -p ~/.kube
cp /path/to/config ~/.kube/config
chmod 600 ~/.kube/config
```

### Check Kubernetes connection

```bash
kubectl get nodes
kubectl get svc
```

### Check Elasticsearch

```bash
kubectl get svc -n elastic
kubectl get svc -A | grep -i elastic
```

### Check Fission

```bash
fission version
kubectl get all -n fission
```

### Create Python 3.9 Fission environment

Python 3.9 is used to avoid compatibility issues with the default Python 3.7 environment.

```bash
fission env create \
  --name python39 \
  --builder fission/python-builder-3.9 \
  --image fission/python-env-3.9
```

## Data Collection Logic

The Bluesky harvester collects posts using the Bluesky search endpoint. It searches for fuel price, petrol, diesel, rent, groceries, inflation, electricity, and cost-of-living related keywords in the Australian context.

### Historical Crawling

- Uses the `until` parameter to gradually crawl older posts.
- Processes a small batch of queries in each execution.
- Stores progress in the `bluesky-cursors` index.
- Avoids Fission timeout by splitting historical crawling across multiple runs.

### Real-time Crawling

- Uses the `since` parameter to collect new posts after the last collected timestamp.
- Updates the realtime cursor after new posts are saved.
- Supports continuous timer-based data collection.

### Query Rotation

The crawler does not process all queries in every execution. Instead, it selects a small query batch and stores the next query position in Elasticsearch. This keeps each function run short and stable.

The Bluesky post URI is used as the Elasticsearch document ID. If the same post is collected again, Elasticsearch updates the same document instead of creating duplicates.

## Elasticsearch Design

Collected social media posts are stored in the shared index:

```text
social-posts
```

The original Bluesky-only index was `bluesky-posts`. It was later changed to `social-posts` so that Bluesky and Reddit social media data can share the same schema and be queried together in Kibana.

Each document includes a `platform` field:

```json
{
  "platform": "bluesky"
}
```

This allows platform-specific filtering:

```text
platform:bluesky
platform:reddit
```

Crawler progress is stored separately in:

```text
bluesky-cursors
```

This cursor index is only used by the Bluesky crawler and should not be merged into `social-posts`.

## Document Schema

The Bluesky crawler writes documents similar to the following structure:

```json
{
  "url": "at://...",
  "text": "post text",
  "author": "example.bsky.social",
  "query": "petrol Australia",
  "created_at": "2026-05-08T12:00:00Z",
  "date": "2026-05-08",
  "platform": "bluesky",
  "ingested_at": "2026-05-08T12:01:00Z",
  "like": 0,
  "reply": 0,
  "repost": 0,
  "is_fuel": true,
  "is_cost": false,
  "is_au": true
}
```

---

### Field Descriptions

| Field | Description |
|---|---|
| `url` | Unique URI of the Bluesky post. Used as the Elasticsearch document ID to avoid duplicate records. |
| `text` | Main textual content of the post. |
| `author` | Bluesky user handle of the post creator. |
| `query` | Search keyword used during crawling. |
| `created_at` | Original timestamp of post creation. |
| `date` | Extracted date (`YYYY-MM-DD`) used for daily aggregation and Kibana visualisation. |
| `platform` | Source platform identifier (`bluesky`). |
| `ingested_at` | Timestamp when the document was stored in Elasticsearch. |
| `like` | Number of likes received by the post. |
| `reply` | Number of replies received by the post. |
| `repost` | Number of reposts received by the post. |
| `is_fuel` | Boolean indicator showing whether the post is related to fuel topics. |
| `is_cost` | Boolean indicator showing whether the post is related to cost-of-living topics. |
| `is_au` | Boolean indicator showing whether the post is related to Australia. |
| `sentiment_score` | VADER compound sentiment score ranging from `-1` to `1`. |
| `sentiment_label` | Sentiment category (`positive`, `neutral`, or `negative`). |
| `matched_location` | Detected Australian state or region inferred using keyword matching. |

### Feature Engineering

Several analytical features are generated during preprocessing to support filtering, aggregation, and sentiment analysis.

- `sentiment_score` and `sentiment_label` are generated using the VADER sentiment analysis model.
- `matched_location` is inferred using Australian location keyword matching.
- `is_fuel`, `is_cost`, and `is_au` are engineered topic indicators used for Kibana filtering and dashboard visualisation.


## Deployment Steps

### Step 1. Create Kubernetes Secret

The function reads Bluesky credentials and Elasticsearch connection details from the Kubernetes secret `es-secret`.

```bash
kubectl create secret generic es-secret \
  --from-literal=BSKY_USER='your_bsky_user' \
  --from-literal=BSKY_PASS='your_app_password' \
  --from-literal=ES_HOST='https://elasticsearch-es-http.elastic:9200' \
  --from-literal=ES_USER='elastic' \
  --from-literal=ES_PASSWORD='elastic' \
  --from-literal=INDEX_NAME='social-posts'
```

`BSKY_PASS` should be a Bluesky App Password, not the normal login password.

Check the secret:

```bash
kubectl get secret es-secret -o yaml
```

### Step 2. Create Deployment Zip

```bash
rm -f bluesky-harvester.zip

zip -r bluesky-harvester.zip \
  bluesky_harvester.py \
  bluesky_processor.py \
  bluesky_storager.py \
  requirements.txt
```

### Step 3. Create Fission Package

Before creating a new package, optionally check or delete the existing package.

```bash
fission package list
fission package delete --name bluesky-pkg
```

Create the package:

```bash
fission package create \
  --name bluesky-pkg \
  --env python39 \
  --sourcearchive bluesky-harvester.zip
```

Check package status:

```bash
fission package list
```

Expected status: succeeded

### Step 4. Create Fission Function

Before creating a new function, optionally check or delete the existing function.

```bash
fission fn list
fission fn delete --name bluesky-harvester
```

Create the function:

```bash
fission fn create \
  --name bluesky-harvester \
  --pkg bluesky-pkg \
  --env python39 \
  --entrypoint "bluesky_harvester.main" \
  --secret es-secret \
  --fntimeout 120
```

### Step 5. Test Function

```bash
fission fn test --name bluesky-harvester --timeout 2m
```

Expected output:

```json
{"saved":xxx,"status":"ok","total":xxx}
```

### Step 6. Create Timer Trigger

```bash
fission timer create \
  --name bluesky-timer \
  --function bluesky-harvester \
  --cron "@every 2m"
```

Check timer and logs:

```bash
fission timer list
fission fn logs --name bluesky-harvester
```

If Bluesky API rate limits occur, increase the timer interval or update the Bluesky account credentials in `es-secret`.

## Verify Data in Elasticsearch

Port-forward Elasticsearch:

```bash
kubectl port-forward -n elastic svc/elasticsearch-es-http 9200:9200
```

Open a new terminal and check the Bluesky data count:

```bash
curl -k -u elastic:elastic \
"https://localhost:9200/social-posts/_count?q=platform:bluesky"
```

Check available indices:

```bash
curl -k -u elastic:elastic "https://localhost:9200/_cat/indices?v"
```

Expected indices include:

```text
social-posts
bluesky-cursors
```

## Kibana Visualisation

Port-forward Kibana:

```bash
kubectl port-forward svc/kibana-kb-http -n elastic 5601:5601
```

Open Kibana in a browser:

```text
https://localhost:5601
```

Login:

```text
Username: elastic
Password: elastic
```

Create a data view:

```text
Name: bluesky
Index pattern: social-posts
Time field: created_at
```

Useful KQL filters:

```text
platform:bluesky
is_fuel:true
is_cost:true
query:"petrol Australia"
```

## Fission Specs

Fission specs are stored under:

```text
backend/bluesky/specs/
```

They are used for reproducible deployment.

Generate specs:

```bash
rm -rf specs
fission spec init

fission package create \
  --spec \
  --name bluesky-pkg \
  --env python39 \
  --sourcearchive bluesky-harvester.zip

fission fn create \
  --spec \
  --name bluesky-harvester \
  --pkg bluesky-pkg \
  --env python39 \
  --entrypoint "bluesky_harvester.main" \
  --secret es-secret \
  --fntimeout 120

fission timer create \
  --spec \
  --name bluesky-timer \
  --function bluesky-harvester \
  --cron "@every 2m"
```

Apply specs:

```bash
fission spec apply
```

If resources already exist, delete them first to avoid conflicts:

```bash
fission timer delete --name bluesky-timer
fission fn delete --name bluesky-harvester
fission package delete --name bluesky-pkg
```

## Update Workflow

After modifying the Bluesky Python code:

```bash
# 1. Repackage
rm -f bluesky-harvester.zip

zip -r bluesky-harvester.zip \
  bluesky_harvester.py \
  bluesky_processor.py \
  bluesky_storager.py \
  requirements.txt

# 2. Update package
fission package update \
  --name bluesky-pkg \
  --sourcearchive bluesky-harvester.zip

# 3. Update function
fission fn update \
  --name bluesky-harvester \
  --entrypoint "bluesky_harvester.main" \
  --secret es-secret \
  --fntimeout 120

# 4. Test
fission fn test --name bluesky-harvester --timeout 2m
```

## Reset for Testing

Reset only crawler progress:

```bash
curl -k -u elastic:elastic -X DELETE https://localhost:9200/bluesky-cursors
```

This keeps existing posts in `social-posts`.

Full reset from scratch:

```bash
curl -k -u elastic:elastic -X DELETE https://localhost:9200/social-posts
curl -k -u elastic:elastic -X DELETE https://localhost:9200/bluesky-cursors
```

Use full reset carefully because `social-posts` is shared with Reddit data.

Delete only Bluesky records while keeping Reddit records:

```bash
curl -k -u elastic:elastic -X POST "https://localhost:9200/social-posts/_delete_by_query" \
  -H "Content-Type: application/json" \
  -d '{"query":{"term":{"platform":"bluesky"}}}'
```

## Issues & Fixes

| Issue | Cause | Fix |
|---|---|---|
| Package stuck in `running` | Heavy dependencies such as `pandas` slowed down Fission package builds | Removed `pandas` from the crawler code and `requirements.txt` |
| Package build failed | Default Python 3.7 environment was incompatible | Created and used a Python 3.9 Fission environment |
| Function timeout | Original crawler attempted too much historical data in one run | Implemented incremental crawling with small query batches and cursor tracking |
| Bluesky API `429 Too Many Requests` | Frequent login requests during repeated testing and timer execution | Replaced the rate-limited Bluesky account and updated the Kubernetes secret credentials |

## Notes

- The crawler runs inside the Kubernetes cluster through Fission.
- Timer execution continues independently of the local terminal.
- `social-posts` is shared by Bluesky and Reddit data.
- `bluesky-cursors` stores only Bluesky crawler progress.
- The Bluesky URI is used as the Elasticsearch document ID to prevent duplicate posts.
- Real credentials should not be committed to GitLab.

## Contributor

**Xinyao Li** - Bluesky Harvester Development and Deployment  
COMP90024 Team 36 - Cluster and Cloud Computing Assignment 2
