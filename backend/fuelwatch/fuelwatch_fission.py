import csv
import io
import json
import os
from datetime import datetime
from typing import Dict, List, Any

import requests
import urllib3

# Elasticsearch in the current cluster uses HTTPS with a self-signed certificate.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUELWATCH_MONTHLY_API = "https://www.fuelwatch.wa.gov.au/api/report/monthly-retail-prices"
DEFAULT_INDEX_NAME = "fuelwatch-daily-ulp"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.fuelwatch.wa.gov.au/",
}


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_year_from_filename(file_name: str) -> int | None:
    """Extract the year from names like FuelWatchRetail-05-2026.csv."""
    try:
        return int(file_name.rsplit("-", 1)[-1].replace(".csv", ""))
    except (AttributeError, ValueError):
        return None


def fetch_monthly_reports(start_year: int) -> List[Dict[str, Any]]:
    """Fetch FuelWatch monthly report metadata and keep files from start_year onwards."""
    response = requests.get(FUELWATCH_MONTHLY_API, headers=HEADERS, timeout=30)
    response.raise_for_status()
    reports = response.json()

    selected = []
    for item in reports:
        year = _extract_year_from_filename(item.get("fileName", ""))
        if year is not None and year >= start_year and item.get("url"):
            selected.append(item)

    return selected


def read_monthly_csv(url: str) -> List[Dict[str, str]]:
    """Download one FuelWatch CSV file and return rows as dictionaries."""
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    text = response.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def build_daily_ulp(records: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Aggregate raw FuelWatch records into one daily average ULP price per date."""
    daily: Dict[str, Dict[str, float | int]] = {}

    for row in records:
        if row.get("PRODUCT_DESCRIPTION") != "ULP":
            continue

        raw_date = row.get("PUBLISH_DATE", "").strip()
        raw_price = row.get("PRODUCT_PRICE", "").strip()

        try:
            date_key = datetime.strptime(raw_date, "%d/%m/%Y").strftime("%Y-%m-%d")
            price = float(raw_price)
        except (ValueError, TypeError):
            continue

        if date_key not in daily:
            daily[date_key] = {"sum_price": 0.0, "station_count": 0}

        daily[date_key]["sum_price"] += price
        daily[date_key]["station_count"] += 1

    result = []
    for date_key in sorted(daily):
        count = int(daily[date_key]["station_count"])
        if count == 0:
            continue
        avg_price = round(float(daily[date_key]["sum_price"]) / count, 2)
        result.append({
            "date": date_key,
            "avg_ulp_price": avg_price,
            "station_count": count,
            "source": "FuelWatch WA",
            "fuel_type": "ULP",
            "ingested_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    return result


def bulk_write_to_es(daily_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write daily records to Elasticsearch using stable date-based document IDs."""
    es_host = os.getenv("ES_HOST", "https://localhost:9200").rstrip("/")
    es_user = os.getenv("ES_USER", "elastic")
    es_password = os.getenv("ES_PASSWORD", "elastic")
    index_name = os.getenv("INDEX_NAME", DEFAULT_INDEX_NAME)

    if not daily_records:
        return {"saved": 0, "index": index_name, "errors": False}

    lines = []
    for record in daily_records:
        doc_id = record["date"]
        lines.append(json.dumps({"index": {"_index": index_name, "_id": doc_id}}))
        lines.append(json.dumps(record))

    payload = "\n".join(lines) + "\n"
    response = requests.post(
        f"{es_host}/_bulk",
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        auth=(es_user, es_password),
        verify=False,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    return {
        "saved": len(daily_records),
        "index": index_name,
        "errors": bool(data.get("errors")),
    }


def main() -> str:
    """Fission entrypoint: fetch FuelWatch data, aggregate daily ULP prices, write to ES."""
    start_year = _to_int(os.getenv("START_YEAR", "2022"), 2022)
    max_files = _to_int(os.getenv("MAX_FILES", "0"), 0)  # 0 means all selected files

    try:
        reports = fetch_monthly_reports(start_year=start_year)
        if max_files > 0:
            # Useful for fast Fission testing: only process the newest N selected files.
            reports = reports[:max_files]

        all_records: List[Dict[str, str]] = []
        failed_files = []

        for item in reports:
            try:
                all_records.extend(read_monthly_csv(item["url"]))
            except Exception as exc:  # Keep one bad month from killing the whole run.
                failed_files.append({"fileName": item.get("fileName"), "error": str(exc)})

        daily_records = build_daily_ulp(all_records)
        es_result = bulk_write_to_es(daily_records)

        return json.dumps({
            "status": "ok",
            "start_year": start_year,
            "monthly_files_attempted": len(reports),
            "raw_records_loaded": len(all_records),
            "daily_records": len(daily_records),
            "es": es_result,
            "failed_files": failed_files,
        })

    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": str(exc),
        })
if __name__ == "__main__":
    print(main())
