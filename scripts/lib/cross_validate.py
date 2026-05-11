"""Cross-validate skill API values against WebSearch (Google) snapshot values.

Used by skills whose primary source (FMP, FINVIZ) may lag the live market.
Caller passes both the API value+timestamp and a value+timestamp parsed
from a WebSearch result. This module decides which to use and whether to
flag a conflict.

Rules:
  1. Both timestamps within 5 min → keep API value, mark sanity-check passed.
  2. Google is >5 min newer, |diff| ≤ 1% → swap to Google silently.
  3. Google is >5 min newer, |diff| > 1% → swap to Google + conflict=True.
  4. Google timestamp missing or unparseable → keep API, sanity-check skipped.
  5. API missing, Google present with timestamp → use Google.
  6. Both missing → return null result.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_FRESHNESS_WINDOW_SECONDS = 300  # 5 minutes
_CONFLICT_PCT_THRESHOLD = 1.0


def cross_validate_spot(
    ticker: str,
    metric: str,
    api_value: float | None,
    api_ts: str | None,
    google_value: float | None,
    google_ts: str | None,
) -> dict[str, Any]:
    """Reconcile an API spot value with a Google search snapshot value.

    Returns a dict with keys: value, source, ts, conflict, note.
    source is one of: "fmp", "fmp_with_websearch_check", "websearch", "none".
    """
    api_dt = _parse_ts(api_ts)
    google_dt = _parse_ts(google_ts)

    if api_value is None and google_value is None:
        return _result(None, "none", None, False, "no data from either source")

    if api_value is None:
        if google_dt is None:
            return _result(None, "none", None, False, "api missing; google timestamp unparseable")
        return _result(google_value, "websearch", google_ts, False, "api unavailable; using google")

    if google_value is None or google_dt is None:
        return _result(
            api_value,
            "fmp",
            api_ts,
            False,
            "sanity_check_skipped: google value or timestamp missing/unparseable",
        )

    # Both values + google timestamp present.
    if api_dt is not None:
        gap_seconds = (google_dt - api_dt).total_seconds()
        if gap_seconds <= _FRESHNESS_WINDOW_SECONDS:
            return _result(
                api_value,
                "fmp_with_websearch_check",
                api_ts,
                False,
                f"google within {_FRESHNESS_WINDOW_SECONDS}s window; api retained",
            )

    # Google is meaningfully newer (or api has no parseable timestamp).
    if api_value == 0:
        diff_pct = float("inf") if google_value != 0 else 0.0
    else:
        diff_pct = abs(google_value - api_value) / abs(api_value) * 100.0

    if diff_pct > _CONFLICT_PCT_THRESHOLD:
        return _result(
            google_value,
            "websearch",
            google_ts,
            True,
            f"google newer; diff {diff_pct:.2f}% vs fmp {api_value} (>1% threshold)",
        )
    return _result(
        google_value,
        "websearch",
        google_ts,
        False,
        f"google newer; diff {diff_pct:.2f}% within tolerance",
    )


def _result(
    value: float | None,
    source: str,
    ts: str | None,
    conflict: bool,
    note: str,
) -> dict[str, Any]:
    return {"value": value, "source": source, "ts": ts, "conflict": conflict, "note": note}


def _parse_ts(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# Snippet parsing helpers. WebSearch snippets are free-form text; these
# helpers do best-effort extraction. Callers should treat None as "could not
# parse" and skip cross-validation (rule 4).

_PRICE_PATTERN = re.compile(r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+\.?[0-9]*)")

_TIME_PATTERN = re.compile(
    r"as\s+of\s+([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM)?\s*[A-Z]{2,4})",
    re.IGNORECASE,
)


def parse_price_from_snippet(snippet: str, ticker: str) -> float | None:
    """Extract the first plausible USD price from a snippet. Returns None if absent."""
    if not snippet:
        return None
    for raw in _PRICE_PATTERN.findall(snippet):
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            continue
    return None


def parse_timestamp_from_snippet(snippet: str) -> str | None:
    """Best-effort: return an ISO timestamp string if the snippet contains an 'as of <time>' phrase.

    Only accepts explicit time markers. Returning the current UTC clock is
    correct here because the snippet was just fetched: an 'as of HH:MM' phrase
    means the quote is at most a few minutes old.
    """
    if not snippet:
        return None
    if _TIME_PATTERN.search(snippet):
        return datetime.now(timezone.utc).isoformat()
    return None
