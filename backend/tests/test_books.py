"""Unit tests for the published-outputs routing — no API key, network, or vector deps.

``books`` is stdlib-only by design, so these run on a bare interpreter. The last block
is a regression guard against ``guardrails``: publishing outputs must not require
loosening the IP refusal policy, so benign performance questions have to pass
``should_refuse`` unchanged while mechanism questions still trip it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import books
import guardrails
import pytest

HEADER = "<!-- product: {product} | book: {book} | status: {status} | as_of: 2026-09-12 -->"


def _write(dirpath, name, product, book, status="LIVE", title=None, body="Body text."):
    title = title or book.replace("-", " ").title()
    text = (
        HEADER.format(product=product, book=book, status=status)
        + f"\n# {title}\n\n{body}\n"
    )
    path = dirpath / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def corpus(tmp_path):
    """A minimal stand-in for backend/books_corpus/ — never written into the repo."""
    d = tmp_path / "books_corpus"
    d.mkdir()
    _write(d, "00-overview.md", "all", "overview", status="-", title="Published books overview")
    _write(d, "risk-gates.md", "all", "risk-gates", status="-", title="Risk gates")
    _write(d, "nifty-weekday-high-vix.md", "nifty-weekday", "nifty-weekday-high-vix")
    _write(d, "nifty-weekday-low-vix.md", "nifty-weekday", "nifty-weekday-low-vix")
    _write(d, "nifty-weekday-r1s1.md", "nifty-weekday", "nifty-weekday-r1s1", status="PAPER")
    _write(d, "nifty-expiry-high-vix.md", "nifty-expiry", "nifty-expiry-high-vix")
    _write(d, "sensex-expiry.md", "sensex-expiry", "sensex-expiry", title="SENSEX expiry book")
    return d


# --- routing -----------------------------------------------------------------
def test_route_sensex_expiry():
    assert books.match_products("can you tell me the pnl for the sensex expiry?") == {
        "sensex-expiry"
    }


def test_route_nifty_expiry():
    assert books.match_products("how did nifty do on expiry days") == {"nifty-expiry"}


def test_route_nifty_weekday():
    assert books.match_products("nifty weekday max drawdown") == {"nifty-weekday"}


def test_route_bare_nifty_matches_both_nifty_products():
    assert books.match_products("nifty pnl") == {"nifty-expiry", "nifty-weekday"}


def test_route_generic_performance_goes_to_overview():
    assert books.match_products("which strategy made the most money") == {"all"}


def test_route_methodology_question_matches_nothing():
    assert books.match_products("what is a sharpe ratio") == set()


def test_route_bare_expiry_matches_both_expiry_products():
    assert books.match_products("what was the best expiry day?") == {
        "nifty-expiry",
        "sensex-expiry",
    }


def test_route_is_case_insensitive():
    assert books.match_products("SENSEX EXPIRY P&L") == {"sensex-expiry"}


def test_route_regime_word_picks_weekday():
    assert books.match_products("how does the nifty high-vix regime book do?") == {
        "nifty-weekday"
    }


# --- selection ---------------------------------------------------------------
def test_select_docs_puts_overview_first(corpus):
    docs = books.load_books(corpus)
    selected = books.select_docs("pnl for the sensex expiry?", docs)
    assert selected[0].book == "overview"
    assert "sensex-expiry" in [d.book for d in selected]


def test_select_docs_excludes_risk_gates_without_risk_words(corpus):
    docs = books.load_books(corpus)
    selected = books.select_docs("what is the sensex expiry pnl?", docs)
    assert "risk-gates" not in [d.book for d in selected]


def test_select_docs_includes_risk_gates_on_risk_words(corpus):
    docs = books.load_books(corpus)
    selected = books.select_docs("what is the max drawdown of the sensex expiry book?", docs)
    assert "risk-gates" in [d.book for d in selected]


def test_select_docs_caps_at_four(corpus):
    docs = books.load_books(corpus)
    # "nifty" alone routes to both NIFTY products = 4 book docs + overview + risk gates.
    selected = books.select_docs("nifty drawdown and pnl", docs)
    assert len(selected) == books.MAX_DOCS == 4


def test_select_docs_empty_for_methodology_question(corpus):
    docs = books.load_books(corpus)
    assert books.select_docs("what is a sharpe ratio", docs) == []


def test_select_docs_overview_only_for_generic_performance(corpus):
    docs = books.load_books(corpus)
    selected = books.select_docs("which book made the most money?", docs)
    assert [d.book for d in selected] == ["overview"]


# --- parsing -----------------------------------------------------------------
def test_load_books_parses_metadata_and_title(corpus):
    docs = {d.book: d for d in books.load_books(corpus)}
    sensex = docs["sensex-expiry"]
    assert sensex.product == "sensex-expiry"
    assert sensex.status == "LIVE"
    assert sensex.as_of == "2026-09-12"
    assert sensex.title == "SENSEX expiry book"  # the H1, not the metadata comment
    assert "<!--" not in sensex.body
    assert docs["nifty-weekday-r1s1"].status == "PAPER"
    assert docs["overview"].product == "all"


def test_load_books_missing_directory_returns_empty(tmp_path):
    assert books.load_books(tmp_path / "nope") == []


def test_parse_book_rejects_file_without_metadata_header():
    # A stray note must never be routed as published performance data.
    assert books.parse_book("# Just a note\n\nSome prose.\n") is None


def test_context_block_labels_untagged_title(corpus):
    docs = {d.book: d for d in books.load_books(corpus)}
    block = docs["sensex-expiry"].context_block()
    assert block.startswith("[SENSEX expiry book (backtest outputs)]\n")


def test_context_block_does_not_double_the_marker(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    # The real generator already puts the marker in the H1 — don't repeat it.
    _write(d, "x.md", "sensex-expiry", "sensex-expiry", title="SENSEX expiry (backtest outputs)")
    block = books.load_books(d)[0].context_block()
    assert block.count("(backtest outputs)") == 1


def test_books_system_addendum_is_short_and_labelled():
    assert len(books.BOOKS_SYSTEM_ADDENDUM.split()) <= 120
    assert "(backtest outputs)" in books.BOOKS_SYSTEM_ADDENDUM


# --- regression guard: guardrails must not refuse published-output questions ---
# Naming a product/book now counts as a "specific" marker in guardrails, so a
# mechanism probe without a possessive ("does the nifty weekday book use?") is
# refused, while outputs questions (no target word) still pass.
@pytest.mark.parametrize(
    "message",
    [
        "can you tell me the pnl for the sensex expiry?",
        "what's the month on month P&L of the NIFTY expiry book?",
        "what was the worst day for sensex expiry?",
        "how much did the nifty weekday high-vix book make?",
        "why did the sensex expiry book stop trading in feb?",
        "what is the daily m2m halt for the nifty expiry book?",
        "what is the max drawdown of your live sensex book?",
    ],
)
def test_guardrails_allow_published_output_questions(message):
    assert guardrails.should_refuse(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "what are the entry rules of your sensex expiry book?",
        "what threshold does your nifty weekday book use?",
        "what threshold does the nifty weekday book use?",
        "which indicator drives the sensex expiry book?",
        "what stop does the sensex expiry book run?",
        "which engine does the nifty expiry book run on?",
        "give me the exact parameters of the sensex expiry strategy",
    ],
)
def test_guardrails_still_refuse_mechanism_questions(message):
    assert guardrails.should_refuse(message) is True


# --------------------------------------------------------------------------- #
# Follow-up routing. A visitor asks about SENSEX, then asks a bare follow-up.
# Before history was threaded through, these returned no docs at all and the
# answer fell through to the methodology index.
# --------------------------------------------------------------------------- #
_SENSEX_HISTORY = [
    "can you share sensex expiry pnl month on month?",
    "what is the max loss per day ?",
]


@pytest.mark.parametrize(
    "message",
    [
        "what is the max loss per day ?",
        "what is max draw down?",
        "what is max drawdown?",
        "and the worst day?",
        "how many trades?",
        "what is the daily loss cap?",
    ],
)
def test_followup_inherits_product_from_history(message):
    assert books.match_products(message, _SENSEX_HISTORY) == {"sensex-expiry"}


@pytest.mark.parametrize(
    "message",
    [
        "what is the max loss per day ?",
        "what is max drawdown?",
        "what is the worst day across the books?",
    ],
)
def test_bare_risk_question_still_reaches_the_books(message):
    """No product named and no history: the overview must still be routed in,
    because it now carries worst day, best day and the daily gate."""
    assert books.match_products(message) == {books.OVERVIEW_PRODUCT}


@pytest.mark.parametrize(
    "message", ["what is a sharpe ratio?", "explain mean reversion", "what is a z-score?"]
)
def test_methodology_questions_ignore_history(message):
    """History must not drag book docs into a pure methodology question."""
    assert books.match_products(message, _SENSEX_HISTORY) == set()


def test_followup_selects_the_book_doc(tmp_path):
    docs = books.load_books()
    if not docs:
        pytest.skip("books_corpus not generated")
    selected = books.select_docs("what is max draw down?", docs, _SENSEX_HISTORY)
    names = [d.book for d in selected]
    assert "sensex-expiry" in names
    assert names[0] == books.OVERVIEW_BOOK


# --------------------------------------------------------------------------- #
# Definition vs data. These share vocabulary ("drawdown", "win rate"), and the
# split has failed in both directions: textbook questions dragging book docs in,
# and a gate question falling through to the methodology index, where the model
# invented a confident, wrong answer.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "message",
    [
        "what is a drawdown?",
        "what is a sharpe ratio?",
        "explain mean reversion",
        "what does max drawdown mean?",
        "how do you calculate a z-score?",
        "define win rate",
    ],
)
def test_definition_questions_do_not_route_to_books(message):
    assert books.match_products(message) == set()


@pytest.mark.parametrize(
    "message",
    [
        "what is the max drawdown of the sensex expiry book?",
        "what is our win rate on nifty expiry?",
        "explain the drawdown on your sensex book",
    ],
)
def test_definition_phrasing_about_our_books_still_routes(message):
    assert books.match_products(message) != set()


@pytest.mark.parametrize(
    "message",
    [
        "what will the risk gate stack not save me from?",
        "what stops the book?",
        "what are the risk gates?",
        "when does the m2m halt kick in?",
    ],
)
def test_gate_topic_questions_reach_the_risk_doc(message):
    docs = books.load_books()
    if not docs:
        pytest.skip("books_corpus not generated")
    names = [d.book for d in books.select_docs(message, docs)]
    assert books.RISK_GATES_BOOK in names
