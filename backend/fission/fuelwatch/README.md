# FuelWatch Backend Pipeline

## Overview

This module implements the complete FuelWatch backend ingestion and aggregation pipeline for the COMP90024 cloud computing group project.

The pipeline provides:

FuelWatch WA API
    ↓
Monthly retail fuel CSV reports
    ↓
Raw ingestion pipeline
    ↓
Elasticsearch raw storage
    ↓
ULP filtering & aggregation
    ↓
Daily analytics dataset

The implementation follows a production-style cloud data engineering architecture with:

- Raw data persistence
- Incremental ingestion
- Historical backfill support
- Elasticsearch bulk indexing
- Serverless execution via Fission
- Automated scheduled updates
- Aggregated analytical datasets

# Data Source

Official FuelWatch WA API:

https://www.fuelwatch.wa.gov.au/

Monthly retail fuel metadata API:

https://www.fuelwatch.wa.gov.au/api/report/monthly-retail-prices

The pipeline dynamically retrieves available monthly CSV reports and processes all files from the configured START_YEAR.

# Data Flow

1. FuelWatch WA monthly metadata API is queried.
2. Monthly CSV report URLs are discovered dynamically.
3. CSV files are downloaded and normalized.
4. Raw records are indexed into Elasticsearch.
5. ULP records are filtered from raw datasets.
6. Daily average ULP prices are aggregated.
7. Aggregated analytics documents are indexed into Elasticsearch.
8. Scheduled Fission timers automate periodic updates.

# Pipeline Architecture

## Stage 1 — Raw Data Ingestion

Function:

fuelwatch-raw

Purpose:

- Download monthly FuelWatch CSV files
- Normalize raw records
- Persist complete raw datasets into Elasticsearch

Target index:

fuelwatch-raw

Characteristics:

- Historical backfill supported
- Incremental ingestion supported
- Retry-safe ingestion
- Stable document IDs
- Elasticsearch bulk indexing

## Incremental Update Strategy

The pipeline supports incremental updates by dynamically discovering newly published monthly FuelWatch CSV reports.

Previously indexed documents are safely overwritten using deterministic Elasticsearch document IDs, allowing the ingestion process to be rerun without generating duplicate records.

This design enables:

- Retry-safe execution
- Incremental historical expansion
- Automated scheduled updates
- Idempotent Elasticsearch ingestion

## Stage 2 — Daily ULP Aggregation

Function:

fuelwatch-dev

Purpose:

- Read FuelWatch raw records
- Filter ULP fuel type
- Aggregate station-level prices into daily average prices
- Generate analytics-ready daily dataset

Target index:

fuelwatch-daily-ulp

ULP was selected as the primary analytical fuel type because it is the most commonly referenced petrol category in Australian consumer fuel price discussions and provides the most stable cross-station daily coverage.

# Elasticsearch Indices

| Index | Purpose |
|---|---|
| fuelwatch-raw | Full raw FuelWatch records |
| fuelwatch-daily-ulp | Aggregated daily ULP analytics dataset |

### Source Data Fields Used

The FuelWatch raw CSV contains multiple fuel product types and station metadata.

For the ULP aggregation pipeline, the following fields are primarily used:

| Field | Purpose |
|---|---|
| PUBLISH_DATE | Aggregation date |
| PRODUCT_DESCRIPTION | Filter for ULP fuel type |
| PRODUCT_PRICE | Daily price aggregation |
| TRADING_NAME | Station counting |

Rows with PRODUCT_DESCRIPTION != "ULP" are excluded from the aggregation process.

# Example Aggregated Document

```json
{
  "date": "2022-01-01",
  "avg_ulp_price": 169.0,
  "station_count": 682,
  "source": "FuelWatch WA",
  "fuel_type": "ULP",
  "ingested_at": "2026-05-06T16:10:25Z"
}
```

Document ID:

```text
date
```

This guarantees deterministic upsert behaviour and prevents duplicate daily records.

The average ULP price is computed as the mean of all ULP station prices published on the same date.

# Environment Variables

| Variable | Description | Default |
|---|---|---|
| ES_HOST | Elasticsearch endpoint | https://localhost:9200 |
| ES_USER | Elasticsearch username | elastic |
| ES_PASSWORD | Elasticsearch password | elastic |
| INDEX_NAME | Aggregated Elasticsearch index | fuelwatch-daily-ulp |
| RAW_INDEX_NAME | Raw Elasticsearch index | fuelwatch-raw |
| START_YEAR | Earliest year to process | 2022 |
| MAX_FILES | Limit monthly files for testing | 1 |
| BULK_BATCH_SIZE | Elasticsearch bulk batch size | 1000 |

# Local Testing

## Test Raw Ingestion

```bash
export ES_HOST="https://localhost:9200"
export ES_USER="elastic"
export ES_PASSWORD="elastic"

export MAX_FILES=1

python3 fuelwatch_raw_ingestion.py
```

## Full Historical Backfill

```bash
unset MAX_FILES

python3 fuelwatch_raw_ingestion.py
```

## Test Daily Aggregation

```bash
python3 fuelwatch_fission.py
```

# Elasticsearch Validation

## Count Raw Records

```bash
curl -k -u elastic:elastic \
"https://localhost:9200/fuelwatch-raw/_count"
```

## Count Aggregated Records

```bash
curl -k -u elastic:elastic \
"https://localhost:9200/fuelwatch-daily-ulp/_count"
```

# Fission Deployment

## Raw Ingestion Function

```bash
fission function create \
  --name fuelwatch-raw \
  --env python39 \
  --pkg fuelwatch-raw-pkg \
  --entrypoint "fuelwatch_raw_ingestion.main"
```

## Aggregation Function

```bash
fission function create \
  --name fuelwatch-dev \
  --env python39 \
  --pkg fuelwatch-dev-pkg \
  --entrypoint "fuelwatch_fission.main"
```

# Automated Scheduled Pipelines

## Raw Data Timer

```bash
fission timer create \
  --name fuelwatch-raw-timer \
  --function fuelwatch-raw \
  --cron "0 */6 * * *"
```

Runs raw ingestion every 6 hours.

## Aggregation Timer

```bash
fission timer create \
  --name fuelwatch-dev-timer \
  --function fuelwatch-dev \
  --cron "30 */6 * * *"
```

Runs aggregation 30 minutes after raw ingestion.

# Scalability Considerations

The pipeline uses Fission poolmgr executor types for scheduled ingestion workloads.

This design is appropriate because the FuelWatch pipeline executes predictable periodic batch jobs rather than burst-oriented user-facing API traffic.

Scheduled execution is handled through Fission timers, while Elasticsearch bulk indexing reduces indexing overhead for large historical backfill operations.

# Engineering Features

The implementation includes several production-oriented engineering improvements:

- Structured logging
- Retry-safe ingestion workflow
- Stable Elasticsearch document IDs
- Elasticsearch bulk indexing
- Incremental ingestion support
- Historical backfill support
- Batch-size optimization
- Error isolation for corrupted monthly files
- Configurable testing controls
- Fission serverless deployment
- Automated scheduled pipelines

# Current Status

The pipeline has been successfully deployed and validated on the shared COMP90024 Kubernetes/Fission environment with Elasticsearch persistence enabled.

Current successful historical backfill results:

| Metric | Value |
|---|---|
| Monthly files processed | 53 |
| Raw records indexed | 4,354,746 |
| Aggregated daily records | 1,586 |
| Failed files | 0 |