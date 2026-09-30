"""FastAPI backend for the public RAG chatbot with dual IP/PII guardrails.

Endpoints:
  GET  /health     -> {"status": "ok"}
  POST /api/chat   -> RAG answer over quant methodology, with guardrails,
                       per-IP rate limiting, and a global daily cap.

Secrets come from the environment only (``python-dotenv`` + ``find_dotenv`` picks up
the repo-root .env in local dev; the platform sets env vars in production).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import date

import books
import guardrails
import metrics as metrics_mod
import observability as obs
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from retriever import get_retriever

try:
    from llm_gateway import get_provider
    from llm_gateway.base import ProviderUnavailable
except ImportError:  # local dev from backend/ without the repo installed: use the sibling
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from llm_gateway import get_provider
    from llm_gateway.base import ProviderUnavailable

# --------------------------------------------------------------------------- #
# Config / setup
# --------------------------------------------------------------------------- #
load_dotenv(find_dotenv())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
# LLM_PROVIDER=anthropic|bedrock|ollama and LLM_MODEL pick the model (see llm_gateway).
# CHAT_MODEL is the pre-gateway name, still honoured for the anthropic provider.
LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
MODEL = os.environ.get("LLM_MODEL") or (
    os.environ.get("CHAT_MODEL") if LLM_PROVIDER == "anthropic" else None
)
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1024"))
TOP_K = int(os.environ.get("TOP_K", "4"))
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
DAILY_REQUEST_CAP = int(os.environ.get("DAILY_REQUEST_CAP", "500"))


def output_filter_enabled() -> bool:
    """The output filter is on unless ``YANTRA_OUTPUT_FILTER=0``.

    Read per request (not at import) so the red-team eval can measure the leak rate
    with the filter off in the same process. Off exists only for that comparison.
    """
    return os.environ.get("YANTRA_OUTPUT_FILTER", "1").strip() != "0"

app = FastAPI(title="Yantra Research Lab — RAG Chatbot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Observability: traces every request + the LLM call. No-op without LOGFIRE_TOKEN.
_LOGFIRE_ACTIVE = obs.configure(app)
logger.info("logfire active=%s", _LOGFIRE_ACTIVE)

# Cold-start flag: True until the first request finishes. On a scale-to-zero host the
# first request after a wake pays the model/index warm-up cost — worth seeing in traces.
_first_request_done = False
_first_lock = threading.Lock()


def _take_cold_start() -> bool:
    global _first_request_done
    if _first_request_done:
        return False
    with _first_lock:
        if _first_request_done:
            return False
        _first_request_done = True
        return True


# --------------------------------------------------------------------------- #
# Lazy singletons: retriever + LLM provider
# --------------------------------------------------------------------------- #
_retriever = None
_retriever_lock = threading.Lock()


def get_retriever_cached():
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                r = get_retriever()
                try:
                    r.load()  # no-op for Qdrant (opens on init)
                except Exception as e:  # index may not be built yet
                    logger.warning("Retriever load failed (run ingest.py?): %s", e)
                _retriever = r
    return _retriever


_books: list[books.BookDoc] | None = None
_books_lock = threading.Lock()


def get_books_cached() -> list[books.BookDoc]:
    """Load the published-outputs corpus once per process (it is small and static)."""
    global _books
    if _books is None:
        with _books_lock:
            if _books is None:
                try:
                    _books = books.load_books()
                except Exception as e:  # an unreadable corpus must not break chat
                    logger.warning("books corpus load failed: %s", e)
                    _books = []
                logger.info("books corpus loaded docs=%d", len(_books))
    return _books


_provider = None
_provider_lock = threading.Lock()


def get_llm_provider():
    """Return the cached ``llm_gateway`` provider (built once; no network until a call).

    Tests monkeypatch ``app.get_provider`` (the gateway factory) to inject a fake.
    """
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = get_provider(LLM_PROVIDER, model=MODEL)
    return _provider


def _provider_labels() -> dict:
    """``{"provider": ..., "model": ...}`` for spans and /api/metrics; never raises."""
    try:
        p = get_llm_provider()
        return {"provider": p.name, "model": p.model}
    except Exception:  # noqa: BLE001 - misconfigured provider: still serve metrics
        return {"provider": LLM_PROVIDER, "model": MODEL or "default"}


# --------------------------------------------------------------------------- #
# Rate limiting + daily cap (in-memory)
# --------------------------------------------------------------------------- #
_hits: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()
_daily = {"date": date.today(), "count": 0}
_daily_lock = threading.Lock()


def _check_rate_limit(ip: str) -> bool:
    """True if the request is allowed; False if the per-IP minute limit is exceeded."""
    now = time.monotonic()
    with _rate_lock:
        dq = _hits[ip]
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_PER_MIN:
            return False
        dq.append(now)
        return True


def _check_daily_cap() -> bool:
    """True if under the global daily cap (and increments); False if exceeded."""
    with _daily_lock:
        today = date.today()
        if _daily["date"] != today:
            _daily["date"] = today
            _daily["count"] = 0
        if _daily["count"] >= DAILY_REQUEST_CAP:
            return False
        _daily["count"] += 1
        return True


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class HistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryItem] = Field(default_factory=list)


class Source(BaseModel):
    title: str
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    refused: bool = False
    sources: list[Source] = Field(default_factory=list)
    # True when the model DID answer but the output filter replaced the answer with
    # the refusal (parameter disclosure / PII echo / system-prompt echo).
    output_filtered: bool = False
    refuse_reason: str | None = None


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/metrics")
def api_metrics():
    """Public, safe aggregate telemetry for the 'Live Ops' page (cached ~60s).

    Returns only counts / latency percentiles / cost / guardrail blocks queried back
    from Logfire — never user text, IPs, or raw logs. Degrades to {available:false}.
    ``llm`` names the configured provider/model (config, not telemetry).
    ``since_boot`` holds in-process guardrail counters (attacks_blocked,
    output_filtered) that work without Logfire and reset on restart.
    """
    return {**metrics_mod.get_metrics(), "llm": _provider_labels(),
            "since_boot": metrics_mod.since_boot()}


def _snippet(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    ip = request.client.host if request.client else "unknown"

    # Cost/abuse controls first.
    if not _check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please slow down and try again "
                     "in a minute."},
        )
    if not _check_daily_cap():
        return JSONResponse(
            status_code=429,
            content={"detail": "The service has reached its daily request cap. "
                     "Please try again tomorrow."},
        )

    t0 = time.monotonic()
    cold_start = _take_cold_start()
    message = req.message or ""

    # One span per request. Attributes are safe aggregates only — NEVER the user's
    # text (PII / injection payloads). These feed the private dashboard + public stats.
    with obs.span("chat_request") as sp:
        attrs: dict = {
            "cold_start": cold_start,
            "msg_chars": len(message),
            **_provider_labels(),
            "refused": False,
            "output_filtered": False,
        }

        # 1. PII redaction — redact before we log or send anything to the model.
        safe_message = guardrails.redact_pii(message)
        logger.info("chat request ip=%s message=%r", ip, safe_message)

        # 2. Injection detection + 3. IP refusal policy — refuse WITHOUT calling the LLM.
        injection = guardrails.detect_injection(message)
        if injection or guardrails.should_refuse(message):
            attrs.update(
                refused=True,
                refuse_reason="injection" if injection else "policy",
                injection_detected=injection,
                total_ms=round((time.monotonic() - t0) * 1000, 1),
            )
            obs.set_attributes(sp, attrs)
            metrics_mod.record("attacks_blocked")
            return ChatResponse(
                answer=guardrails.REFUSAL_ANSWER, refused=True, sources=[],
                refuse_reason=attrs["refuse_reason"],
            )

        # Retrieve methodology context (top-k). Degrade gracefully if index is missing.
        chunks = []
        with obs.span("retrieve") as rsp:
            r0 = time.monotonic()
            try:
                chunks = get_retriever_cached().search(safe_message, k=TOP_K)
            except Exception as e:
                logger.warning("retrieval failed: %s", e)
            retrieve_ms = round((time.monotonic() - r0) * 1000, 1)
            # Which collections the hits came from, e.g. {"methodology": 3,
            # "research_corpus": 1} - the trace shows whether papers were served.
            per_collection: dict[str, int] = {}
            for c in chunks:
                per_collection[c.collection or "?"] = per_collection.get(c.collection or "?", 0) + 1
            obs.set_attributes(
                rsp,
                {"retrieved_k": len(chunks), "retrieve_ms": retrieve_ms,
                 "collections": per_collection},
            )
        attrs.update(retrieved_k=len(chunks), retrieve_ms=retrieve_ms, collections=per_collection)

        # Published backtest outputs: deterministic keyword routing on the ORIGINAL
        # message (redaction rewrites digit runs), prepended ahead of the vector chunks
        # so the figures lead the context. Outputs only — mechanism stays refused.
        # Prior turns let a follow-up ("and the max drawdown?") inherit the book
        # under discussion; without it the router saw no product and returned
        # nothing, dropping the question onto the methodology index.
        prior = [h.content for h in req.history if h.role == "user"]
        selected = books.select_docs(message, get_books_cached(), prior)
        selected_titles = {d.title for d in selected}
        attrs["book_docs"] = len(selected)

        book_blocks = [d.context_block() for d in selected]
        chunk_blocks = [
            f"[{c.title}]\n{c.text}" for c in chunks if c.title not in selected_titles
        ]

        sources = [Source(title=d.title, snippet=_snippet(d.body)) for d in selected] + [
            Source(title=c.title, snippet=_snippet(c.text))
            for c in chunks
            if c.title not in selected_titles
        ]
        blocks = book_blocks + chunk_blocks
        context = "\n\n".join(blocks) if blocks else "(no retrieved context)"

        def not_configured() -> ChatResponse:
            attrs.update(
                llm_configured=False,
                total_ms=round((time.monotonic() - t0) * 1000, 1),
            )
            obs.set_attributes(sp, attrs)
            return ChatResponse(
                answer="The assistant is not configured with an API key right now, so I "
                "can't generate a full answer. Set ANTHROPIC_API_KEY and try again.",
                refused=False,
                sources=sources,
            )

        try:
            provider = get_llm_provider()
        except (ProviderUnavailable, ValueError) as e:
            logger.warning("LLM provider not configured: %s", e)
            return not_configured()

        # Build messages: prior turns + the current (PII-redacted) question with context.
        messages = [
            {"role": h.role, "content": guardrails.redact_pii(h.content)}
            for h in req.history
            if h.role in ("user", "assistant")
        ]
        messages.append(
            {
                "role": "user",
                "content": f"Retrieved context (methodology and, where relevant, "
                f"published backtest outputs):\n{context}\n\n"
                f"Question: {safe_message}",
            }
        )

        answer = ""
        with obs.span("llm") as lsp:
            l0 = time.monotonic()
            try:
                resp = provider.complete(
                    system=guardrails.SYSTEM_PROMPT + "\n\n" + books.BOOKS_SYSTEM_ADDENDUM,
                    messages=messages,
                    max_tokens=MAX_TOKENS,
                    cache_system=True,  # cache the stable prefix
                )
                answer = resp.text.strip()
                if not answer:
                    answer = "I wasn't able to produce an answer for that. Try rephrasing."
                tokens = {
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                    "cache_write_tokens": resp.cache_write_tokens,
                    "cache_read_tokens": resp.cache_read_tokens,
                }
                cost = round(resp.cost_usd, 6)
                attrs.update(tokens, est_cost_usd=cost)
                obs.set_attributes(
                    lsp, {**tokens, "est_cost_usd": cost,
                          "provider": resp.provider, "model": resp.model}
                )
            except ProviderUnavailable as e:  # no key / no AWS creds / Ollama down
                logger.warning("LLM provider unavailable: %s", e)
                return not_configured()
            except Exception as e:  # API error, rate limit, connection, etc.
                # Never 500 the whole request for an LLM hiccup — friendly message.
                logger.warning("LLM call failed: %s", e)
                answer = (
                    "I'm having trouble reaching the language model right now. Please "
                    "try again in a moment."
                )
                attrs["llm_error"] = True
            llm_ms = round((time.monotonic() - l0) * 1000, 1)
            obs.set_attributes(lsp, {"llm_ms": llm_ms})
        attrs["llm_ms"] = llm_ms

        # 4. Output filter — the model answered; check what it said before the user
        # sees it. A prompt that slipped past the input guardrails still cannot carry
        # parameters, echoed PII, or the system prompt out.
        ok, reason = guardrails.check_output(answer)
        if not ok:
            attrs["output_filter_reason"] = reason
            if output_filter_enabled():
                logger.warning("output filter blocked an answer reason=%s", reason)
                attrs.update(refused=True, refuse_reason="output_filter",
                             output_filtered=True,
                             total_ms=round((time.monotonic() - t0) * 1000, 1))
                obs.set_attributes(sp, attrs)
                metrics_mod.record("attacks_blocked")
                metrics_mod.record("output_filtered")
                return ChatResponse(
                    answer=guardrails.REFUSAL_ANSWER, refused=True, sources=[],
                    output_filtered=True, refuse_reason="output_filter",
                )
            logger.warning("output filter DISABLED; passing flagged answer reason=%s", reason)

        attrs["total_ms"] = round((time.monotonic() - t0) * 1000, 1)
        obs.set_attributes(sp, attrs)
        return ChatResponse(answer=answer, refused=False, sources=sources)
