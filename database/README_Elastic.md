# Comp90024 A2 Elastic and Backend Guide
**Hanyue Li - Group 36**

## Table of Contents

1. [Infrastructure Deployment: Elasticsearch and Kibana](#1-infrastructure-deployment-elasticsearch-and-kibana)
   - [1.1 Environment Setup](#11-environment-setup)
   - [1.2 Local Environment Preparation](#12-local-environment-preparation)
   - [1.3 Elastic Stack Deployment](#13-elastic-stack-deployment)
   - [1.4 Verification and Access](#14-verification-and-access)
   - [1.5 Export and Save Configurations](#15-export-and-save-configurations)

2. [Elasticsearch — Data Layer Design & Optimization](#2-elasticsearch--data-layer-design--optimization)
   - [Phase 1: Index Schema Design & Initial Setup](#phase-1-index-schema-design--initial-setup)
   - [Phase 2: Distributed Storage Architecture (Sharding)](#phase-2-distributed-storage-architecture-sharding)
   - [Phase 3: Decoupled Aggregation Pipeline](#phase-3-decoupled-aggregation-pipeline)

3. [Elasticsearch — Production Index Reference](#3-elasticsearch--production-index-reference)

---

# 1. Infrastructure Deployment: Elasticsearch and Kibana

This section outlines the deployment process for the Elasticsearch and Kibana infrastructure
on a Kubernetes cluster.

## 1.1 Environment Setup
The deployment was executed using the following environment and toolset:
* Windows + WSL2 (Ubuntu 24.04)
* Kubernetes Cluster (MRC/NeCTAR)
* Helm Package Manager
* Elastic Cloud on Kubernetes (ECK)

---

## 1.2 Local Environment Preparation

### 1.2.1 Install kubectl
Update the local package list:
```bash
sudo apt-get update
```

Download the latest stable kubectl binary for Linux:
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
```

Install kubectl with executable permissions:
```bash
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

Verify the installation:
```bash
kubectl version --client
```
> **Expected output:** Client Version: v1.36.0

### 1.2.2 Configure Kubernetes Access
Create the standard directory for Kubernetes configuration:
```bash
mkdir -p ~/.kube
```

Copy the cluster configuration file provided for the project:
```bash
cp <path-to-your-kube-config> ~/.kube/config
```

Set the appropriate security permissions for the configuration file:
```bash
chmod 600 ~/.kube/config
```

Verify the connection to the remote cluster:
```bash
kubectl get nodes
```
> **Expected output:** 
> All nodes show STATUS: Ready

### 1.2.3 Install Helm
Install Helm using the official automated script:
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Verify the Helm installation:
```bash
helm version
```
> **Expected output:** v3.20.2

---

## 1.3 Elastic Stack Deployment

### 1.3.1 Add Elastic Helm Repository
Add the official Elastic repository to Helm:
```bash
helm repo add elastic https://helm.elastic.co
```

Update local repositories to fetch the latest charts:
```bash
helm repo update
```

### 1.3.2 Install Elastic Cloud on Kubernetes (ECK) Operator
Deploy the Elastic Operator, which manages the lifecycle of Elastic resources, into a
dedicated namespace:
```bash
helm upgrade --install elastic-operator elastic/eck-operator \
  --namespace elastic \
  --create-namespace \
  --version "v3.2.0"
```

Verify the operator deployment:
```bash
kubectl get pods -n elastic
```
> **Expected output:** elastic-operator-0   Running

### 1.3.3 Prepare Deployment Files
Navigate to the local deployment directory containing the project manifests:
```bash
cd "<path-to-your-local-directory>"
```

The local directory contains the following assets:
* `storage-class.yaml`
* `elasticsearch.yaml`
* `kibana.yaml`

### 1.3.4 Deploy Storage Class
Apply the storage class to handle persistent volumes for the database:
```bash
kubectl apply -f storage-class.yaml
```

### 1.3.5 Create Elasticsearch User Secret
Manually define the authentication credentials for the default `elastic` user to override
the auto-generated password:
```bash
kubectl -n elastic create secret generic elasticsearch-es-elastic-user \
  --from-literal=elastic='elastic' \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 1.3.6 Deploy Elasticsearch and Kibana
Provision the Elasticsearch cluster nodes:
```bash
kubectl apply -f elasticsearch.yaml
```

Deploy the Kibana dashboard linked to the Elasticsearch cluster:
```bash
kubectl apply -f kibana.yaml
```

---

## 1.4 Verification and Access

### 1.4.1 Verify Deployment
Monitor the initialization status of all associated pods:
```bash
kubectl get pods -n elastic --watch
```
> **Expected running services:**
> * elastic-operator
> * elasticsearch-es-default-0
> * elasticsearch-es-default-1
> * kibana-kb
>
> All pods should eventually reach the status: **Running**.

### 1.4.2 Access Cloud Services (Port Forwarding)
Establish secure local tunnels to the cloud services. **These commands must run in
separate terminal sessions.**

**Elasticsearch REST API (For Data Harvesters & Jupyter):**
```bash
kubectl port-forward service/elasticsearch-es-http -n elastic 9200:9200
```
> Access Endpoint: `https://127.0.0.1:9200`

**Kibana Web UI (For Administration & Analysis):**
```bash
kubectl port-forward service/kibana-kb-http -n elastic 5601:5601
```
> Access Endpoint: `https://127.0.0.1:5601`

---

## 1.5 Export and Save Configurations

Extract the running, finalized state of the deployments into static YAML files for
version control and documentation:
```bash
kubectl get elasticsearch elasticsearch -n elastic -o yaml > final_elasticsearch.yaml
kubectl get kibana kibana -n elastic -o yaml > final_kibana.yaml
```

Transfer the generated configuration files back to the Windows host directory:
```bash
cp ~/final_*.yaml <path_to_your_local_directory>
```

---

## Final Result
The following architectural components have been successfully deployed and verified:
* Elastic Cloud on Kubernetes (ECK) Operator
* High-availability Elasticsearch cluster
* Kibana data visualization dashboard
* Persistent storage class configuration
* Static authentication secrets and local network tunnels

Both Elasticsearch and Kibana services are actively running and accessible for data
ingestion and analytical tasks.

---

# 2. Elasticsearch — Data Layer Design & Optimization

## Phase 1: Index Schema Design & Initial Setup

### Step 1: Start Ubuntu and Port-Forwarding
* **Goal:** 
  Before any data operations, we must ensure a stable connection between the local development environment and the remote Elasticsearch (ES) cluster deployed on Kubernetes.

* **Attention:**
  * **Port 9200:** Used for **Backend-to-DB** communication (FastAPI/Python to ES). 
  * **Port 5601:** Used for **Human-to-DB** interaction (Kibana Dev Tools).

* **Action:** 
  Create stable paths to the core database (Elasticsearch) and the management interface (Kibana) from local environment.
  ```bash
  # Terminal 1: Bridge to the ES Engine (For Backend/API)
  kubectl port-forward -n elastic svc/elasticsearch-es-http 9200:9200

  # Terminal 2: Bridge to the Kibana Dashboard (For Management)
  kubectl port-forward svc/kibana-kb-http -n elastic 5601:5601
  ```
* **Verification:** 
  * Access https://127.0.0.1:9200 in the browser. A JSON response confirms the database is alive.
  * Access https://127.0.0.1:5601 in the browser to enter the Kibana UI.

### Step 1.2 [Post-Hoc Note]: Standard Mapping Reference
* **Background**:
This step was `not performed during initial setup`. Indices were created without explicitly specifying `number_of_shards`, so ES defaulted to a single-shard configuration. Dynamic Mapping correctly inferred all core field types from the ingested data, so no schema issues arose (e.g. `sentiment_score` and `product_price` were recognized correcly as `float`).
* **Discovery:**
As data volume grew (4.3M+ records in `fuelwatch-raw`, 70,000+ in `social-posts`), the single-shard layout became a bottleneck — all read/write load was concentrated on one node with no horizontal distribution.
* **Resolution:** 
Rather than deleting and recreating the indices (which would lose all ingested data), a data-safe migration was performed via `_reindex` + `Index Aliasing`, prioritising data integrity over zero-downtime. 
This is documented in **Phase 2: Distributed Storage Architecture (Sharding)**.
* **What should have been done here:**
  * **Warning:** 
  Running `DELETE` **will wipe existing data**. **Only perform this** during the **initial setup** or when a **schema reset is required**.
  * **Action:** 
    Execute in `Kibana -> Dev Tools -> Console`:
    ```bash
    # 1. Clear old structures (Skip if data is already correct)
    DELETE /social-posts
    # If error 404 occurs, it means the policy doesn't exist yet; proceed to Step 2.
    DELETE /_enrich/policy/fuel_price_policy

    # 2. Define Standardized Mapping
    PUT /social-posts
    {
      "settings": {
        "index": {
          "number_of_shards": 3,
          "number_of_replicas": 1
        }
      },
      "mappings": {
        "properties": {
          "date": { "type": "date" },
          "created_at": { "type": "date" },
          "ingested_at": { "type": "date" },
          "platform": { "type": "keyword" },
          "author": { "type": "keyword" },
          "text": { "type": "text" },
          "sentiment_score": { "type": "float" },
          "sentiment_label": { "type": "keyword" },
          "is_au": { "type": "boolean" },
          "is_fuel": { "type": "boolean" },
          "is_cost": { "type": "boolean" },
          "matched_location": { "type": "keyword" },
          "query": { "type": "keyword" },
          "like": { "type": "integer" },
          "reply": { "type": "integer" },
          "repost": { "type": "integer" },
          "subreddit": {
            "type": "text",
            "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } }
          },
          "url": { "type": "keyword" }
        }
      }
    }

    # 3. Define Standardized Mapping for Fuel Table
    PUT /fuelwatch-raw
    {
      "settings": {
        "index": {
          "number_of_shards": 3,
          "number_of_replicas": 1
        }
      },
      "mappings": {
        "properties": {
          "date": { "type": "date" },
          "price_value": { "type": "float" },
          "state": { "type": "keyword" },
          "fuel_type": { "type": "keyword" },
          "location": { "type": "geo_point" }
        }
      }
    }
    ```
* **Lesson:**
Always define explicit `mappings` and `settings.number_of_shards` before any data ingestion. Once data exists, schema changes require a full reindex.

### Step 2: Data Audit & Verification
* **Goal:** 
  Confirm that data ingested by harvesters has actually arrived, and verify the schema is correct before building any query logic.

* **Action 1 — Index & Volume Check:** 
  Go to `Kibana -> Management -> Dev Tools` and run:
  ```bash
  # Check index and data quantity
  GET /_cat/indices?v&s=index
  ```
* **Checklist:** 
  * Index `social-posts`: Check the docs.count (70,000+). If it is 0, the data ingestion from scrapers has failed.

  * Index `fuelwatch-raw`: Ensure the reference data for fuel prices is present and intact (4.3M+).
  
  * Health Status: Ensure the indices are `green` or `yellow`.
* **Action 2 — Mapping Inspection:** 
  Go to `Kibana -> Management -> Dev Tools` and run:
  ```bash
  GET /social-posts/_mapping
  GET /fuelwatch-raw/_mapping
  ```
* **Checklist:** 
  Confirm `sentiment_score` is `float`, `platform` is `keyword`, and `date` fields are `date` type — not `text`.
* **Action 3 — Sample Record Check:** 
  Go to `Kibana -> Management -> Dev Tools` and run:
  ```bash
  GET /social-posts/_search
  { "size": 1 }

  GET /fuelwatch-raw/_search
  { "size": 1 }
  ```
* **Discovery:** 
  * Granularity mismatch found between `fuelwatch-raw` `location` (suburb-level, ALL CAPS, e.g. "NEERABUP") and `social-posts` `matched_location`(city-level, e.g. "Sydney"/"Australia"). 
  * **Resolution:** Abandon strict geospatial joining; rely exclusively on **date-based time-series joining for Phase 2**.

### Step 3: Create Kibana Data Views
* **Goal:** 
  Create unified observation windows in Kibana for ongoing data monitoring.

* **Action 1 — Social Posts View:** 
  1. Navigate to **Stack Management → Kibana → Data Views → Create data view**.
  2. **Name:** `Social Posts Analytics`.
  3. **Index pattern:** `social-posts`.
  4. **Timestamp field:** `created_at`.
  5. Save.

* **Action 2 — Fuel Data View:** 
  1. Navigate to **Stack Management → Kibana → Data Views → Create data view**.
  2. **Name:** `Fuel Prices Raw`.
  3. **Index pattern:** `fuelwatch-raw`.
  4. **Timestamp field:** `publish_date`.
  5. Save.
* **UI Sanity Check (Kibana → Discover):** 
  * **Time Range:** Adjust the top-right time picker. Ensure data populates and the histogram appears.
  * **Data Types (Sidebar):** Verify `product_price` and `sentiment_score` have the `#` (numeric) icon. Verify dates have the calendar icon.
  * Verify `date` fields show the `calendar` icon.

---

  ## Phase 2: Distributed Storage Architecture (Sharding)
> **Architectural Decision Record: Why Sharding**
> The initial `fuelwatch-raw` index was created with number_of_shards: 1. This meant all 4.35M records sat on a single node, creating a bottleneck. 
> To achieve true distributed computation, the architecture was upgraded: a new sharded summary index was introduced to distribute data and query load across all cluster nodes.

### Step 1: Create Sharded Summary Index (`fuel-daily-summary`)
* **Action:** 
  Go to `WSL2 Ubuntu terminal` and run:
  ```bash
  curl -X PUT "https://127.0.0.1:9200/fuel-daily-summary" \
    -k -u "elastic:elastic" \
    -H 'Content-Type: application/json' -d'
  {
    "settings": {
      "index": {
        "number_of_shards": 3,
        "number_of_replicas": 1
      }
    },
    "mappings": {
      "properties": {
        "date":      { "type": "date" },
        "avg_price": { "type": "float" }
      }
    }
  }'
  ```

### Step 2: Data Migration via `_reindex` + `Index Aliasing`
* **Goal:**
  Migrate both indices from single-shard to 3-shard compliant versions without modifying any harvester code. An alias is applied post-migration so all existing writes transparently route to the new index.

* **Attention:**
  A brief window exists between `DELETE` and alias creation where harvester writes may fail. To eliminate this risk, **pause all harvesters** before executing this migration and resume after Step 10.

* **Action:**
  Go to `Kibana -> Management -> Dev Tools` and run:
  ```bash
  # ── social-posts ──────────────────────────────────────────
  # 1. Create new compliant index with explicit 3-shard mapping
  PUT /social-posts-v1
  {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1
    },
    "mappings": { "dynamic": true }
  }

  # 2. Reindex all data into the new 3-shard compliant index
  POST /_reindex
  {
    "source": {
      "index": "social-posts"
    },
    "dest": {
      "index": "social-posts-v1"
    }
  }

  # 3. Verify data integrity before deletion — counts must match
  GET /social-posts/_count
  GET /social-posts-v1/_count

  # 4. Delete the original single-shard index
  DELETE /social-posts

  # 5. Apply alias so all existing harvester code requires zero changes
  POST /_aliases
  {
    "actions": [
      { "add": { 
      "index": "social-posts-v1", 
      "alias": "social-posts" } }
    ]
  }

  # 6. Verify alias and shard configuration
  GET /_alias/social-posts
  GET /social-posts/_settings

  # ── fuelwatch-raw ──────────────────────────────────────────
  # 7. Create new compliant index with explicit 3-shard mapping
  PUT /fuelwatch-raw-v1
  {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1
    },
    "mappings": { "dynamic": true }
  }

  # 8. Reindex all 4.35M records into the new index
  POST /_reindex
  {
    "source": { "index": "fuelwatch-raw" },
    "dest":   { "index": "fuelwatch-raw-v1" }
  }

  # 9. Verify data integrity before deletion — counts must match
  GET /fuelwatch-raw/_count
  GET /fuelwatch-raw-v1/_count

  # 10. Delete the original single-shard index
  DELETE /fuelwatch-raw

  # 11. Apply alias
  POST /_aliases
  {
    "actions": [
      { "add": { 
      "index": "fuelwatch-raw-v1", 
      "alias": "fuelwatch-raw" } }
    ]
  }

  # 12. Verify alias and shard configuration
  GET /_alias/fuelwatch-raw
  GET /fuelwatch-raw/_settings
  ```

* **Outcome:**
  Both indices migrated to 3-shard compliant versions. 
  Original indices deleted only after document count parity was confirmed. 
  Aliases applied so all harvester write targets (`social-posts`, `fuelwatch-raw`) require zero code changes — they transparently route to their respective v1 indices.

* **Note on data safety:**
  This approach prioritises data integrity over zero-downtime: reindex completes fully and count is verified before any deletion occurs. This is appropriate for a development environment where harvesters can be briefly paused during migration.

### Step 3: Verify Sharding Distribution
* **Action 1:** 
  Go to `WSL2 Ubuntu terminal` and run:
  ```bash
  # 1. Verify shard distribution across nodes
  curl -k -u "elastic:elastic" \
    "https://127.0.0.1:9200/_cat/shards/fuelwatch-raw?v"
  ```
  * **Outcome:**
    * 3 shards (0, 1, 2), each with 1 primary (p) and 1 replica (r) — 6 shard instances total.
    * Primary shards distributed across 2 nodes (`elasticsearch-es-default-0`, `elasticsearch-es-default-1`), confirming horizontal scaling.
    * Each shard holds ~1.45M records at ~215MB, evenly balanced across nodes.
  
* **Action 2:** 
  Go to `WSL2 Ubuntu terminal` and run:
  ```bash
  # 2. Verify data volume and physical storage size
  curl -k -u "elastic:elastic" \
    "https://127.0.0.1:9200/_cat/indices/fuelwatch-raw?v"
  ```
  * **Outcome:**
    * Index: `fuelwatch-raw-v1` (accessed via alias `fuelwatch-raw`)
    * Health: `green` — all primary and replica shards assigned.
    * `docs.count`: **4,350,000+** records successfully migrated.
    * `store.size`: **1.2GB** total (primary: 645.3MB across 3 shards).
    * Cross-reference with `fuel-daily-summary`: 4.37M raw records reduced to ~1,500 daily summary rows — demonstrating the effectiveness of the aggregation pipeline.

* **Action 3:** 
  Go to `WSL2 Ubuntu terminal` and run:
  ```bash
  # 3. Verify cluster health and node load during aggregation
  curl -k -u "elastic:elastic" \
    "https://127.0.0.1:9200/_cat/nodes?v&h=name,cpu,ram.percent,heap.percent,fielddata.memory_size"
  ```
  * **Outcome:**
    * 2 active nodes: `elasticsearch-es-default-0`, `elasticsearch-es-default-1`.
    * Both nodes at 96% RAM usage — expected given 4.37M records in memory.
    * Heap usage: 20% and 54% respectively — within safe operating range.
    * Fielddata: 1.7kb / 3.7kb — minimal, confirming aggregations are using `keyword` fields correctly rather than loading full text into memory.

---

## Phase 3: Decoupled Aggregation Pipeline
> **Architectural Decision: Pivot from Database-Layer Join to Decoupled Aggregation**
>
> **Context:**
> The goal was to correlate daily fuel prices with social media sentiment. Three approaches were attempted before arriving at the final solution.
>
> **Approach 1 — ES|QL LOOKUP Join (Abandoned):**
> Created a `fuel-lookup-table` index with `index.mode: lookup` and attempted a direct `LOOKUP` join in ES|QL. Failed due to date format incompatibility: `social-posts.created_at` stores full ISO timestamps while the lookup key required an exact string match — no implicit truncation was available.
>
> **Approach 2 — ENRICH Policy (Abandoned):**
> Created an ENRICH policy matching on `lookup_date` to inject fuel price into each social post at query time. Two blockers identified:
> 1. *Time Precision Mismatch:* Raw fuel data was ingested with a forced default timestamp (e.g., `10:00:00`), causing strict date-based joins to fail against social posts recorded at exact seconds (e.g., `16:53:46`).
> 2. *Statistical Inaccuracy:* The `ENRICH` processor retrieves only the *first* matched document — returning a single petrol station's price rather than the true national daily average.
>
> **Approach 3 — Compute Pushdown (Final Solution):**
> Abandoned database-layer joining entirely. Heavy aggregation is pushed down to Elasticsearch independently for both datasets using `date_histogram`. Python receives only lightweight daily summaries and performs a safe in-memory hash-map merge. This eliminates both the precision mismatch and the statistical inaccuracy in a single architectural change.

### Step 1: Verify Aggregation Queries (Kibana Dev Tools)
* **Goal:** 
  Verify that the data truncation and aggregations execute correctly on the raw data before integrating them into the Python application.
  
* **Action 1 — Social Media Sentiment Query:** 
  Test Social Media Volume & Sentiment Query (Cross-Platform).
  Run the following ES|QL queries in `Kibana -> Dev Tools -> Console` and visually inspect the JSON output.
  ```bash
  POST /_query?format=json
  {
    "query": """
      FROM social-posts
      | EVAL date_only = DATE_TRUNC(1 days, created_at)
      | STATS 
          avg_sentiment = AVG(sentiment_score), 
          post_count = COUNT(*) 
        BY date_only, platform
      | SORT date_only ASC
    """
  }
  ```
* **Expected output:** 
  Chronological list partitioned by platform, with post count and average sentiment per platform per day. Avoids backend memory overflow by aggregating entirely within ES.

* **Action 2 — Fuel Price Baseline Query:** 
  Test National Daily Average Fuel Price Query.
  Run the following ES|QL queries in `Kibana -> Dev Tools -> Console` and visually inspect the JSON output.
  ```bash
  POST /_query?format=json
    {
      "query": """
        FROM fuelwatch-raw
        | EVAL date_only = DATE_TRUNC(1 days, publish_date)
        | STATS national_avg_price = AVG(product_price) BY date_only
        | SORT date_only ASC
      """
    }
  ```
* **Expected output:** 
  True national daily average fuel price, stripping the forced `10:00:00` timestamp artefact.

### Step 2: Offline Aggregation Script (`aggregate_fuel.py`)
* **Action:**
  See **Backend — Phase 2 Step 1** for the complete execution steps and algorithm.

---

# 3. Elasticsearch — Production Index Reference

This section documents the four production indices currently active in the cluster,
their purpose, schema, and relationship to each other.

## Index Overview

| Index | Shards | Docs | Size | Role |
|-------|--------|------|------|------|
| `fuelwatch-raw-v1` | 3 | 4,378,039 | 1.26 GB | Raw source data |
| `fuel-daily-summary` | 3 | 1,596 | 286 KB | Pre-aggregated fuel baseline |
| `social-posts-v1` | 3 | 72,631 | 144 MB | Harvested social media posts |
| `bluesky-cursors` | — | ~59 | — | Crawler state (internal use only) |

Both `fuelwatch-raw-v1` and `social-posts-v1` are accessed via aliases
(`fuelwatch-raw` and `social-posts` respectively), so harvester write targets
require zero code changes after the 3-shard migration.

---

## `social-posts-v1` (alias: `social-posts`)

**Purpose:** Unified store for all harvested social media posts from Bluesky and
Reddit. Sentiment scoring (VADER) is applied at ingestion time by the harvester functions, so every document already carries a `sentiment_score` float on arrival.

**Key fields:**
| Field | Type | Description |
|-------|------|-------------|
| `created_at` | `date` | Post timestamp (stored in UTC, bucketed in AEST) |
| `platform` | `keyword` | `"bluesky"` or `"reddit"` |
| `text` | `text` | Raw post content |
| `sentiment_score` | `float` | VADER compound score (−1.0 to +1.0) |
| `sentiment_label` | `keyword` | `"positive"`, `"negative"`, `"neutral"` |
| `matched_location` | `keyword` | Inferred Australian city/region |
| `is_au` | `boolean` | Whether post is Australia-related |
| `is_fuel` | `boolean` | Whether post mentions fuel/petrol |
| `is_cost` | `boolean` | Whether post mentions cost of living |
| `subreddit` | `keyword` | Source subreddit (Reddit only) |

**Timezone note:** All `date_histogram` aggregations in the API layer use `time_zone: "Australia/Melbourne"` to ensure posts made after 14:00 AEST are bucketed into the correct local date, not the following UTC day.

**Consumers:** `analytics_service.py` (real-time aggregation for sentiment data).

---

## `fuelwatch-raw-v1` (alias: `fuelwatch-raw`)

**Purpose:** 
Stores every raw station-level fuel price record ingested from the FuelWatch WA API. This is the single source of truth for all fuel price data.

**Key fields:**
| Field | Type | Description |
|-------|------|-------------|
| `publish_date` | `date` | Date of the price record |
| `product_price` | `float` | Fuel price in cents per litre |
| `fuel_type` | `keyword` | e.g. ULP, diesel |
| `state` | `keyword` | Australian state |
| `location` | `geo_point` | Station coordinates |

**Why 3 shards:** 
At 4.37M records and 1.26 GB, a single-shard layout concentrated all read/write load on one node. The 3-shard layout distributes ~1.45M records per shard across both cluster nodes, enabling parallel aggregation.

**Consumers:** `aggregate_fuel.py` (aggregation source), Kibana dashboards.

---

## `fuel-daily-summary`

**Purpose:** 
Pre-aggregated daily national average fuel price, computed from `fuelwatch-raw-v1` by the `daily-aggregator` Fission function. Reduces 4.37M raw records to ~1,596 daily summary rows, enabling O(1) lookups in the API layer.

**Key fields:**
| Field | Type | Description |
|-------|------|-------------|
| `date` | `date` | The calendar date (AEST) |
| `avg_price` | `float` | National average price (cents/litre, rounded to 2dp) |

**Why this exists:** 
Direct aggregation over 4.37M records on every API request would be too slow for a real-time endpoint. This index acts as a materialized view, refreshed nightly by the Timer-triggered `daily-aggregator` at 03:00 UTC.

**Consumers:** 
`analytics_service.py` (primary read source for fuel data in the merged API response).

---

## `bluesky-cursors`

**Purpose:** Internal crawler state store used exclusively by the Bluesky harvester Fission function. Tracks pagination cursors to avoid re-fetching already-ingested posts across timer invocations.

**Key fields:** `cursor_state`, `last_seen_time`, `until`, `finished`.

**Consumers:** Bluesky harvester only. Not read by the API layer or Jupyter frontend.