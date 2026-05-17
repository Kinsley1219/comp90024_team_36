"""
Meaningful unit tests for reddit_harvest.py
Tests core business logic using mocks - no real ES or Reddit connection needed.
COMP90024 Team 36
"""
import sys
import os
from unittest.mock import MagicMock

# Stub out modules that require external services BEFORE importing project code.
# This prevents ImportError when elasticsearch8 / reddit_crawler are not installed.
sys.modules.setdefault("elasticsearch8", MagicMock())
sys.modules.setdefault("reddit_crawler", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "fission", "reddit"))

import reddit_harvest  # noqa: E402  (import after sys.path manipulation is intentional)


# ── read_secret ───────────────────────────────────────────────────────────────

def test_read_secret_falls_back_to_env(monkeypatch):
    """read_secret must return the env var value when the secret file is absent."""
    monkeypatch.setenv("MY_TEST_SECRET_ABC", "from_env")
    assert reddit_harvest.read_secret("MY_TEST_SECRET_ABC") == "from_env"


def test_read_secret_returns_default_when_nothing_set():
    """read_secret must return the supplied default when neither file nor env var exists."""
    result = reddit_harvest.read_secret("DEFINITELY_NOT_SET_XYZ_999", default="fallback")
    assert result == "fallback"


def test_read_secret_returns_none_by_default():
    """read_secret must return None when no default is given and nothing is set."""
    result = reddit_harvest.read_secret("DEFINITELY_NOT_SET_XYZ_999")
    assert result is None


# ── main() result structure ───────────────────────────────────────────────────

def test_main_returns_all_required_keys(monkeypatch):
    """main() must always return a dict that contains every expected summary key."""
    monkeypatch.setattr(reddit_harvest, "collect_reddit_realtime", lambda: [])
    monkeypatch.setattr(reddit_harvest, "get_es", lambda: MagicMock())

    result = reddit_harvest.main()

    assert isinstance(result, dict)
    for key in ("status", "platform", "collected", "saved", "skipped", "errors"):
        assert key in result, f"Key missing from main() result: {key}"


def test_main_platform_is_reddit(monkeypatch):
    """main() result must identify the platform as 'reddit'."""
    monkeypatch.setattr(reddit_harvest, "collect_reddit_realtime", lambda: [])
    monkeypatch.setattr(reddit_harvest, "get_es", lambda: MagicMock())

    result = reddit_harvest.main()
    assert result["platform"] == "reddit"


def test_main_status_is_ok_on_success(monkeypatch):
    """main() must return status='ok' when everything succeeds."""
    monkeypatch.setattr(reddit_harvest, "collect_reddit_realtime", lambda: [])
    monkeypatch.setattr(reddit_harvest, "get_es", lambda: MagicMock())

    result = reddit_harvest.main()
    assert result["status"] == "ok"


# ── main() skip / save logic ──────────────────────────────────────────────────

def test_main_skips_docs_missing_uri(monkeypatch):
    """main() must skip documents that have no 'uri' field."""
    docs = [
        {"uri": "reddit://t3/abc", "created_at": "2024-01-01"},  # valid
        {"title": "no uri here"},                                  # missing uri -> skip
    ]
    monkeypatch.setattr(reddit_harvest, "collect_reddit_realtime", lambda: docs)
    monkeypatch.setattr(reddit_harvest, "get_es", lambda: MagicMock())

    result = reddit_harvest.main()
    assert result["skipped"] == 1
    assert result["saved"] == 1


def test_main_skips_docs_missing_created_at(monkeypatch):
    """main() must skip documents that have no 'created_at' field."""
    docs = [
        {"uri": "reddit://t3/abc", "created_at": "2024-01-01"},  # valid
        {"uri": "reddit://t3/xyz"},                               # missing created_at -> skip
    ]
    monkeypatch.setattr(reddit_harvest, "collect_reddit_realtime", lambda: docs)
    monkeypatch.setattr(reddit_harvest, "get_es", lambda: MagicMock())

    result = reddit_harvest.main()
    assert result["skipped"] == 1
    assert result["saved"] == 1


def test_main_counts_es_write_errors(monkeypatch):
    """main() must record ES write failures in the errors counter."""
    docs = [{"uri": "reddit://t3/fail", "created_at": "2024-01-01"}]
    monkeypatch.setattr(reddit_harvest, "collect_reddit_realtime", lambda: docs)

    mock_es = MagicMock()
    mock_es.index.side_effect = Exception("connection refused")
    monkeypatch.setattr(reddit_harvest, "get_es", lambda: mock_es)

    result = reddit_harvest.main()
    assert result["errors"] == 1
    assert result["saved"] == 0


def test_main_collected_equals_total_docs(monkeypatch):
    """main() 'collected' counter must equal the total number of docs returned by the crawler."""
    docs = [
        {"uri": "reddit://t3/1", "created_at": "2024-01-01"},
        {"uri": "reddit://t3/2", "created_at": "2024-01-02"},
        {"title": "incomplete"},
    ]
    monkeypatch.setattr(reddit_harvest, "collect_reddit_realtime", lambda: docs)
    monkeypatch.setattr(reddit_harvest, "get_es", lambda: MagicMock())

    result = reddit_harvest.main()
    assert result["collected"] == 3
