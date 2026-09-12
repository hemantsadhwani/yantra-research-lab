"""Published backtest outputs as a deterministic, keyword-routed context source.

The vector index is good at methodology ("what is a drawdown?") and bad at the thing a
visitor actually asks first: "what's the P&L for the SENSEX expiry?". Embedding search
over eight methodology notes cannot answer that, and the honest-but-useless reply was
"I have no performance data".

So the published figures get their own, non-vector path:

  ``books_corpus/`` (generated markdown, one file per book + an overview + risk gates)
      -> ``load_books``    parse the metadata header, H1 title, and body
      -> ``match_products`` deterministic keyword routing on the ORIGINAL message
      -> ``select_docs``   the routed docs, overview first, capped

Keyword routing rather than retrieval, because "sensex" -> the SENSEX book is a fact, not
a similarity score: it must not miss, and it must be explainable in an interview.

IP boundary (see CLAUDE.md and ADR-0001): these documents carry backtest **outputs**
only — P&L, drawdown, win rate, costs, sizing. Engine parameters, thresholds, and
entry/exit logic are not in the corpus, and questions about them stay refused by
``guardrails.should_refuse`` exactly as before.

Stdlib only, no vector/embedding imports — so this module is unit-testable anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

BOOKS_DIR = Path(__file__).parent / "books_corpus"

# Products with published books. Routing only ever emits these ids, or "all".
PRODUCT_IDS = ("nifty-weekday", "nifty-expiry", "sensex-expiry")
OVERVIEW_PRODUCT = "all"
OVERVIEW_BOOK = "overview"
RISK_GATES_BOOK = "risk-gates"

# The label the system-prompt addendum keys off. Context blocks carrying it are the
# published figures and may be quoted with their disclaimers.
OUTPUTS_MARKER = "(backtest outputs)"

# At most this many book docs are prepended to the LLM context. Four keeps the
# prompt small enough that the vector chunks still fit alongside them.
MAX_DOCS = 4

# Line 1 of every generated file:
#   <!-- product: sensex-expiry | book: sensex-expiry | status: LIVE | as_of: 2026-09-12 -->
_META_RE = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)


@dataclass
class BookDoc:
    """One published-outputs document: its routing metadata, title, and prose body."""

    product: str
    book: str
    status: str
    as_of: str
    title: str
    body: str
    source: str = ""

    def context_block(self) -> str:
        """Render as an LLM context block, labelled so the system prompt can find it.

        The generated titles usually already end in "(backtest outputs)"; don't
        double the marker up when they do.
        """
        title = self.title if OUTPUTS_MARKER in self.title.lower() else (
            f"{self.title} {OUTPUTS_MARKER}"
        )
        return f"[{title}]\n{self.body}"


def _parse_meta(comment_body: str) -> dict[str, str]:
    """Parse ``product: x | book: y | status: LIVE | as_of: 2026-09-12`` into a dict."""
    meta: dict[str, str] = {}
    for field in comment_body.split("|"):
        key, _, value = field.partition(":")
        key = key.strip().lower()
        if key:
            meta[key] = value.strip()
    return meta


def parse_book(text: str, source: str = "") -> BookDoc | None:
    """Parse one generated markdown document. Returns None if it has no metadata header."""
    match = _META_RE.search(text)
    if match is None or match.start() > 0:
        # No leading metadata comment — not a generated book doc; skip it rather than
        # guessing, so a stray note in the folder can never be routed as performance data.
        return None
    meta = _parse_meta(match.group("body"))
    rest = text[match.end() :]

    title = ""
    body_lines: list[str] = []
    for line in rest.splitlines():
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip()

    if not title:
        title = (meta.get("book") or "untitled").replace("-", " ").title()

    return BookDoc(
        product=meta.get("product", ""),
        book=meta.get("book", ""),
        status=meta.get("status", "-"),
        as_of=meta.get("as_of", ""),
        title=title,
        body=body,
        source=source,
    )


def load_books(dir: Path | str = BOOKS_DIR) -> list[BookDoc]:
    """Load every book doc in ``dir``. Missing directory -> [] (the corpus is optional)."""
    folder = Path(dir)
    if not folder.exists():
        return []
    docs: list[BookDoc] = []
    for path in sorted(p for p in folder.rglob("*.md") if p.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        doc = parse_book(text, source=path.name)
        if doc is not None:
            docs.append(doc)
    return docs


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
# Session words that disambiguate which NIFTY product is meant.
_EXPIRY_WORDS = ("expiry", "tuesday", "0dte")
_WEEKDAY_WORDS = ("weekday", "high vix", "low vix", "high-vix", "low-vix", "regime")

# Performance vocabulary. Present without any product name, these route to the
# overview alone — "which strategy made the most money" is a cross-book question.
_PERF_WORDS = (
    "pnl",
    "p&l",
    "p & l",
    "profit",
    "performance",
    "drawdown",
    "draw down",
    "win rate",
    "returns",
    "how did",
    "month on month",
    "month-on-month",
    "monthly",
    "best month",
    "worst month",
    "worst day",
    "best day",
    "which book",
    "which strategy",
    "strategies",
    # Risk/exposure phrasings a visitor uses without naming a product. These are
    # all answerable from the published outputs, so they must route to a book.
    "max loss",
    "maximum loss",
    "worst loss",
    "biggest loss",
    "largest loss",
    "loss per day",
    "per day",
    "daily loss",
    "max drawdown",
    "maximum drawdown",
    "mdd",
    "days up",
    "trades",
    "sessions",
    "how many months",
    "months up",
    "top 5",
    "concentration",
    "sizing",
    "lot size",
    "per leg",
    "slippage",
    "live or paper",
    "paper or live",
)

# Words that pull in the risk-gates doc alongside whatever else matched.
# Textbook phrasings: the visitor wants the concept, not our numbers. "What is a
# drawdown?" is teaching; "what is OUR max drawdown?" is a data question. Without
# this, shared vocabulary ("drawdown", "win rate") dragged book docs into every
# methodology answer.
_DEFINITION_WORDS = (
    "what is a ",
    "what is an ",
    "what's a ",
    "whats a ",
    "what does ",
    "explain ",
    "define ",
    "definition of",
    "how do you calculate",
    "how is ",
    "in general",
    "generally",
    "textbook",
    "concept",
    "why does",
    "why is",
    "difference between",
)

# Markers that make a question about OUR books despite textbook phrasing.
_OURS_WORDS = (
    "your",
    "our",
    "the book",
    "this book",
    "the lab",
    "nifty",
    "sensex",
    "expiry",
    "weekday",
    "live",
    "paper",
)


def _is_definition_question(m: str) -> bool:
    return any(w in m for w in _DEFINITION_WORDS) and not any(w in m for w in _OURS_WORDS)


# Phrases that are about the risk-gate machinery itself, not a book's numbers.
_GATE_TOPIC_WORDS = (
    "risk gate",
    "gate stack",
    "gates",
    "m2m",
    "day gate",
    "daily gate",
    "weekly gate",
    "monthly stop",
    "hard stop",
    "intraday floor",
    "what stops",
    "not save",
    "stop the book",
    "halt",
)

_RISK_WORDS = (
    "gate",
    "stop",
    "halt",
    "drawdown",
    "draw down",
    "risk",
    "max loss",
    "maximum loss",
    "worst loss",
    "loss per day",
    "daily loss",
    "m2m",
    "exposure",
    "capital",
)


def _normalize(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").lower())


def match_products(message: str, history: list[str] | None = None) -> set[str]:
    """Deterministic keyword routing: message -> the product ids it is asking about.

    Runs on the ORIGINAL message, not the PII-redacted one: redaction rewrites digit
    runs, and a question like "sensex expiry 2026" must still route.

    ``history`` carries the earlier turns of the conversation, most recent last. A
    follow-up rarely repeats the product name -- "and the max drawdown?" after three
    turns about SENSEX is still about SENSEX -- so when the current message names no
    product but does ask about performance, the most recent product named in the
    conversation is inherited. Without this the router returned nothing and the answer
    fell through to the methodology index, which is what made follow-ups fail.

    Returns ``{"all"}`` for performance questions with no named product anywhere
    (overview only), and an empty set for pure methodology questions, which the
    vector index handles.
    """
    m = _normalize(message)
    if _is_definition_question(m):
        # Pure methodology: let the vector index answer it.
        return set()
    products: set[str] = set()

    has_expiry = any(w in m for w in _EXPIRY_WORDS)
    has_weekday = any(w in m for w in _WEEKDAY_WORDS)

    if "sensex" in m:
        products.add("sensex-expiry")
    if "nifty" in m:
        if has_expiry:
            products.add("nifty-expiry")
        if has_weekday:
            products.add("nifty-weekday")
        if not has_expiry and not has_weekday:
            # Bare "nifty" is ambiguous — offer both NIFTY products.
            products.update(("nifty-expiry", "nifty-weekday"))
    if not products:
        # No index named. A bare session word still identifies the product(s).
        if has_expiry:
            products.update(("nifty-expiry", "sensex-expiry"))
        if "weekday" in m:
            products.add("nifty-weekday")

    if products:
        return products

    asks_perf = any(w in m for w in _PERF_WORDS)
    # A question about the gate stack itself names no product and no perf word
    # ("what will the gates not save me from?"). It is still answerable from the
    # published risk-gates doc, and must not fall through to the methodology
    # index, which will happily invent a plausible answer.
    if not asks_perf and any(w in m for w in _GATE_TOPIC_WORDS):
        return {OVERVIEW_PRODUCT}
    if asks_perf and history:
        # Inherit from the conversation, most recent turn first.
        for earlier in reversed(history):
            inherited = match_products(earlier)
            inherited.discard(OVERVIEW_PRODUCT)
            if inherited:
                return inherited
    if asks_perf:
        return {OVERVIEW_PRODUCT}
    return set()


def select_docs(
    message: str, docs: list[BookDoc], history: list[str] | None = None
) -> list[BookDoc]:
    """Pick the book docs to prepend as context for ``message``.

    The overview always rides along when anything matched (it carries the cross-book
    totals and the labelling disclaimer), and goes first. ``risk-gates`` joins only for
    risk-flavoured questions. ``history`` lets a follow-up inherit the product under
    discussion. Capped at ``MAX_DOCS``.
    """
    wanted = match_products(message, history)
    if not wanted:
        return []

    m = _normalize(message)
    wants_risk = any(w in m for w in _RISK_WORDS)

    overview = [d for d in docs if d.book == OVERVIEW_BOOK]
    risk_gates = [d for d in docs if d.book == RISK_GATES_BOOK]
    matched = [
        d
        for d in docs
        if d.book not in (OVERVIEW_BOOK, RISK_GATES_BOOK) and d.product in wanted
    ]

    selected = overview[:1]
    if wants_risk:
        selected += risk_gates[:1]
    selected += matched
    return selected[:MAX_DOCS]


# --------------------------------------------------------------------------- #
# System-prompt addendum (concatenated after guardrails.SYSTEM_PROMPT)
# --------------------------------------------------------------------------- #
BOOKS_SYSTEM_ADDENDUM = """Context blocks titled "(backtest outputs)" are the lab's \
PUBLISHED backtest figures for its three products, and you may quote them directly.

5. Always carry the labels with the numbers: they are backtest results with simulated \
fills, P&L is in points summed and not compounded, and LIVE/PAPER is a production \
status, not the source of these figures.
6. Never extrapolate, annualise, compound, or convert these figures into percentage \
returns, and never project them forward.
7. If asked for month-by-month figures and the document says the monthly series is \
pending, say exactly that.
8. How a book decides — the engine, indicators, thresholds, entries, exits — remains \
confidential and is refused as before. Outputs are public; mechanism is not.
"""
