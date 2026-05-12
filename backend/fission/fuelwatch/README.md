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

# Elasticsearch Indices

| Index | Purpose |
|---|---|
| fuelwatch-raw | Full raw FuelWatch records |
| fuelwatch-daily-ulp | Aggregated daily ULP analytics dataset |

# Example Aggregated Document

{
  "date": "2022-01-01",
  "avg_ulp_price": 169.0,
  "station_count": 682,
  "source": "FuelWatch WA",
  "fuel_type": "ULP",
  "ingested_at": "2026-05-06T16:10:25Z"
}

Document ID:

date

This guarantees deterministic upsert behaviour and prevents duplicate daily records.

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

export ES_HOST="https://localhost:9200"
export ES_USER="elastic"
export ES_PASSWORD="elastic"

export MAX_FILES=1

python3 fuelwatch_raw_ingestion.py

## Full Historical Backfill

unset MAX_FILES

python3 fuelwatch_raw_ingestion.py

## Test Daily Aggregation

python3 fuelwatch_fission.py

# Elasticsearch Validation

## Count Raw Records

curl -k -u elastic:elastic \
"https://localhost:9200/fuelwatch-raw/_count"

## Count Aggregated Records

curl -k -u elastic:elastic \
"https://localhost:9200/fuelwatch-daily-ulp/_count"

# Fission Deployment

## Raw Ingestion Function

fission function create \
  --name fuelwatch-raw \
  --env python39 \
  --pkg fuelwatch-raw-pkg \
  --entrypoint "fuelwatch_raw_ingestion.main"

## Aggregation Function

fission function create \
  --name fuelwatch-dev \
  --env python39 \
  --pkg fuelwatch-dev-pkg \
  --entrypoint "fuelwatch_fission.main"

# Automated Scheduled Pipelines

## Raw Data Timer

fission timer create \
  --name fuelwatch-raw-timer \
  --function fuelwatch-raw \
  --cron "0 2 * * *"

Runs daily incremental raw ingestion.

## Aggregation Timer

fission timer create \
  --name fuelwatch-dev-timer \
  --function fuelwatch-dev \
  --cron "0 3 * * *"

Runs daily aggregation after raw ingestion completes.

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

Successfully validated on the shared COMP90024 Elasticsearch cluster.

Current successful historical backfill results:

| Metric | Value |
|---|---|
| Monthly files processed | 53 |
| Raw records indexed | 4,354,746 |
| Aggregated daily records | 1,586 |
| Failed files | 0 |
