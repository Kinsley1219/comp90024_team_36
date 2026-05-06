# FuelWatch Backend Pipeline

## Overview

This module implements the FuelWatch backend ingestion pipeline for the COMP90024 group project.

The pipeline:

```text
FuelWatch WA API
→ Monthly CSV reports
→ Python cleaning & aggregation
→ Elasticsearch indexing
```

The current implementation focuses on:

* Downloading FuelWatch historical retail fuel data
* Filtering ULP (Unleaded Petrol) records
* Aggregating daily average ULP prices
* Writing processed daily records into Elasticsearch

---

# Data Source

Source:

* FuelWatch Western Australia
* API endpoint:

```text
https://www.fuelwatch.wa.gov.au/api/report/monthly-retail-prices
```

The API returns metadata for monthly CSV fuel reports.

Each CSV contains station-level fuel price records.

---

# Processing Logic

## Filtering

The pipeline currently keeps only:

```text
PRODUCT_DESCRIPTION = ULP
```

Other fuel types are ignored.

---

## Daily Aggregation

For each date:

* Sum all ULP prices
* Count the number of valid stations
* Compute daily average ULP price

Formula:

```text
avg_ulp_price = total_price / station_count
```

Malformed rows are skipped automatically.

---

# Elasticsearch Schema

Index name (development):

```text
fuelwatch-dev
```

Example document:

```json
{
  "date": "2022-01-01",
  "avg_ulp_price": 169.0,
  "station_count": 682,
  "source": "FuelWatch WA",
  "fuel_type": "ULP",
  "ingested_at": "2026-05-06T15:33:46Z"
}
```

Document ID:

```text
YYYY-MM-DD
```

Using the date as the document ID prevents duplicate records when the pipeline is rerun.

---

# Project Structure

```text
backend/
└── fuelwatch/
    ├── fuelwatch_fission.py
    ├── requirements.txt
    └── README.md
```

---

# Local Development

## Prerequisites

* WSL2 Ubuntu
* Python 3
* kubectl configured
* Elasticsearch port-forward enabled

---

## Start Elasticsearch Port Forward

```bash
kubectl port-forward -n elastic svc/elasticsearch-es-http 9200:9200
```

---

## Run Locally

```bash
python3 fuelwatch_fission.py
```

---

## Optional Environment Variables

### Limit number of processed monthly files

Useful during testing:

```bash
export MAX_FILES=2
```

---

### Change Elasticsearch index

```bash
export INDEX_NAME="fuelwatch-dev"
```

---

# Current Development Status

Completed:

* FuelWatch API integration
* CSV ingestion
* Daily ULP aggregation
* Elasticsearch bulk indexing
* Local end-to-end testing

Planned:

* Fission package deployment
* Fission function deployment
* Scheduled timer execution
* Kibana visualization
* Integration with social media sentiment analysis

---

# Notes

* pandas is intentionally avoided to reduce Fission build overhead.
* Elasticsearch uses HTTPS with a self-signed certificate.
* The pipeline uses Elasticsearch bulk indexing for efficiency.

---

# Author

COMP90024 Team 36 HK_ZHANG
FuelWatch backend pipeline implementation.

