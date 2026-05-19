# COMP90024 Team 36 - Fuel Price and Cost-of-Living Sentiment Analytics

## Project Overview

This repository contains Team 36's COMP90024 Assignment 2 project. The project builds a cloud-native data collection and analytics system for analysing Australian fuel prices and cost-of-living sentiment.

The system collects data from three sources:

- Reddit public JSON endpoints and historical archive data
- Bluesky Search Posts API
- FuelWatch WA historical CSV fuel price reports

The collected data is stored in Elasticsearch. Fission serverless functions are used for scheduled data ingestion, backend aggregation, and API access. Jupyter Notebook is used as the frontend analytics and visualisation interface.

## Team Responsibilities

| Member | Main Contribution |
|---|---|
| Xinyao Li | Designed and deployed the Bluesky Fission ingestion pipeline, implemented Elasticsearch integration and cursor tracking, validated ingestion workflows, and produced system architecture and deployment diagrams. |
| Junyao Zhang | Initial Kubernetes cluster setup, kubeconfig sharing, Reddit Fission pipeline, Reddit realtime and historical ingestion |
| Hanyue Li | Elasticsearch and Kibana deployment, storage optimisation, aggregation pipeline, backend analytics API |
| Hongkun Zhang | FuelWatch Fission pipeline, official fuel price processing, Jupyter Notebook visualisation and automation |
| Yichen Sun | GitLab CI/CD support, documentation/background support |

## System Architecture

The project is organised into five main layers:

1. **External data sources**
   - Reddit public JSON endpoints
   - Arctic Shift Reddit archive
   - Bluesky Search Posts API
   - FuelWatch WA monthly fuel price CSV reports

2. **Fission ingestion layer**
   - Reddit harvester functions
   - Bluesky harvester function
   - FuelWatch ingestion and processing functions
   - Timer triggers and HTTP triggers

3. **Elasticsearch and Kibana layer**
   - Social media post storage
   - FuelWatch raw records
   - Fuel summary indices
   - Bluesky crawler state index
   - Kibana inspection and validation

4. **Backend analytics layer**
   - Daily fuel aggregation
   - Fuel and sentiment trend API

5. **Frontend analytics layer**
   - Jupyter Notebook visualisations and analytical workflows using backend API responses.

## Repository Structure

```text
comp90024_team_36/
├── backend/
│   ├── README_Backend.md
│   └── fission/
│       ├── reddit/
│       ├── bluesky/
│       ├── fuelwatch/
│       ├── analytics/
│       └── aggregator/
├── database/
│   ├── README_Elastic.md
│   ├── deployment/
│   ├── mappings/
│   └── queries/
├── frontend/
│   └── notebooks/
├── data/
│   ├── initial_crawler_samples/
│   └── kibana_analytics_samples/
├── docs/
├── llm/
├── test/
├── .gitlab-ci.yml
└── README.md
```

## Documentation Map

Use this root README as the project entry point. Detailed deployment and implementation notes are stored in module-level README files.

| Component | Documentation |
|---|---|
| Reddit Fission pipeline | [backend/fission/reddit/README.md](backend/fission/reddit/README.md) |
| Bluesky Fission pipeline | [backend/fission/bluesky/README_bluesky.md](backend/fission/bluesky/README_bluesky.md) |
| FuelWatch Fission pipeline | [backend/fission/fuelwatch/README.md](backend/fission/fuelwatch/README.md) |
| Elasticsearch and Kibana | [database/README_Elastic.md](database/README_Elastic.md) |
| Backend analytics API | [backend/README_Backend.md](backend/README_Backend.md) |
| Jupyter Notebook frontend | [frontend/notebooks/Frontend_Team36.ipynb](frontend/notebooks/Frontend_Team36.ipynb) |

## Main Components

### Reddit Fission Pipeline

The Reddit pipeline collects Australian fuel price and cost-of-living discussions from selected Australian-related subreddits.

Location: `backend/fission/reddit/`

Main functions:

- `reddit-harvest`
- `reddit-bootstrap`
- `reddit-api`

Main trigger and routes:

- `reddit-timer`: `@every 5m`
- `GET /api/reddit/posts`
- `GET /api/reddit/stats`
- `GET /api/reddit/sentiment`

Reddit records are stored in the shared social media index `social-posts`.

### Bluesky Fission Pipeline

The Bluesky pipeline collects fuel price and cost-of-living related posts using the Bluesky Search Posts API.

Location: `backend/fission/bluesky/`

Main function and package:

- `bluesky-harvester`
- `bluesky-pkg`

Main timer:

- `bluesky-timer`: `@every 2m`

Main Elasticsearch indices:

- `social-posts`
- `bluesky-cursors`

`social-posts` stores processed Bluesky posts. `bluesky-cursors` stores crawler state and cursor progress for repeated timer-triggered executions.

### FuelWatch Fission Pipeline

The FuelWatch pipeline collects official Western Australia fuel price data from FuelWatch monthly CSV reports.

Location: `backend/fission/fuelwatch/`

Main functions:

- `fuelwatch-raw` is the main production ingestion function. 
- `fuelwatch-dev` was used for development and validation of daily ULP processing.

Main timers:

- `fuelwatch-raw-timer`: `0 */6 * * *`
- `fuelwatch-dev-timer`: `30 */6 * * *`

Main Elasticsearch indices:

`fuelwatch-raw` stores raw station-level FuelWatch records.
`fuelwatch-daily-ulp` was used as an intermediate validation dataset during development.
The raw FuelWatch records are later aggregated into `fuel-daily-summary` by the backend aggregation workflow.

### Elasticsearch and Kibana

Elasticsearch and Kibana are deployed on Kubernetes using Elastic Cloud on Kubernetes.

Location: `database/`

Important indices include:

| Index / Alias | Type | Primary Shards | Documents | Used by | Purpose |
|---|---|---:|---:|---|---|
| `bluesky-cursors` | physical index | 1 | 59 | Bluesky harvester | Stores Bluesky crawler cursor state |
| `social-posts` -> `social-posts-v1` | alias → physical index | 3 | 74,150 | Reddit harvester, Bluesky harvester, backend analytics | Shared social media post storage |
| `fuelwatch-raw`-> `fuelwatch-raw-v1` | alias → physical index | 3 | 4,388,076 | FuelWatch raw ingestion, daily aggregator | Raw station-level FuelWatch records |
| `fuelwatch-daily-ulp` | development/validation index | 1 | 1,599 | FuelWatch processing | Intermediate daily ULP validation dataset |
| `fuel-daily-summary` | pre-aggregated analytics index | 3 | 1,599 | Daily aggregator, backend API | Pre-aggregated fuel price summary for `/api/v1/trends` |

Kibana is used to inspect index mappings, document counts, sample records, and ingestion results.

### Backend Analytics API

The backend analytics API combines fuel price summaries with Reddit and Bluesky sentiment aggregations.

Locations:

- `backend/fission/analytics/`
- `backend/fission/aggregator/`

Main functions:

- `daily-aggregator`
- `fuel-sentiment-analytics`

`daily-aggregator` reads raw FuelWatch records from `fuelwatch-raw`
and generates the pre-aggregated `fuel-daily-summary` index
used by the analytics API.

Main endpoint:

- `GET /api/v1/trends`

The API can be accessed through the Fission router using port-forwarding:

```bash
kubectl port-forward service/router -n fission 8888:80
```

After port-forwarding, the endpoint is available at:

```text
http://127.0.0.1:8888/api/v1/trends
```

### Jupyter Notebook Frontend

Location: `frontend/notebooks/Frontend_Team36.ipynb`

The notebook calls the backend analytics API and generates visualisations for:

- fuel price trends
- Reddit and Bluesky sentiment trends
- social media discussion volume
- platform comparison
- fuel price and sentiment trend comparison

## Deployment Summary

The project is deployed on a shared MRC/NeCTAR Kubernetes cluster.

High-level deployment workflow:

1. Configure local Kubernetes access using the shared kubeconfig file.
2. Deploy Elasticsearch and Kibana using ECK.
3. Create the Python 3.9 Fission environment.
4. Configure Kubernetes Secrets such as `es-secret`.
5. Package crawler code and dependencies into Fission packages.
6. Create Fission functions and attach timer or HTTP triggers.
7. Validate ingestion using `fission fn test`, Elasticsearch count queries, and Kibana inspection.
8. Expose backend API routes through the Fission router.
9. Use Jupyter Notebook to consume the backend API and generate visualisations.

Detailed deployment commands are kept in the module-level README files rather than duplicated here.

## Key Ports

| Purpose | Port | Notes |
|---|---:|---|
| Elasticsearch REST API | 9200 | Used for local port-forwarding and ES validation |
| Kibana Web UI | 5601 | Used for Kibana inspection |
| Local FastAPI prototype | 8000 | Used by `backend/api_gateway.py` before Fission migration |
| Final analytics API through Fission router | 8888 | Used for `/api/v1/trends` |
| Reddit API testing through Fission router | 9090 | Used only for Reddit API testing |

## CI/CD

The repository includes a GitLab CI/CD pipeline defined in `.gitlab-ci.yml`.

The pipeline includes:

- linting with `flake8`
- unit testing with `pytest`
- dependency scanning with `pip-audit`
- manual deployment updates for Reddit and Bluesky Fission packages/functions on the `main` branch

The CI/CD pipeline supports code quality checks and partial deployment automation. It does not replace full cloud deployment validation, because Fission runtime behaviour, Kubernetes Secrets, Elasticsearch access, timer triggers, and external APIs still need to be checked in the cluster environment.

## Testing

Tests are stored in `test/`.

Current test files include:

- `test_basic.py`
- `test_reddit_logic.py`
- `test_bluesky_logic.py`

The tests cover basic repository checks and selected Reddit/Bluesky crawler logic.

Cloud deployment validation is performed separately using:

- `fission fn test`
- Fission function logs
- Elasticsearch count queries
- Kibana inspection
- direct API calls through Fission router port-forwarding
- Jupyter Notebook visualisation checks

## Security Notes

Real credentials should not be committed to GitLab.

The deployed functions read Elasticsearch credentials and API credentials from Kubernetes Secrets, mainly `es-secret`.

Before updating a shared Kubernetes Secret, team members should inspect existing fields carefully. Recreating a shared secret can overwrite credentials required by other Fission functions.

## Project Links

GitLab Repository: https://gitlab.unimelb.edu.au/JUNYAOZ5/comp90024_team_36.git 

YouTube Demonstration:  https://youtu.be/It4Hejc5Z8c?si=u53z3XJB4hKNyYt- 

## Project Status

The main ingestion pipelines, Elasticsearch storage layer, backend analytics API, CI/CD checks, and Jupyter Notebook visualisations have been implemented for the COMP90024 Assignment 2 submission.

Future improvements could include:

- broader automated deployment coverage
- queue-based ingestion scaling
- stronger monitoring and alerting
- more advanced NLP models for sentiment and topic analysis
