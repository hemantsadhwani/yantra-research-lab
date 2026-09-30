"""Optional Logfire tracing for the research graph: one span per node, with tokens and cost.

Mirrors ``backend/observability.py``:

* **No token → no-op.** ``configure()`` only calls ``logfire.configure`` when
  ``LOGFIRE_TOKEN`` is set; otherwise every helper here is a null span and nothing
  leaves the process (no network, no console noise). ``logfire`` is imported lazily
  inside a ``try`` so this module imports without it installed.
* **One decorator.** ``traced("propose")`` wraps a node function in a ``node.propose``
  span and, after the node returns, copies the numbers from its state update onto the
  span: iteration, n_variants, engine, provider, model, llm_calls, llm_failures,
  input/output tokens, llm_cost_usd, spent_usd, stop_reason.
* **Privacy by default.** Proposal rationales and parameter values are never span
  attributes unless ``YANTRA_TRACE_PARAMS=1``.

Only the graph arm (``graph.py`` / ``run_graph.py``) uses this; the stdlib path
(``run.py``, ``supervisor.py``) never imports it, so it never imports logfire.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
from collections.abc import Callable
from typing import Any

_logfire: Any = None     # the configured logfire module, or None (→ no-ops)

# Node-update keys copied onto the span, as ``span attribute ← update key``.
_UPDATE_ATTRS = {
    "iteration": "iteration",
    "llm_calls": "llm_calls",
    "llm_failures": "llm_failures",
    "llm_cost_usd": "llm_cost_usd",
    "input_tokens": "llm_input_tokens",
    "output_tokens": "llm_output_tokens",
    "provider": "llm_provider",
    "model": "llm_model",
    "stop_reason": "stop_reason",
    "budget_exhausted_at_iteration": "budget_exhausted_at_iteration",
}

# Control-flow exceptions LangGraph raises through a node (``interrupt()``): not errors.
_CONTROL_FLOW = {"GraphInterrupt", "NodeInterrupt", "ParentCommand"}


def _import_logfire() -> Any:
    try:
        import logfire
    except ImportError:          # not installed (or blocked) → everything is a no-op
        return None
    return logfire


def configure(service_name: str = "yantra-research") -> bool:
    """Turn tracing on iff ``logfire`` is importable AND ``LOGFIRE_TOKEN`` is set.

    Returns True when spans are being exported. Idempotent.
    """
    global _logfire
    if _logfire is not None:
        return True
    if not os.environ.get("LOGFIRE_TOKEN"):
        return False
    logfire = _import_logfire()
    if logfire is None:
        return False
    try:
        logfire.configure(
            service_name=os.environ.get("LOGFIRE_SERVICE_NAME", service_name),
            environment=os.environ.get("LOGFIRE_ENVIRONMENT", "development"),
            send_to_logfire="if-token-present",
            console=False,       # the CLI's own stdout stays clean
        )
    except Exception:  # noqa: BLE001 - telemetry must never break a run
        return False
    with contextlib.suppress(Exception):
        logfire.instrument_anthropic()   # per-call spans with token usage
    _logfire = logfire
    return True


def enabled() -> bool:
    return _logfire is not None


class _NullSpan:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_attribute(self, *a, **k):
        pass

    def set_attributes(self, *a, **k):
        pass


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in attrs.items() if v is not None}


def span(name: str, **attrs: Any):
    """A span context manager; a ``_NullSpan`` unless ``configure()`` enabled tracing."""
    if _logfire is None:
        return _NullSpan()
    return _logfire.span(name, **_clean(attrs))


def set_attributes(span_obj: Any = None, attrs: dict[str, Any] | None = None,
                   **kw: Any) -> None:
    """Attach attributes to a span, tolerating the null span and telemetry errors."""
    if span_obj is None:
        return
    with contextlib.suppress(Exception):
        span_obj.set_attributes(_clean({**(attrs or {}), **kw}))


def trace_params() -> bool:
    return os.environ.get("YANTRA_TRACE_PARAMS") == "1"


def node_attributes(state: dict[str, Any], update: dict[str, Any] | None) -> dict[str, Any]:
    """The span attributes for one node, from its input state and returned update."""
    update = update or {}
    attrs: dict[str, Any] = {"engine": state.get("engine")}
    for attr, key in _UPDATE_ATTRS.items():
        if key in update:
            attrs[attr] = update[key]
    if "proposals" in update:
        attrs["n_variants"] = len(update["proposals"])
        if trace_params():    # opt-in: rationales / params can be sensitive
            attrs["proposals"] = json.dumps(
                [{"id": p.get("id"), "params": p.get("params"),
                  "rationale": p.get("rationale")} for p in update["proposals"]])
    if isinstance(update.get("budget"), dict):
        attrs["spent_usd"] = update["budget"].get("spent_usd")
    return _clean(attrs)


def traced(name: str) -> Callable:
    """Decorate a graph node: run it inside a ``node.<name>`` span, then tag the span."""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            if _logfire is None:
                return fn(state, *args, **kwargs)
            cm = span(f"node.{name}", node=name, iteration=state.get("iteration", 0))
            sp = cm.__enter__()
            try:
                update = fn(state, *args, **kwargs)
            except BaseException as e:
                if type(e).__name__ in _CONTROL_FLOW:
                    # interrupt() pauses the graph; close the span cleanly, not as an error.
                    set_attributes(sp, interrupted=True)
                    cm.__exit__(None, None, None)
                else:
                    cm.__exit__(type(e), e, e.__traceback__)
                raise
            set_attributes(sp, node_attributes(state, update if isinstance(update, dict)
                                               else None))
            cm.__exit__(None, None, None)
            return update
        return wrapper
    return deco
