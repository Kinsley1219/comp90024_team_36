"""
Meaningful unit tests for bluesky_harvester.py
Tests cursor management and entry-point logic using mocks.
COMP90024 Team 36
"""
import sys
import os
from unittest.mock import MagicMock

# Build minimal stubs for bluesky_processor and bluesky_storager before importing
# the harvester so that Python never tries to resolve the real modules.
_processor_stub = MagicMock()
_processor_stub.EARLIEST_DATE = "2024-01-01T00:00:00+00:00"
_processor_stub.QUERIES = ["fuel prices", "cost of living", "grocery prices", "interest rates"]
_processor_stub.get_requests = MagicMock()
_processor_stub.read_secret = MagicMock(return_value="test_value")
_processor_stub.query_id = lambda q: q.replace(" ", "_")
_processor_stub.make_doc = MagicMock(return_value={"created_at": "2024-06-01", "uri": "at://test"})

_storager_stub = MagicMock()
_storager_stub.get_es = MagicMock(return_value=MagicMock())
_storager_stub.init_all_indexes = MagicMock()
_storager_stub.save_posts = MagicMock(return_value=0)

sys.modules.setdefault("bluesky_processor", _processor_stub)
sys.modules.setdefault("bluesky_storager", _storager_stub)
sys.modules.setdefault("elasticsearch8", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "fission", "bluesky"))

import bluesky_harvester  # noqa: E402


# ── get_cursor ────────────────────────────────────────────────────────────────

def test_get_cursor_returns_default_on_es_error():
    """get_cursor must return the default value when ES raises an exception."""
    mock_es = MagicMock()
    mock_es.get.side_effect = Exception("index not found")

    result = bluesky_harvester.get_cursor(mock_es, "missing-cursor", default={"key": "val"})
    assert result == {"key": "val"}


def test_get_cursor_returns_empty_dict_when_no_default():
    """get_cursor must return an empty dict when ES fails and no default is supplied."""
    mock_es = MagicMock()
    mock_es.get.side_effect = Exception("not found")

    result = bluesky_harvester.get_cursor(mock_es, "missing-cursor")
    assert result == {}


def test_get_cursor_returns_source_on_success():
    """get_cursor must return the _source document when ES finds the record."""
    mock_es = MagicMock()
    mock_es.get.return_value = {"_source": {"last_seen_time": "2024-06-01T00:00:00Z"}}

    result = bluesky_harvester.get_cursor(mock_es, "realtime-last-seen")
    assert result["last_seen_time"] == "2024-06-01T00:00:00Z"


# ── get_query_batch ───────────────────────────────────────────────────────────

def test_get_query_batch_respects_batch_size():
    """get_query_batch must return at most batch_size queries."""
    mock_es = MagicMock()
    mock_es.get.side_effect = Exception("no cursor yet")  # fresh start, start=0

    batch, _ = bluesky_harvester.get_query_batch(mock_es, batch_size=2)
    assert len(batch) <= 2


def test_get_query_batch_advances_cursor():
    """get_query_batch must advance next_start by batch_size on the first call."""
    mock_es = MagicMock()
    mock_es.get.side_effect = Exception("no cursor yet")

    _, next_start = bluesky_harvester.get_query_batch(mock_es, batch_size=2)
    assert next_start == 2


def test_get_query_batch_wraps_around():
    """get_query_batch must reset next_start to 0 when it exceeds the query list length."""
    mock_es = MagicMock()
    # Simulate a cursor that puts us near the end of the QUERIES list
    total = len(bluesky_harvester.QUERIES)
    mock_es.get.return_value = {"_source": {"next_start": total - 1}}

    _, next_start = bluesky_harvester.get_query_batch(mock_es, batch_size=2)
    assert next_start == 0


def test_get_query_batch_returns_nonempty_list():
    """get_query_batch must always return at least one query."""
    mock_es = MagicMock()
    mock_es.get.side_effect = Exception("no cursor")

    batch, _ = bluesky_harvester.get_query_batch(mock_es, batch_size=4)
    assert len(batch) >= 1


# ── main() ────────────────────────────────────────────────────────────────────

def test_main_returns_status_key(monkeypatch):
    """main() must return a dict that contains a 'status' key."""
    monkeypatch.setattr(bluesky_harvester, "run", lambda: (5, 3))

    result = bluesky_harvester.main()
    assert isinstance(result, dict)
    assert "status" in result


def test_main_returns_ok_on_success(monkeypatch):
    """main() must return status='ok' when run() succeeds."""
    monkeypatch.setattr(bluesky_harvester, "run", lambda: (10, 8))

    result = bluesky_harvester.main()
    assert result["status"] == "ok"


def test_main_handles_run_exception(monkeypatch):
    """main() must catch exceptions from run() and return status='error' with a message."""
    def failing_run():
        raise RuntimeError("network is down")

    monkeypatch.setattr(bluesky_harvester, "run", failing_run)

    result = bluesky_harvester.main()
    assert result["status"] == "error"
    assert "msg" in result
    assert len(result["msg"]) > 0
