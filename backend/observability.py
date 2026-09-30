"""Optional Logfire observability (distributed tracing, latency, token cost).

Design goals:
  - **Zero-friction local dev / CI.** If the ``logfire`` package is missing or no
    ``LOGFIRE_TOKEN`` is set, every helper here is a safe no-op — the app runs
    identically, tests never need an account.
  - **Only production exports.** ``configure()`` does nothing unless
    ``YANTRA_ENV=production`` (set in ``backend/fly.toml``) or ``YANTRA_TRACE_LOCAL=1``
    is set explicitly. A ``LOGFIRE_TOKEN`` in a laptop's ``.env`` is therefore not
    enough to send spans, so local runs, tests and evals can never inflate the public
    /ops numbers. Every span is tagged with ``environment=$YANTRA_ENV`` (Logfire's
    ``deployment.environment.name`` resource attribute), which ``metrics.py`` filters on.
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


def yantra_env() -> str:
    """Deployment environment: ``production`` on Fly, ``local`` by default."""
    return (os.environ.get("YANTRA_ENV") or "local").strip().lower()


def export_allowed() -> bool:
    """True only in production, or when a developer opts in with YANTRA_TRACE_LOCAL=1."""
    return yantra_env() == "production" or os.environ.get("YANTRA_TRACE_LOCAL") == "1"


def configure(app=None) -> bool:
    """Configure Logfire once and auto-instrument FastAPI + the Anthropic client.

    Returns True only if telemetry is actually being exported. Skipped entirely (no
    ``logfire.configure``, no instrumentation) unless ``export_allowed()``; spans created
    by ``span()`` then stay local no-ops of an unconfigured Logfire. Uses
    ``send_to_logfire="if-token-present"`` so nothing leaves without ``LOGFIRE_TOKEN``.
    """
    global _configured
    if logfire is None or not export_allowed():
        return False
    if not _configured:
        logfire.configure(
            service_name=os.environ.get("LOGFIRE_SERVICE_NAME", "yantra-chatbot"),
            # logfire>=4 writes this as the resource attribute deployment.environment.name,
            # exposed as the ``deployment_environment`` column in Logfire SQL.
            environment=yantra_env(),
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
    """A span context manager; a no-op ``_NullSpan`` unless ``configure()`` enabled Logfire.

    An unconfigured Logfire creates no spans anyway (and warns on every call), so skip it.
    """
    if logfire is None or not _configured:
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
