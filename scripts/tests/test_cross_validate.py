"""Tests for scripts/lib/cross_validate.py."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.cross_validate import (
    cross_validate_spot,
    parse_price_from_snippet,
    parse_timestamp_from_snippet,
)


def _ts(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


class TestCrossValidateSpot:
    def test_both_within_5min_prefers_api(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=174.32,
            api_ts=_ts(2),
            google_value=174.40,
            google_ts=_ts(3),
        )
        assert result["source"] == "fmp_with_websearch_check"
        assert result["value"] == 174.32
        assert result["conflict"] is False

    def test_google_newer_small_diff_swaps_silently(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=174.32,
            api_ts=_ts(60),
            google_value=174.50,
            google_ts=_ts(2),
        )
        assert result["source"] == "websearch"
        assert result["value"] == 174.50
        assert result["conflict"] is False

    def test_google_newer_large_diff_flags_conflict(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=174.32,
            api_ts=_ts(60),
            google_value=178.00,
            google_ts=_ts(2),
        )
        assert result["source"] == "websearch"
        assert result["value"] == 178.00
        assert result["conflict"] is True
        assert "2.11%" in result["note"] or "2.1%" in result["note"]

    def test_google_missing_timestamp_discards_google(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=174.32,
            api_ts=_ts(60),
            google_value=174.50,
            google_ts=None,
        )
        assert result["source"] == "fmp"
        assert result["value"] == 174.32
        assert result["conflict"] is False
        assert "sanity_check_skipped" in result["note"]

    def test_api_missing_uses_google(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=None,
            api_ts=None,
            google_value=174.50,
            google_ts=_ts(2),
        )
        assert result["source"] == "websearch"
        assert result["value"] == 174.50

    def test_api_missing_and_google_no_timestamp_returns_none(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=None,
            api_ts=None,
            google_value=174.50,
            google_ts=None,
        )
        assert result["value"] is None
        assert result["source"] == "none"

    def test_both_missing_returns_none(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=None,
            api_ts=None,
            google_value=None,
            google_ts=None,
        )
        assert result["value"] is None
        assert result["source"] == "none"

    def test_api_newer_than_google_keeps_api(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=174.32,
            api_ts=_ts(1),
            google_value=170.00,
            google_ts=_ts(60),
        )
        assert result["source"] == "fmp_with_websearch_check"
        assert result["value"] == 174.32

    def test_zero_division_safe_when_api_value_zero(self):
        result = cross_validate_spot(
            ticker="X",
            metric="price",
            api_value=0.0,
            api_ts=_ts(60),
            google_value=1.0,
            google_ts=_ts(2),
        )
        assert result["source"] == "websearch"
        assert result["conflict"] is True

    def test_invalid_timestamp_string_treated_as_missing(self):
        result = cross_validate_spot(
            ticker="AAPL",
            metric="price",
            api_value=174.32,
            api_ts=_ts(60),
            google_value=174.50,
            google_ts="not-a-timestamp",
        )
        assert result["source"] == "fmp"
        assert "sanity_check_skipped" in result["note"]


class TestParsePriceFromSnippet:
    def test_basic_dollar_price(self):
        snippet = "Apple Inc (AAPL) Stock Price: $174.32 -1.20 (-0.68%)"
        assert parse_price_from_snippet(snippet, "AAPL") == 174.32

    def test_price_with_comma_thousands(self):
        snippet = "Berkshire Hathaway BRK.A trades at $625,450.00 today"
        assert parse_price_from_snippet(snippet, "BRK.A") == 625450.00

    def test_returns_none_when_no_price(self):
        snippet = "Apple Inc reports strong quarterly earnings"
        assert parse_price_from_snippet(snippet, "AAPL") is None

    def test_price_in_first_position(self):
        snippet = "$174.32 USD - AAPL last trade"
        assert parse_price_from_snippet(snippet, "AAPL") == 174.32


class TestParseTimestampFromSnippet:
    def test_as_of_time(self):
        snippet = "AAPL $174.32 as of 10:23 AM EDT"
        ts = parse_timestamp_from_snippet(snippet)
        assert ts is not None

    def test_no_timestamp_returns_none(self):
        snippet = "AAPL trades at $174.32 today"
        assert parse_timestamp_from_snippet(snippet) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
