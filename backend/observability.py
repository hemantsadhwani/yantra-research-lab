"""Optional Logfire observability (distributed tracing, latency, token cost).

Design goals:
  - **Zero-friction local dev / CI.** If the ``logfire`` package is missing or no
    ``LOGFIRE_TOKEN`` is set, every helper here is a safe no-op — the app runs
    identically, tests never need an account.
  - **One import surface.** ``app.py`` calls ``configure(app)`` once at startup and
    wraps request work in ``span(...)`` / ``set_attributes(...)``; nothing else needs
    to know whether Logfire is active.

The same per-request telemetry produced here powers two things: the private Logfire
dashboard (deep traces + alerts) and, later, the public "Live Ops" page (safe
aggregates queried back from Logfire's API).
"""

from __future__ import annotations

import os

# Anthropic pricing, USD per million tokens. Defaults are Claude Haiku 4.5 list
# prices; override via env if pricing or model changes. Cache reads/writes are
# billed differently, so we track them separately for an honest cost estimate.
PRICE_INPUT_PER_MTOK = float(os.environ.get("PRICE_INPUT_PER_MTOK", "1.0"))
PRICE_OUTPUT_PER_MTOK = float(os.environ.get("PRICE_OUTPUT_PER_MTOK", "5.0"))
PRICE_CACHE_WRITE_PER_MTOK = float(os.environ.get("PRICE_CACHE_WRITE_PER_MTOK", "1.25"))
PRICE_CACHE_READ_PER_MTOK = float(os.environ.get("PRICE_CACHE_READ_PER_MTOK", "0.10"))

try:
    import logfire
except ImportError:  # package not installed → everything degrades to no-ops
    logfire = None

_configured = False


def configure(app=None) -> bool:
    """Configure Logfire once and auto-instrument FastAPI + the Anthropic client.

    Returns True only if telemetry is actually being exported (i.e. a token is set).
    Uses ``send_to_logfire="if-token-present"`` so spans are created cheaply in dev
    but nothing leaves the process without ``LOGFIRE_TOKEN``.
    """
    global _configured
    if logfire is None:
        return False
    if not _configured:
        logfire.configure(
            service_name=os.environ.get("LOGFIRE_SERVICE_NAME", "yantra-chatbot"),
            environment=os.environ.get("LOGFIRE_ENVIRONMENT", "production"),
            send_to_logfire="if-token-present",
            console=False,  # keep the app's own stdout clean
        )
        _configured = True
    if app is not None:
        try:
            # capture_headers=False → never record request headers (avoid leaking IPs).
            logfire.instrument_fastapi(app, capture_headers=False)
        except Exception:
            pass
    try:
        logfire.instrument_anthropic()  # auto-span every messages.create with token usage
    except Exception:
        pass
    return bool(os.environ.get("LOGFIRE_TOKEN"))


class _NullSpan:
    """Stand-in span used when Logfire isn't installed. Swallows everything."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_attribute(self, *a, **k):
        pass

    def set_attributes(self, *a, **k):
        pass


def span(name: str, **attrs):
    """A span context manager; a no-op ``_NullSpan`` when Logfire isn't installed."""
    if logfire is None:
        return _NullSpan()
    return logfire.span(name, **attrs)


def set_attributes(span_obj, attrs: dict) -> None:
    """Attach a dict of attributes to a span, tolerating the no-op span."""
    if span_obj is None:
        return
    try:
        span_obj.set_attributes(attrs)
    except Exception:
        pass


def usage_tokens(usage) -> dict:
    """Extract token counts from an Anthropic ``usage`` object into a flat dict."""
    def g(name: str) -> int:
        return int(getattr(usage, name, 0) or 0) if usage is not None else 0

    return {
        "input_tokens": g("input_tokens"),
        "output_tokens": g("output_tokens"),
        "cache_write_tokens": g("cache_creation_input_tokens"),
        "cache_read_tokens": g("cache_read_input_tokens"),
    }


def estimate_cost_usd(usage) -> float:
    """Estimate the USD cost of one Anthropic call, accounting for prompt caching."""
    t = usage_tokens(usage)
    cost = (
        t["input_tokens"] * PRICE_INPUT_PER_MTOK
        + t["output_tokens"] * PRICE_OUTPUT_PER_MTOK
        + t["cache_write_tokens"] * PRICE_CACHE_WRITE_PER_MTOK
        + t["cache_read_tokens"] * PRICE_CACHE_READ_PER_MTOK
    ) / 1_000_000
    return round(cost, 6)
