# Comp90024 A2 Backend Guide
**Hanyue Li - Group 36**

## Table of Contents

1. [Backend — API Layer Design & Cloud Deployment](#1-backend--api-layer-design--cloud-deployment)
   - [Phase 0: Backend File Relationship Overview](#phase-0-backend-file-relationship-overview)
   - [Phase 1: Local Prototype & Data Source Validation](#phase-1-local-prototype--data-source-validation)
   - [Phase 2: Core API Implementation (Local FastAPI Prototype)](#phase-2-core-api-implementation-local-fastapi-prototype)
   - [Phase 3: Cloud Migration — Serverless Fission Deployment](#phase-3-cloud-migration--serverless-fission-deployment)
   - [Phase 4: Production Automation & Reliability](#phase-4-production-automation--reliability)

2. [Frontend Integration Guide: Fuel & Sentiment API](#2-frontend-integration-guide-fuel--sentiment-api)

---

# 1. Backend — API Layer Design & Cloud Deployment

## Phase 0: Backend File Relationship Overview

| File | Role | Runtime | ES Connection |
|------|------|---------|---------------|
| `aggregate_fuel.py` (local) | One-time bulk aggregation of all 4.35M historical records into `fuel-daily-summary` | WSL2, run manually | `127.0.0.1:9200` via port-forward |
| `aggregate_fuel.py` (cloud) | Daily incremental aggregation of previous day's data, deployed as Fission function `daily-aggregator` | Fission container, triggered by Timer `fuel-daily-aggregator` at 03:00 UTC | Internal cluster DNS |
| `api_gateway.py` (local) | Local prototype of the REST API — used to validate merge logic before cloud migration | Local FastAPI, `127.0.0.1:8000` | `127.0.0.1:9200` via port-forward |
| `analytics_service.py` (cloud) | Production version of `api_gateway.py`, adapted for Fission — deployed as function `fuel-sentiment-analytics` | Fission container, exposed via route `/api/v1/trends` | Internal cluster DNS |

**Key relationships:**
- `aggregate_fuel.py` (local) → validates aggregation logic → `aggregate_fuel.py` (cloud) is the same file adapted for Fission with incremental processing
- `api_gateway.py` → validates merge logic locally → `analytics_service.py` is the cloud adaptation of the same logic
- Both cloud functions read credentials from the same `es-secret` Kubernetes Secret

---
 
## Phase 1: Local Prototype & Data Source Validation
 
### Step 1: Environment Setup (Local Development)
* **Goal:**
  Establish an isolated local Python environment with all required backend dependencies before writing any API logic.
* **Action:**
  Run the following in the `local CLI (e.g. VS Code Terminal)`:
  ```bash
  # 1. Activate the dedicated project environment
  conda activate comp90024
 
  # 2. Install core backend dependencies
  pip install fastapi uvicorn elasticsearch>=8.12.0
  ```
 
### Step 2: Data Source Validation (Kibana Dev Tools)
* **Goal:**
  Before writing any Python logic, verify that the ES indices are reachable, correctly named, and have the expected data volume and schema. This prevents debugging integration errors later.
* **Action 1 — Connectivity & Content Verification:**
  Run in `Kibana → Dev Tools → Console`:
  ```bash
  # Sample social media records
  POST /_query?format=json
  { "query": "FROM \"social-posts\" | LIMIT 10" }
 
  # Sample fuel price records
  POST /_query?format=json
  { "query": "FROM \"fuelwatch-raw\" | LIMIT 10" }
  ```
 
* **Action 2 — Volume Check:**
  ```bash
  GET /social-posts/_count
  GET /fuelwatch-raw/_count
  ```
* **Checklist:**
  * `social-posts`: 70,000+ documents.
  * `fuelwatch-raw`: 4,350,000+ documents.
* **Action 3 — Schema & Mapping Audit:**
  ```bash
  GET /social-posts/_mapping
  GET /fuelwatch-raw/_mapping
  ```
* **Discovery:**
  The audit revealed that fields intended for numeric operations (e.g. `sentiment_score`, `product_price`) were dynamically indexed as `text` type. This caused aggregation queries to return 0 results even though Kibana showed data present.
* **Resolution:**
  Pivoted from ES|QL-style queries (which enforce strict schema) to **Elasticsearch Aggregation API** with schema-resilient handlers (`missing` parameter), bypassing the mapping constraint without requiring a full reindex of 4.3M records.

---

## Phase 2: Core API Implementation (Local FastAPI Prototype)
 
> **Architectural Decision: Decoupled Aggregation ("Compute Pushdown")**
>
> Rather than fetching raw records into Python and joining them there, heavy aggregation is pushed down to Elasticsearch independently for both datasets using `date_histogram`. Python receives only lightweight daily summaries and performs an in-memory hash-map merge. This avoids memory overflow in both the local process and later the Fission container.
 
### Step 1: Offline Aggregation Script (`aggregate_fuel.py`)
* **Goal:**
  Act as the offline data processing layer — command ES's shards to compute the daily average fuel price across 4.35M records and write results into the `fuel-daily-summary` index.
* **Key Implementation Points:**
  * Password read from environment variable (`ES_PASSWORD`) — never hardcoded.
  * `request_timeout=120` set for heavy aggregation over 4.35M records.
  * Uses `helpers.bulk()` for efficient batch write to the summary index.
  * Aggregation executes entirely inside ES with `size=0` — no raw records are transferred to the Python process, avoiding memory overflow.
* **Action:** 
  Ensure port-forward to ES (**port 9200**) is active in a separate terminal, then run in `WSL2 Ubuntu terminal`:
  ```bash
  # 0. Verify fuel-daily-summary index exists before running
  curl -k -u "elastic:elastic" "https://127.0.0.1:9200/_cat/indices/fuel-daily-summary?v"

  # 1. Navigate to local script directory
  cd "/mnt/c/Users/.../es_py"
 
  # 2. Set password as environment variable (session-only, secure)
  export ES_PASSWORD="elastic"
 
  # 3. Execute aggregation pipeline
  python3 aggregate_fuel.py
  ```
 
* **Algorithm (`aggregate_fuel.py`) — Daily Aggregation Pipeline:**
  ```
  ALGORITHM AggregateFuel
      READ ES_PASSWORD from environment variable
      IF not set → EXIT with error

      CONNECT to Elasticsearch at 127.0.0.1:9200
          with request_timeout = 120s (extended for 4.35M records)

      QUERY "fuelwatch-raw":
          GROUP BY publish_date (1-day interval)
          FOR EACH day → COMPUTE AVG(product_price)
          size = 0  // aggregation only, no raw records returned

      FOR EACH daily bucket:
          IF doc_count > 0 AND avg_price is not None:
              APPEND to bulk_actions:
                  { date: bucket.date, avg_price: round(avg, 2) }

      BULK INSERT bulk_actions → "fuel-daily-summary"
      PRINT count of successfully indexed records
  END ALGORITHM
  ```

  * **Verify output:**
  ```bash
  curl -k -u "elastic:elastic" \
      "https://127.0.0.1:9200/_cat/indices/fuel-daily-summary?v"
  ```

### Step 2: Timezone Drift Fix
* **Problem:**
UTC vs AEST (UTC+10) time difference caused posts made after 14:00 AEST to be bucketed into the wrong date (the following UTC day), creating a systematic 10-hour misalignment in the `date_histogram` buckets.
* **Diagnosis:**
Compared raw `created_at` timestamps against bucket boundaries — confirmed up to 10-hour offset between social post dates and fuel price dates.
* **Resolution:**
Explicitly added `"time_zone": "Australia/Melbourne"` to all `date_histogram` aggregation queries in the API handler, ensuring social posts are bucketed into the correct AEST date.
  ```json
  "date_histogram": {
      "field": "created_at",
      "calendar_interval": "1d",
      "time_zone": "Australia/Melbourne"
    }
  ```
 
### Step 3: Core API Logic (`api_gateway.py`)
* **Goal:**
  Build a REST endpoint that merges the fuel baseline and social sentiment data into a unified daily time-series JSON, optimized for frontend visualization.
* **Algorithm (`api_gateway.py`) — Hash-Map Merge:**
  ```bash
  ALGORITHM GetTrends
      CONNECT to Elasticsearch
 
      ON REQUEST GET "/api/v1/trends":
          TRY:
              SET fuel_aggs:   GROUP BY date(1d) → AVG(price)
              SET social_aggs: GROUP BY date(1d) → AVG(sentiment) + TERMS(platform)
 
              FETCH from "fuel-daily-summary" (pre-aggregated, O(1))
              FETCH from "social-posts-v1"    (real-time aggregation, size=0)
 
              INIT merged_map = {}
 
              FOR EACH hit IN fuel_results:
                  merged_map[date] = { date, national_avg_price, sentiment: 0, platforms: {} }
 
              FOR EACH bucket IN social_results:
                  IF date NOT IN merged_map: INIT with defaults
                  UPDATE merged_map[date] with total_posts, overall_avg_sentiment
                  FOR EACH platform_bucket:
                      merged_map[date].platforms[name] = { avg_sentiment, post_count }
 
              RETURN merged_map SORTED BY date ASC AS JSON Array
 
          CATCH Exception:
              RETURN Error Details
  END ALGORITHM
  ```
 
* **Schema Conflict & Resolution:**
  * **Issue:** Aggregations on `platform` and `product_price` returned 0 results because these fields were mapped as `text`.
  * **Solution:** Used schema-resilient aggregations targeting raw field strings with a `missing` value handler, allowing the aggregation engine to bucket data without enabling memory-intensive Fielddata.
* **CORS Configuration:**
  Added `CORSMiddleware` to FastAPI so the Jupyter Notebook frontend can consume the API cross-origin without browser security blocks.
### Step 4: Local Testing & API Contract Verification
* **Action:** 
  Run in local CLI (`VS Code Terminal or WSL2 Ubuntu terminal`).
  ```bash
  python api_gateway.py
  ```
* **Swagger UI:**
  Navigate to `http://127.0.0.1:8000/docs` to access the auto-generated Swagger UI. This served as the live **API contract** with the frontend team — providing a testable interface to inspect the JSON schema before cloud deployment.
* **Final JSON Response Structure (Frontend Contract):**
  ```json
  [
    {
      "date": "2026-05-11",
      "national_avg_price": 182.35,
      "total_posts": 1250,
      "overall_avg_sentiment": 0.452,
      "platforms": {
        "bluesky": { "avg_sentiment": 0.512, "post_count": 800 },
        "reddit":  { "avg_sentiment": 0.321, "post_count": 450 }
      }
    }
  ]
  ```

---

## Phase 3: Cloud Migration — Serverless Fission Deployment
 
> **Architectural Note: From Local Script to Cloud-Native**
> The local FastAPI prototype validated the logic. The next step is migrating to **Fission** (serverless framework on Kubernetes) so the API runs inside the MRC cluster, co-located with Elasticsearch, eliminating network latency and exposing the endpoint through the cluster router.
 
### Step 1: Pre-Deployment Cluster Audit
* **Goal:**
  Before pushing new code, audit the existing Fission environment to confirm the Python runtime, existing packages, and routes are in a healthy state.
* **Action:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  # 1. Verify Python environment is installed and functional
  fission env list
 
  # 2. Audit existing packages and build status
  fission pkg list
 
  # 3. Check existing routes to avoid URL path conflicts
  fission route list
  ```
* **Discovery:**
  Confirmed that the `python-39` environment was available and that no conflicting route existed on `/api/v1/trends`.
### Step 2: Kubernetes Secret Configuration (`es-secret`)
* **Goal:**
  Avoid hardcoding the Elasticsearch password in source code. Store it as a Kubernetes Secret and mount it into the Fission function at runtime.
* **Attention:**
  This is a one-time cluster setup step. If the secret already exists, skip creation and go directly to verification.
* **Action:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  # Create the secret (run once)
  kubectl create secret generic es-secret \
      --from-literal=password=elastic \
      -n fission-function
 
  # Verify
  kubectl get secret es-secret -n fission-function
  ```
 
* **How `analytics_service.py` gets the `secret` at runtime:**
  ```python
  secret_path = "/secrets/es-secret/password"
  if os.path.exists(secret_path):
      with open(secret_path, "r") as f:
          es_pass = f.read().strip()
  else:
      # Fallback for local testing
      es_pass = os.environ.get("ES_PASSWORD", "elastic")
  ```

* **[Incident Record] Secret Overwrite Caused Harvester Authentication Failure**
  * **Symptom:** Other team members' harvester Fission functions suddenly failed to write to ES with 401 Unauthorized errors.
  * **Root Cause:**
    The following command was used to update `es-secret`, which **completely overwrites** all existing secret fields with the newly specified values:
    ```bash
    kubectl create secret generic es-secret \
        --from-literal=BSKY_USER='yilin40.bsky.social' \
        --from-literal=BSKY_PASS='123456789' \
        --from-literal=ES_HOST='https://elasticsearch-es-http.elastic.svc.cluster.local:9200' \
        --from-literal=ES_USER='elastic' \
        --from-literal=ES_PASSWORD='elastic' \
        --from-literal=INDEX_NAME='social-posts' \
        --from-literal=password='elastic' \
        --dry-run=client -o yaml | kubectl apply -f -
    ```
    The `--dry-run=client -o yaml | kubectl apply -f -` pattern replaces the entire secret in-place. If any harvester's previously mounted field value differed from what was written here, every Fission function depending on that secret fails immediately.
  * **Important Distinction:**
    Running `export ES_PASSWORD="elastic"` locally has **no effect** on the cluster — it only exists for the current terminal session and disappears on close. The destructive action was the `kubectl apply` that persistently modified the secret stored in Kubernetes.
  * **Fix:**
    Re-apply the complete secret (command above) with all team members' required fields included, ensuring the password value matches the actual ES password.
  * **Lesson:**
    `es-secret` is a shared team resource. Before modifying it, always inspect the current fields first:
    ```bash
    kubectl get secret es-secret -n fission-function -o yaml
    ```
 
### Step 3: Cloud-Ready Function Engineering (`analytics_service.py`)
* **Goal:**
  Adapt the local API logic to work inside the MRC cluster network — using the internal ES service URL, Kubernetes Secrets for credentials, and server-side aggregations to stay within Fission container memory limits.
* **Key Technical Changes from Local Version:**
  * **Internal cluster URL:** 
  `https://elasticsearch-es-http.elastic.svc.cluster.local:9200` (replaces `127.0.0.1:9200`).
  * **Secure handshake:** `verify_certs=False` to bypass internal self-signed certificate.
  * **Memory guard:** All queries use `size: 0` so aggregation executes inside ES, not in the Fission container.
  * **Credential mounting:** Password read from Kubernetes Secret file path instead of environment variable.
* **Algorithm (`analytics_service.py`) — Cloud-Native API Entry Point:**
  ```
  ALGORITHM GetTrends  [Fission Entrypoint: main()]
      SET es_host = internal cluster URL (elasticsearch-es-http.elastic.svc.cluster.local:9200)

      RETRIEVE password:
          IF /secrets/es-secret/password exists (cloud):
              READ password from mounted Secret file
          ELSE (local testing):
              READ from environment variable ES_PASSWORD

      CONNECT to Elasticsearch
          with verify_certs=False, request_timeout=60s

      // --- Fuel Data (pre-aggregated, fast lookup) ---
      FETCH top 2000 records from "fuel-daily-summary"
          SORT BY date ASC

      // --- Social Sentiment (real-time aggregation) ---
      QUERY "social-posts-v1" with size=0:
          GROUP BY created_at (1-day interval, time_zone=Australia/Melbourne)
          FOR EACH day:
              COMPUTE AVG(sentiment_score)
              TERMS BY platform.keyword:
                  COMPUTE AVG(sentiment_score) per platform

      // --- Merge ---
      INIT merged_map = {}

      FOR EACH fuel record:
          merged_map[date] = { date, national_avg_price, sentiment=0, platforms={} }

      FOR EACH social bucket:
          IF date NOT IN merged_map: INIT with defaults
          UPDATE merged_map[date]:
              total_posts, overall_avg_sentiment
              FOR EACH platform bucket:
                  platforms[name] = { avg_sentiment, post_count }

      RETURN merged_map SORTED BY date ASC
          as { "status": "success", "data": [...] }

      ON ANY ERROR:
          RETURN { "status": "error", "message": <error detail> }
  END ALGORITHM
  ```
 
### Step 4: Source Packaging & Deployment
* **Goal:**
  Bundle `analytics_service.py` and `requirements.txt` into a ZIP archive and deploy to the Fission cluster.
* **Action 1 — Package locally on Windows:**
  In File Explorer, `navigate to the function directory`:
    Ensure the following two files are present:
  * `analytics_service.py`
  * `requirements.txt`
  Select both files → right-click → **Compress to ZIP** → rename to `my_code.zip`.
* **Action 2:**
  Deploy from `WSL2 Ubuntu terminal`:
  ```bash
  # 0. Navigate to the directory containing my_code.zip
  cd "/mnt/c/Users/.../es_py"

  # 1. Create function (first deployment)
  fission fn create \
      --name fuel-sentiment-analytics \
      --env python-39 \
      --src my_code.zip \
      --entrypoint "analytics_service.main" \
      --secret es-secret

  # 2. Update function (subsequent deployments)
  fission fn update \
      --name fuel-sentiment-analytics \
      --src my_code.zip \
      --secret es-secret

  # 3. Monitor build status — wait for 'succeeded'
  fission pkg list
  ```

### Step 5: Route Configuration & Secure Tunneling
* **Goal:**
  Expose the function via a stable HTTP path and establish a port-forward tunnel so the local Jupyter Notebook or browser can call the internal cluster API.
* **Action 1 — Create Route:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  fission route create \
      --name fuel-sentiment-route \
      --method GET \
      --url /api/v1/trends \
      --function fuel-sentiment-analytics
  ```
 
* **Action 2 — Open Tunnel (keep terminal active):**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  kubectl port-forward service/router -n fission 8888:80
  ```
 
* **Attention:**
  * **Port 8888:** 
  Used for **Jupyter/Browser-to-API** communication (frontend calling Fission functions).
  * **Keep this terminal session alive** for the duration of any frontend demo or testing.
  
### Step 6: Production Testing & Verification
* **Goal:**
  Verify the end-to-end cloud deployment by triggering the function and validating the live JSON payload.
* **Action 1 — Fission function test:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  fission fn test --name fuel-sentiment-analytics
  ```
 
* **Action 2 — Direct HTTP call via tunnel:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  curl http://127.0.0.1:8888/api/v1/trends
  ```
 
* **Action 3 — Log inspection:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  fission fn log --name fuel-sentiment-analytics
  ```
 
* **Expected Outcome:**
  A time-sorted JSON array is returned with merged fuel and sentiment data. 
  A successful response confirms the transition from local prototype to cloud-native API is complete.

---

## Phase 4: Production Automation & Reliability

### Step 1: Deploy Cloud Aggregation Function (`daily-aggregator`)
* **Goal:**
  * Deploy the production version of the aggregation pipeline as a Fission serverless function. Unlike the local `aggregate_fuel.py` which runs manually against `127.0.0.1:9200`, this cloud version uses the internal cluster URL, reads credentials from Kubernetes Secret, and processes only the previous day's data incrementally to avoid duplicate writes.
  * This step was performed after initial local testing — **see Phase 2 Step 1 
  for the local version**.

* **Algorithm (`aggregate_fuel.py`) — Incremental Daily Aggregation:**
  ```
  ALGORITHM DailyAggregator  [Fission Entrypoint: aggregate_fuel.main()]
      RETRIEVE password from /secrets/es-secret/password
          FALLBACK to ES_PASSWORD environment variable

      CONNECT to elasticsearch-es-http.elastic.svc.cluster.local:9200
          with request_timeout = 120s

      COMPUTE date window:
          yesterday = today - 1 day (UTC)
          date_from = yesterday, date_to = today

      QUERY "fuelwatch-raw" with size=0:
          FILTER publish_date >= date_from AND < date_to
          GROUP BY publish_date (1-day interval)
          FOR EACH day → COMPUTE AVG(product_price)

      FOR EACH bucket:
          IF doc_count > 0 AND avg_price is not None:
              APPEND to bulk_actions:
                  { date: bucket.date, avg_price: round(avg, 2) }

      BULK INSERT bulk_actions → "fuel-daily-summary"
      RETURN "Aggregation completed successfully.", 200

      ON ANY ERROR:
          RETURN "Aggregation failed: <error>", 500
  END ALGORITHM
  ```

* **Action1 — Package locally on Windows:**
  In File Explorer, select `aggregate_fuel.py` and `requirements.txt` → right-click → **Compress to ZIP** → rename to `aggregator.zip`.

  **Action 2:**
  Deploy from `WSL2 Ubuntu terminal`:
  ```bash
  # 0. Navigate to the directory containing aggregator.zip
  cd "/mnt/c/Users/.../es_py"

  # 1. Create function (first deployment)
  fission fn create \
      --name daily-aggregator \
      --env python-39 \
      --src aggregator.zip \
      --entrypoint "aggregate_fuel.main" \
      --secret es-secret \
      --fntimeout 300

  # 2. Update function (subsequent deployments)
  fission fn update \
      --name daily-aggregator \
      --src aggregator.zip \
      --secret es-secret

  # 3. Monitor build status — wait for 'succeeded'
  fission pkg list
  ```
 
### Step 2: Automated Daily Refresh (Fission Timer Trigger)
* **Goal:**
  Schedule the aggregation pipeline to run unattended every night, ensuring `fuel-daily-summary` stays current without manual intervention.
* **Action:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  fission timer create \
      --name fuel-aggregation-daily \
      --function daily-aggregator \
      --cron "0 3 * * *"
  ```
 
* **Explanation:**
  Triggers at `03:00 UTC every day`. Runs the offline aggregation script to process any new raw fuel data ingested overnight and refresh the summary index.


### Step 3: Verification
* **Action 1 — Confirm timer was created:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  fission timer list
  ```
  * Expected: `fuel-aggregation-daily` appears with cron `0 3 * * *`.

* **Action 2 — Manually trigger the function to test without waiting:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  fission fn test --name daily-aggregator
  ```
  * Expected: function executes and prints indexed record count.

* **Action 3 — Confirm summary index was refreshed:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  curl -k -u "elastic:elastic" \
      "https://127.0.0.1:9200/fuel-daily-summary/_count"
  ```
  * Expected: `docs.count` is non-zero and consistent with previous run.

* **Action 4 — Check function execution logs:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  fission fn log --name daily-aggregator
  ```
  * Expected: log shows `[+] Pipeline complete. Indexed: X records.`

* **Action 5 — Verify via API response:**
  Run in `WSL2 Ubuntu terminal`:
  ```bash
  curl http://127.0.0.1:8888/api/v1/trends
  ```
  * Expected: returned JSON contains up-to-date `national_avg_price` entries with today's date.

---

# 2. Frontend Integration Guide: Fuel & Sentiment API
> **Project Context:** 
> Backend API Integration Successfully Verified. The analytics engine is live on the MRC cluster via Fission.
- **Access Method**: Must run `kubectl port-forward service/router -n fission 8888:80` locally first.
- **Endpoint**: `http://127.0.0.1:8888/api/v1/trends`
- **Data Logic**: 
    - The `data` array is time-sorted (ASC).
    - `national_avg_price` may be `null` for some dates; please handle this in your chart logic.
    - `platforms` contains nested sentiment scores for Reddit and Bluesky.

---

### Step 1: Establish the Secure Data Tunnel
Since the API is hosted within the private Melbourne Research Cloud (MRC) network, you must bridge the connection to your local machine before fetching data.
* **Action:** Run the following command in your terminal and **leave it running**:
  ```bash
  kubectl port-forward service/router -n fission 8888:80
  ```
* **API Endpoint:** Once the tunnel is active, the API will be available at:
`http://127.0.0.1:8888/api/v1/trends`.

---

### Step 2: Understand the Data Contract (JSON Schema)
The API returns a cleaned, time-sorted array. Each object merges fuel data with platform sentiment metrics.
* **Sample Structure:**
  ```json
  {
    "status": "success",
    "data": [
      {
        "date": "2026-05-11",
        "national_avg_price": 218.05,
        "total_posts": 745,
        "overall_avg_sentiment": 0.1321,
        "platforms": {
          "reddit": { "avg_sentiment": 0.3107, "post_count": 101 },
          "bluesky": { "avg_sentiment": -0.1053, "post_count": 76 }
        }
      }
    ]
  }
  ```

---

### Step 3: Fetching Data (Jupyter Notebook)
* **Attention:** **Do NOT** use Google Colab for this API. Colab runs on Google's remote servers and cannot "see" the 127.0.0.1 tunnel on your local machine.
* **Python Logic:**
  ```python
  # Using standard requests to handle the JSON payload
  import requests

  API_URL = "http://127.0.0.1:8888/api/v1/trends"

  response = requests.get(API_URL)
  payload = response.json()

  if payload['status'] == 'success':
      dataset = payload['data']
      # Loop through 'dataset' to extract values for your charts
  ```