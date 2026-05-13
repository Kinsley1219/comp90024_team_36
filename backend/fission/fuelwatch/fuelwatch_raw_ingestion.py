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
DEFAULT_RAW_INDEX = "fuelwatch-raw"

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


def get_config() -> Dict[str, Any]:
    return {
        "start_year": _to_int(os.getenv("START_YEAR"), 2022),
        "max_files": _to_int(os.getenv("MAX_FILES"), 1),
	"es_host": os.getenv("ES_HOST", "https://elasticsearch-es-http.elastic:9200").rstrip("/"),
        "es_user": os.getenv("ES_USER", "elastic"),
        "es_password": os.getenv("ES_PASSWORD", "elastic"),
        "raw_index": os.getenv("RAW_INDEX_NAME", DEFAULT_RAW_INDEX),
        "request_timeout": _to_int(os.getenv("REQUEST_TIMEOUT"), 60),
        "es_timeout": _to_int(os.getenv("ES_TIMEOUT"), 120),
        "max_retries": _to_int(os.getenv("MAX_RETRIES"), 3),
        "retry_sleep": _to_int(os.getenv("RETRY_SLEEP"), 2),
    }


def request_with_retry(method: str, url: str, *, config: Dict[str, Any], **kwargs: Any) -> requests.Response:
    last_error = None

    for attempt in range(1, config["max_retries"] + 1):
        try:
            response = requests.request(
                method,
                url,
                timeout=config["request_timeout"],
                **kwargs,
            )
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            log(f"Request failed attempt={attempt}/{config['max_retries']} url={url} error={exc}")
            if attempt < config["max_retries"]:
                time.sleep(config["retry_sleep"])

    raise RuntimeError(f"Request failed after {config['max_retries']} attempts: {last_error}")


def extract_year_from_filename(file_name: str) -> Optional[int]:
    try:
        return int(file_name.rsplit("-", 1)[-1].replace(".csv", ""))
    except (AttributeError, ValueError):
        return None

def extract_year_month_from_filename(file_name: str):
    try:
        # FuelWatchRetail-05-2026.csv
        name = file_name.replace(".csv", "")
        parts = name.split("-")
        month = int(parts[-2])
        year = int(parts[-1])
        return year, month
    except Exception:
        return 0, 0

def fetch_monthly_reports(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    log("Fetching FuelWatch monthly report metadata")

    response = request_with_retry(
        "GET",
        FUELWATCH_MONTHLY_API,
        config=config,
        headers=HEADERS,
    )

    reports = response.json()
    selected = []

    for item in reports:
        file_name = item.get("fileName", "")
        year = extract_year_from_filename(file_name)

        if year is not None and year >= config["start_year"] and item.get("url"):
            selected.append(item)

    selected = sorted(selected, key=lambda x: extract_year_month_from_filename(x.get("fileName", "")), reverse=True)

    if config["max_files"] > 0:
        selected = selected[: config["max_files"]]

    log(f"Selected {len(selected)} monthly files from start_year={config['start_year']}")
    return selected


def read_monthly_csv(url: str, config: Dict[str, Any]) -> List[Dict[str, str]]:
    response = request_with_retry(
        "GET",
        url,
        config=config,
        headers=HEADERS,
    )

    text = response.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def parse_float(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except ValueError:
        return None


def parse_int(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(str(value).strip()))
    except ValueError:
        return None


def parse_date(value: str) -> Optional[str]:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        return None


def normalize_raw_record(row: Dict[str, str], file_name: str, ingested_at: str) -> Optional[Dict[str, Any]]:
    publish_date = parse_date(row.get("PUBLISH_DATE", ""))
    price = parse_float(row.get("PRODUCT_PRICE"))

    if publish_date is None or price is None:
        return None

    record = {
        "publish_date": publish_date,
        "trading_name": row.get("TRADING_NAME", "").strip(),
        "brand_description": row.get("BRAND_DESCRIPTION", "").strip(),
        "product_description": row.get("PRODUCT_DESCRIPTION", "").strip(),
        "product_price": price,
        "address": row.get("ADDRESS", "").strip(),
        "location": row.get("LOCATION", "").strip(),
        "postcode": parse_int(row.get("POSTCODE")),
        "latitude": parse_float(row.get("LATITUDE")),
        "longitude": parse_float(row.get("LONGITUDE")),
        "site_features": row.get("SITE_FEATURES", "").strip(),
        "source": "FuelWatch WA",
        "source_file": file_name,
        "ingested_at": ingested_at,
    }

    return record


def ensure_raw_index(config: Dict[str, Any]) -> None:
    index_name = config["raw_index"]
    es_host = config["es_host"]

    mapping = {
        "mappings": {
            "properties": {
                "publish_date": {"type": "date", "format": "yyyy-MM-dd"},
                "trading_name": {"type": "keyword"},
                "brand_description": {"type": "keyword"},
                "product_description": {"type": "keyword"},
                "product_price": {"type": "float"},
                "address": {"type": "text"},
                "location": {"type": "keyword"},
                "postcode": {"type": "integer"},
                "latitude": {"type": "float"},
                "longitude": {"type": "float"},
                "site_features": {"type": "text"},
                "source": {"type": "keyword"},
                "source_file": {"type": "keyword"},
                "ingested_at": {"type": "date"},
            }
        }
    }

    response = requests.head(
        f"{es_host}/{index_name}",
        auth=(config["es_user"], config["es_password"]),
        verify=False,
        timeout=config["es_timeout"],
    )

    if response.status_code == 200:
        log(f"Raw index already exists: {index_name}")
        return

    if response.status_code != 404:
        response.raise_for_status()

    log(f"Creating raw index: {index_name}")

    create_response = requests.put(
        f"{es_host}/{index_name}",
        json=mapping,
        auth=(config["es_user"], config["es_password"]),
        verify=False,
        timeout=config["es_timeout"],
    )
    create_response.raise_for_status()


def make_doc_id(record: Dict[str, Any]) -> str:
    parts = [
        str(record.get("publish_date", "")),
        str(record.get("trading_name", "")),
        str(record.get("address", "")),
        str(record.get("product_description", "")),
        str(record.get("product_price", "")),
    ]
    return "|".join(parts).lower().replace(" ", "_")


def bulk_write_raw(records: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
    batch_size = _to_int(os.getenv("BULK_BATCH_SIZE"), 500)
    total_saved = 0

    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]

        lines = []
        for record in batch:
            doc_id = make_doc_id(record)
            lines.append(json.dumps({"index": {"_index": config["raw_index"], "_id": doc_id}}))
            lines.append(json.dumps(record))

        body = "\n".join(lines) + "\n"

        response = requests.post(
            f"{config['es_host']}/_bulk",
            headers={"Content-Type": "application/x-ndjson"},
            auth=(config["es_user"], config["es_password"]),
            data=body.encode("utf-8"),
            verify=False,
            timeout=config["es_timeout"],
        )
        response.raise_for_status()
        result = response.json()

        if result.get("errors"):
            return {
                "saved": total_saved,
                "errors": True,
                "index": config["raw_index"],
                "message": "Elasticsearch bulk API returned item-level errors",
            }

        total_saved += len(batch)

    return {
        "saved": total_saved,
        "errors": False,
        "index": config["raw_index"],
    }

def main() -> str:
    config = get_config()

    log(
        f"Starting FuelWatch raw ingestion "
        f"index={config['raw_index']} start_year={config['start_year']} max_files={config['max_files']}"
    )

    try:
        reports = fetch_monthly_reports(config)
        ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_raw_records = []
        failed_files = []
        skipped_rows = 0
        raw_rows_loaded = 0

        for item in reports:
            file_name = item.get("fileName", "unknown")

            try:
                log(f"Reading monthly CSV: {file_name}")
                rows = read_monthly_csv(item["url"], config)
                raw_rows_loaded += len(rows)

                normalized = []

                for row in rows:
                    record = normalize_raw_record(row, file_name, ingested_at)
                    if record is None:
                        skipped_rows += 1
                        continue
                    normalized.append(record)

                all_raw_records.extend(normalized)

                log(
                    f"Loaded {len(rows)} rows from {file_name}; "
                    f"normalized={len(normalized)}"
                )

            except Exception as exc:
                failed_files.append({"fileName": file_name, "error": str(exc)})
                log(f"Failed to process file={file_name} error={exc}")

        es_result = bulk_write_raw(all_raw_records, config)

        result = {
            "status": "ok",
            "monthly_files_attempted": len(reports),
            "raw_rows_loaded": raw_rows_loaded,
            "normalized_raw_records": len(all_raw_records),
            "skipped_rows": skipped_rows,
            "es": es_result,
            "failed_files": failed_files,
        }

        log("FuelWatch raw ingestion finished")
        return json.dumps(result)

    except Exception as exc:
        log(f"FuelWatch raw ingestion failed error={exc}")
        return json.dumps({"status": "error", "error": str(exc)})


if __name__ == "__main__":
    print(main())
