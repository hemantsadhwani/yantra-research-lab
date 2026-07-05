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
import threading
import time
from collections import defaultdict, deque
from datetime import date

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import guardrails
from retriever import get_retriever

# --------------------------------------------------------------------------- #
# Config / setup
# --------------------------------------------------------------------------- #
load_dotenv(find_dotenv())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
MODEL = os.environ.get("CHAT_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1024"))
TOP_K = int(os.environ.get("TOP_K", "4"))
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
DAILY_REQUEST_CAP = int(os.environ.get("DAILY_REQUEST_CAP", "500"))

app = FastAPI(title="Yantra Research Lab — RAG Chatbot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Lazy singletons: retriever + Anthropic client
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


_client = None
_client_lock = threading.Lock()


def get_client():
    """Return a cached Anthropic client, or None if no API key is configured."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    return None
                import anthropic

                _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


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
    leak_rate: int = 0


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


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

    # 1. PII redaction — redact before we log or send anything to the model.
    safe_message = guardrails.redact_pii(req.message or "")
    logger.info("chat request ip=%s message=%r", ip, safe_message)

    # 2. Injection detection + 3. IP refusal policy — refuse WITHOUT calling the LLM.
    if guardrails.detect_injection(req.message or "") or guardrails.should_refuse(
        req.message or ""
    ):
        return ChatResponse(
            answer=guardrails.REFUSAL_ANSWER, refused=True, sources=[], leak_rate=0
        )

    # Retrieve methodology context (top-k). Degrade gracefully if the index is missing.
    chunks = []
    try:
        chunks = get_retriever_cached().search(safe_message, k=TOP_K)
    except Exception as e:
        logger.warning("retrieval failed: %s", e)

    sources = [Source(title=c.title, snippet=_snippet(c.text)) for c in chunks]
    context = (
        "\n\n".join(f"[{c.title}]\n{c.text}" for c in chunks)
        if chunks
        else "(no retrieved context)"
    )

    client = get_client()
    if client is None:
        return ChatResponse(
            answer="The assistant is not configured with an API key right now, so I "
            "can't generate a full answer. Set ANTHROPIC_API_KEY and try again.",
            refused=False,
            sources=sources,
            leak_rate=0,
        )

    # Build messages: prior turns + the current (PII-redacted) question with context.
    messages = [
        {"role": h.role, "content": guardrails.redact_pii(h.content)}
        for h in req.history
        if h.role in ("user", "assistant")
    ]
    messages.append(
        {
            "role": "user",
            "content": f"Retrieved methodology context:\n{context}\n\n"
            f"Question: {safe_message}",
        }
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": guardrails.SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # cache the stable prefix
                }
            ],
            messages=messages,
        )
        answer = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not answer:
            answer = "I wasn't able to produce an answer for that. Try rephrasing."
    except Exception as e:  # covers anthropic.APIError, RateLimitError, connection, etc.
        # Never 500 the whole request for an LLM hiccup — return a friendly message.
        logger.warning("LLM call failed: %s", e)
        answer = (
            "I'm having trouble reaching the language model right now. Please try "
            "again in a moment."
        )

    return ChatResponse(answer=answer, refused=False, sources=sources, leak_rate=0)
