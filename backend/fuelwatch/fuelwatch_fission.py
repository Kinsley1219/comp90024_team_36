import csv
import io
import json
import os
import time
import urllib3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FUELWATCH_MONTHLY_API = "https://www.fuelwatch.wa.gov.au/api/report/monthly-retail-prices"
DEFAULT_INDEX_NAME = "fuelwatch-daily-ulp"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.fuelwatch.wa.gov.au/",
}


def log(message: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{now}] {message}", flush=True)


def _to_int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _get_env() -> Dict[str, Any]:
    return {
        "start_year": _to_int(os.getenv("START_YEAR"), 2022),
        "max_files": _to_int(os.getenv("MAX_FILES"), 0),
        "es_host": os.getenv("ES_HOST", "https://localhost:9200").rstrip("/"),
        "es_user": os.getenv("ES_USER", "elastic"),
        "es_password": os.getenv("ES_PASSWORD", "elastic"),
        "index_name": os.getenv("INDEX_NAME", DEFAULT_INDEX_NAME),
        "request_timeout": _to_int(os.getenv("REQUEST_TIMEOUT"), 60),
        "es_timeout": _to_int(os.getenv("ES_TIMEOUT"), 120),
        "max_retries": _to_int(os.getenv("MAX_RETRIES"), 3),
        "retry_sleep": _to_int(os.getenv("RETRY_SLEEP"), 2),
    }


def request_with_retry(method: str, url: str, *, max_retries: int, retry_sleep: int, timeout: int, **kwargs: Any) -> requests.Response:
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            log(f"Request failed attempt={attempt}/{max_retries} url={url} error={exc}")
            if attempt < max_retries:
                time.sleep(retry_sleep)
    raise RuntimeError(f"Request failed after {max_retries} attempts: {last_error}")


def extract_year_from_filename(file_name: str) -> Optional[int]:
    try:
        return int(file_name.rsplit("-", 1)[-1].replace(".csv", ""))
    except (AttributeError, ValueError):
        return None


def fetch_monthly_reports(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    log("Fetching FuelWatch monthly report metadata")
    response = request_with_retry(
        "GET", FUELWATCH_MONTHLY_API, headers=HEADERS,
        max_retries=config["max_retries"], retry_sleep=config["retry_sleep"], timeout=config["request_timeout"]
    )
    reports = response.json()
    selected = []
    for item in reports:
        year = extract_year_from_filename(item.get("fileName", ""))
        if year is not None and year >= config["start_year"] and item.get("url"):
            selected.append(item)
    selected = sorted(selected, key=lambda x: x.get("fileName", ""), reverse=True)
    if config["max_files"] > 0:
        selected = selected[: config["max_files"]]
    log(f"Selected {len(selected)} monthly files from start_year={config['start_year']}")
    return selected


def read_monthly_csv(url: str, config: Dict[str, Any]) -> List[Dict[str, str]]:
    response = request_with_retry(
        "GET", url, headers=HEADERS,
        max_retries=config["max_retries"], retry_sleep=config["retry_sleep"], timeout=config["request_timeout"]
    )
    text = response.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def build_daily_ulp(records: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    daily: Dict[str, Dict[str, float | int]] = {}
    skipped_rows = 0
    for row in records:
        if row.get("PRODUCT_DESCRIPTION") != "ULP":
            continue
        raw_date = row.get("PUBLISH_DATE", "").strip()
        raw_price = row.get("PRODUCT_PRICE", "").strip()
        try:
            date_key = datetime.strptime(raw_date, "%d/%m/%Y").strftime("%Y-%m-%d")
            price = float(raw_price)
        except (ValueError, TypeError):
            skipped_rows += 1
            continue
        if date_key not in daily:
            daily[date_key] = {"sum_price": 0.0, "station_count": 0}
        daily[date_key]["sum_price"] = float(daily[date_key]["sum_price"]) + price
        daily[date_key]["station_count"] = int(daily[date_key]["station_count"]) + 1

    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = []
    for date_key in sorted(daily):
        count = int(daily[date_key]["station_count"])
        if count == 0:
            continue
        result.append({
            "date": date_key,
            "avg_ulp_price": round(float(daily[date_key]["sum_price"]) / count, 2),
            "station_count": count,
            "source": "FuelWatch WA",
            "fuel_type": "ULP",
            "ingested_at": ingested_at,
        })
    log(f"Built {len(result)} daily records; skipped_rows={skipped_rows}")
    return result


def ensure_index(config: Dict[str, Any]) -> Dict[str, Any]:
    index_name = config["index_name"]
    es_host = config["es_host"]
    mapping = {
        "mappings": {
            "properties": {
                "date": {"type": "date", "format": "yyyy-MM-dd"},
                "avg_ulp_price": {"type": "float"},
                "station_count": {"type": "integer"},
                "source": {"type": "keyword"},
                "fuel_type": {"type": "keyword"},
                "ingested_at": {"type": "date"},
            }
        }
    }
    response = requests.head(f"{es_host}/{index_name}", auth=(config["es_user"], config["es_password"]), verify=False, timeout=config["es_timeout"])
    if response.status_code == 200:
        log(f"Elasticsearch index already exists: {index_name}")
        return {"created": False, "index": index_name}
    if response.status_code != 404:
        response.raise_for_status()
    log(f"Creating Elasticsearch index: {index_name}")
    create_response = request_with_retry(
        "PUT", f"{es_host}/{index_name}", json=mapping,
        auth=(config["es_user"], config["es_password"]), verify=False,
        max_retries=config["max_retries"], retry_sleep=config["retry_sleep"], timeout=config["es_timeout"]
    )
    return {"created": True, "index": index_name, "status_code": create_response.status_code}


def bulk_write_to_es(daily_records: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
    index_name = config["index_name"]
    if not daily_records:
        return {"saved": 0, "index": index_name, "errors": False}
    ensure_index(config)
    lines = []
    for record in daily_records:
        doc_id = record["date"]
        lines.append(json.dumps({"index": {"_index": index_name, "_id": doc_id}}))
        lines.append(json.dumps(record))
    payload = "\n".join(lines) + "\n"
    log(f"Writing {len(daily_records)} records to Elasticsearch index={index_name}")
    response = request_with_retry(
        "POST", f"{config['es_host']}/_bulk", data=payload.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        auth=(config["es_user"], config["es_password"]), verify=False,
        max_retries=config["max_retries"], retry_sleep=config["retry_sleep"], timeout=config["es_timeout"]
    )
    data = response.json()
    errors = bool(data.get("errors"))
    log("Elasticsearch bulk write completed" + (" with errors" if errors else " successfully"))
    return {"saved": len(daily_records), "index": index_name, "errors": errors}


def main() -> str:
    config = _get_env()
    log(f"Starting FuelWatch pipeline index={config['index_name']} start_year={config['start_year']} max_files={config['max_files']}")
    try:
        reports = fetch_monthly_reports(config)
        all_records: List[Dict[str, str]] = []
        failed_files = []
        for item in reports:
            file_name = item.get("fileName", "unknown")
            try:
                log(f"Reading monthly CSV: {file_name}")
                rows = read_monthly_csv(item["url"], config)
                all_records.extend(rows)
                log(f"Loaded {len(rows)} rows from {file_name}")
            except Exception as exc:
                failed_files.append({"fileName": file_name, "error": str(exc)})
                log(f"Failed to process file={file_name} error={exc}")
        daily_records = build_daily_ulp(all_records)
        es_result = bulk_write_to_es(daily_records, config)
        result = {
            "status": "ok",
            "start_year": config["start_year"],
            "monthly_files_attempted": len(reports),
            "raw_records_loaded": len(all_records),
            "daily_records": len(daily_records),
            "es": es_result,
            "failed_files": failed_files,
        }
        log(f"FuelWatch pipeline finished status=ok daily_records={len(daily_records)}")
        return json.dumps(result)
    except Exception as exc:
        log(f"FuelWatch pipeline failed error={exc}")
        return json.dumps({"status": "error", "error": str(exc)})


if __name__ == "__main__":
    print(main())
