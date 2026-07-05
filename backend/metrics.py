"""Public, SAFE aggregate metrics for the "Live Ops" page.

Source of truth is Logfire: we query back the per-request spans emitted by
``observability.py`` and reduce them to a handful of numbers that are safe to show
the whole internet — counts, latency percentiles, cost, guardrail blocks. **No user
text, no IPs, no raw logs** ever leave this module; only aggregates and event *types*.

Durable across the backend's scale-to-zero restarts because the data lives in Logfire,
not in this process. Results are cached briefly so the public page can't hammer the
Logfire query API.

Requires ``LOGFIRE_READ_TOKEN``. Without it, ``get_metrics()`` returns
``{"available": False}`` and the page renders a graceful "warming up" state.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

import httpx

# Logfire read/query API. Defaults to the US region (our read token is pylf_v1_us_…);
# override with LOGFIRE_QUERY_URL for an EU project (https://logfire-eu.pydantic.dev/v1/query).
QUERY_URL = os.environ.get("LOGFIRE_QUERY_URL", "https://logfire-us.pydantic.dev/v1/query")
CACHE_TTL_SEC = float(os.environ.get("METRICS_CACHE_TTL_SEC", "60"))
ROW_LIMIT = int(os.environ.get("METRICS_ROW_LIMIT", "1000"))
FEED_LEN = int(os.environ.get("METRICS_FEED_LEN", "12"))

# Pull the raw per-request spans; we reduce them in Python so we don't depend on any
# particular SQL percentile support in the query engine.
_SQL = (
    "SELECT start_timestamp, attributes "
    "FROM records "
    "WHERE span_name = 'chat_request' "
    "ORDER BY start_timestamp DESC "
    f"LIMIT {ROW_LIMIT}"
)

_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def _pct(sorted_vals: list[float], q: float) -> float:
    """Nearest-rank percentile (q in [0,1]). Returns 0.0 for an empty list."""
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 1)


def _rows_from_response(payload: dict) -> list[dict]:
    """Normalise the query API response into a list of {column: value} dicts.

    Logfire returns a *columnar* shape: ``{"columns": [{"name","datatype","values":
    [...]}, ...]}`` — each column carries its own aligned ``values`` array. We also
    tolerate a row-oriented shape as a fallback so this stays robust to API changes.
    """
    if not isinstance(payload, dict):
        return []
    cols = payload.get("columns")

    # Primary: columnar with per-column value arrays.
    if cols and isinstance(cols[0], dict) and "values" in cols[0]:
        names = [c.get("name") for c in cols]
        value_lists = [c.get("values") or [] for c in cols]
        n = min((len(v) for v in value_lists), default=0)
        return [
            {names[j]: value_lists[j][i] for j in range(len(names))}
            for i in range(n)
        ]

    # Fallback: row-oriented ({"columns":[...], "rows":[[...]|{...}]}).
    rows = payload.get("rows")
    if rows is None:
        return []
    if cols and isinstance(cols[0], dict):
        cols = [c.get("name") for c in cols]
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        elif cols:
            out.append(dict(zip(cols, r)))
    return out


def _attrs(row: dict) -> dict:
    a = row.get("attributes")
    if isinstance(a, str):
        try:
            return json.loads(a)
        except Exception:
            return {}
    return a if isinstance(a, dict) else {}


def _hhmm(ts) -> str:
    """Format an ISO timestamp string to HH:MM (UTC). Best-effort."""
    if not isinstance(ts, str):
        return ""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return ""


def _compute(rows: list[dict]) -> dict:
    latencies: list[float] = []
    costs: list[float] = []
    answered = 0
    blocked = 0
    leaks = 0
    feed: list[dict] = []

    for row in rows:
        a = _attrs(row)
        refused = bool(a.get("refused"))
        if refused:
            blocked += 1
        else:
            answered += 1
        leaks += int(a.get("leak_rate", 0) or 0)

        total_ms = a.get("total_ms")
        if isinstance(total_ms, (int, float)):
            latencies.append(float(total_ms))
        cost = a.get("est_cost_usd")
        if isinstance(cost, (int, float)):
            costs.append(float(cost))

        if len(feed) < FEED_LEN:
            if refused:
                reason = a.get("refuse_reason")
                detail = (
                    "prompt-injection attempt"
                    if reason == "injection"
                    else "strategy-extraction attempt"
                )
                feed.append({"ts": _hhmm(row.get("start_timestamp")), "type": "blocked", "detail": detail})
            else:
                secs = (total_ms / 1000.0) if isinstance(total_ms, (int, float)) else None
                detail = f"{secs:.1f}s" if secs is not None else "answered"
                feed.append({"ts": _hhmm(row.get("start_timestamp")), "type": "answered", "detail": detail})

    lat_sorted = sorted(latencies)
    total_cost = round(sum(costs), 4)
    avg_cost = round(sum(costs) / len(costs), 6) if costs else 0.0

    return {
        "available": True,
        "window": "all-time",
        "queries_served": len(rows),
        "answered": answered,
        "attacks_blocked": blocked,
        "leaks": leaks,
        "p50_ms": _pct(lat_sorted, 0.50),
        "p95_ms": _pct(lat_sorted, 0.95),
        "avg_cost_usd": avg_cost,
        "total_cost_usd": total_cost,
        "recent_events": feed,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _query_logfire(token: str) -> list[dict]:
    resp = httpx.get(
        QUERY_URL,
        params={"sql": _SQL},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return _rows_from_response(resp.json())


def get_metrics() -> dict:
    """Return safe public aggregates, cached for ``CACHE_TTL_SEC``.

    Never raises: on any error (no token, query failure) returns
    ``{"available": False, "reason": ...}`` so the page degrades gracefully.
    """
    now = time.monotonic()
    with _lock:
        if _cache["data"] is not None and now - _cache["at"] < CACHE_TTL_SEC:
            return _cache["data"]

    token = os.environ.get("LOGFIRE_READ_TOKEN")
    if not token:
        return {"available": False, "reason": "metrics not configured"}

    try:
        rows = _query_logfire(token)
        data = _compute(rows)
    except Exception as e:  # network, auth, schema — degrade, don't 500
        return {"available": False, "reason": f"query failed: {type(e).__name__}"}

    with _lock:
        _cache["at"] = time.monotonic()
        _cache["data"] = data
    return data
