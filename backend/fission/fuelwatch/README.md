FuelWatch Backend Pipeline
Overview

This module implements the FuelWatch backend ingestion pipeline for the COMP90024 group project.

The pipeline:

FuelWatch WA API
→ Monthly CSV reports
→ Python cleaning & aggregation
→ Elasticsearch bulk indexing

The current implementation focuses on:

Downloading FuelWatch historical retail fuel data
Filtering ULP (Unleaded Petrol) records
Aggregating station-level prices into daily average prices
Writing processed data into Elasticsearch
Supporting future Fission serverless deployment
Data Source

Source:

https://www.fuelwatch.wa.gov.au/

Monthly retail fuel CSV metadata API:

https://www.fuelwatch.wa.gov.au/api/report/monthly-retail-prices

The pipeline dynamically retrieves available monthly CSV reports and processes data from the configured start year onwards.

Elasticsearch Document Structure

Example indexed document:

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

This guarantees stable upsert behaviour and avoids duplicate records.

Environment Variables
Variable	Description	Default
ES_HOST	Elasticsearch endpoint	https://localhost:9200

ES_USER	Elasticsearch username	elastic
ES_PASSWORD	Elasticsearch password	elastic
INDEX_NAME	Elasticsearch index name	fuelwatch-daily-ulp
START_YEAR	Earliest year to process	2022
MAX_FILES	Limit processed monthly files for testing	0
Local Testing

Run locally:

export INDEX_NAME="fuelwatch-dev"
export MAX_FILES=2

python3 fuelwatch_fission.py

Run full historical ingestion:

unset MAX_FILES
python3 fuelwatch_fission.py
Elasticsearch Validation

Count indexed documents:

curl -k -u elastic:elastic \
"https://localhost:9200/fuelwatch-dev/_count"

Query sample documents:

curl -k -u elastic:elastic \
"https://localhost:9200/fuelwatch-dev/_search?size=3&pretty"
Engineering Features

The current implementation includes several production-style engineering improvements:

Structured logging
Retry-safe ingestion workflow
Stable document IDs
Elasticsearch bulk indexing
Explicit Elasticsearch mappings
Error isolation for corrupted monthly files
Configurable testing controls via environment variables
Current Status

Current successful local test results:

53 monthly files processed
4,344,768 raw records loaded
1,586 aggregated daily records indexed
0 failed files

The pipeline has been validated against the shared COMP90024 Elasticsearch cluster.

Future Work

Planned extensions:

Fission deployment
Scheduled automatic ingestion
Additional fuel type support
Sentiment-analysis integration
Kibana visualization dashboard

Full historical backfill should be run manually once. Fission function is designed for incremental updates using MAX_FILES=1 or 2.
