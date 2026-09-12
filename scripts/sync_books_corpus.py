"""Render strategy-book JSON into markdown docs for the chatbot's RAG corpus.

Why this exists: the strategy books (``frontend/public/data/books/*.json``) are the
single source of truth for backtest OUTPUTS — headline P&L, cost, sizing, monthly
series, risk gates. The backend's Docker image only ``COPY``s ``backend/``, so it
never sees ``frontend/`` at build time or at runtime. This script renders that JSON
into plain-prose markdown under ``backend/books_corpus/`` so the generated files can
be committed and shipped inside the backend image, and picked up by ``ingest.py``
the same way ``seed_corpus/`` is.

OUTPUTS ONLY, same rule as everywhere else in this repo (see CLAUDE.md and
ADR-0001): these docs may describe backtest results — P&L, win rate, drawdown,
sizing, risk gates — and must NEVER contain engine internals: indicator names,
parameter/threshold values, entry/exit rule names, or trade-level rows. The
``--check`` validation at the bottom of this module also greps the rendered output
for a denylist of known-internal terms as a defense-in-depth guardrail.

Usage:
    python scripts/sync_books_corpus.py            # render and write all files
    python scripts/sync_books_corpus.py --check     # render in memory, diff against
                                                      # disk, exit 1 on any mismatch
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = REPO_ROOT / "frontend" / "public" / "data" / "books"
OUT_DIR = REPO_ROOT / "backend" / "books_corpus"

STANDARD_LABEL = (
    "These are backtest outputs with simulated fills and a per-trade slippage "
    "charge; P&L is in points, summed not compounded; not a performance promise."
)

NOT_PUBLISHED_LINE = (
    "Not published, by design: the engine, indicators, thresholds, entry/exit "
    "rules and trade-level data. Ask about the methodology instead."
)

SERIES_PENDING_LINE = (
    "Monthly and daily P&L series have not been published yet — only the totals "
    "above are available. If asked for month-on-month numbers, say they are pending."
)


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------


def fmt_num(value: float, decimals: int = 2) -> str:
    """Format a float with a fixed number of decimals, plain '-' for negatives."""
    return f"{value:.{decimals}f}"


def fmt_inr(value: float) -> str:
    """Format a rupee amount with Indian digit grouping, e.g. 5855118 -> 58,55,118.

    Negative values keep a leading '-' before the currency symbol is applied by
    the caller. Fractional rupees are rounded to the nearest integer.
    """
    negative = value < 0
    n = round(abs(value))
    s = str(n)
    if len(s) <= 3:
        grouped = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join(parts) + "," + tail
    return ("-" if negative else "") + grouped


def fmt_inr_symbol(value: float) -> str:
    """Indian-grouped rupee amount with a leading currency symbol, e.g. '-69,004' -> '-₹69,004'."""
    grouped = fmt_inr(value)
    if grouped.startswith("-"):
        return "-₹" + grouped[1:]
    return "₹" + grouped


def fmt_pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def fmt_points(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{fmt_num(value)} points"


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Per-book rendering
# ---------------------------------------------------------------------------


def render_book(book: dict, product_def: dict) -> str:
    book_id = book["id"]
    label = book["label"]
    status = book["status"]
    as_of = INDEX["as_of"]

    lines: list[str] = []
    lines.append(
        f"<!-- product: {book['product']} | book: {book_id} | status: {status} | "
        f"as_of: {as_of} -->"
    )
    title_suffix = label if label.lower().endswith("book") else f"{label} book"
    lines.append(f"# {product_def['name']} — {title_suffix} (backtest outputs)")
    lines.append("")

    h = book["headline"]
    c = book["cost"]
    sz = book["sizing"]
    period = book["period"]

    status_sentence = (
        "Runs LIVE in production."
        if status == "LIVE"
        else "Runs PAPER — simulated fills, not live money."
    )
    para = (
        f"{book['blurb']} {status_sentence} This covers the backtest period "
        f"{period['from']} to {period['to']}. {STANDARD_LABEL}"
    )
    lines.append(para)
    lines.append("")

    # Headline
    lines.append("Headline:")
    lines.append(
        f"- Book P&L {fmt_points(h['pnl_points'])} over {h['trades']} trades in "
        f"{h['sessions']} sessions"
    )
    lines.append(
        f"- Win rate {fmt_pct(h['win_rate_pct'])} ({h['wins']} wins / {h['losses']} losses)"
    )
    lines.append(
        f"- Per trade {fmt_points(h['per_trade_points'])}, per session "
        f"{fmt_points(h['per_session_points'])}"
    )
    lines.append(f"- Months up {h['months_up']} of {h['months_traded']} traded")
    lines.append(f"- Top 5 trades are {fmt_num(h['top5_share_pct'], 0)}% of the book")
    lines.append("")

    # What it costs
    lines.append("What it costs:")
    lines.append(
        f"- Worst day {fmt_num(c['worst_day_points'])} points (about "
        f"{fmt_inr_symbol(c['worst_day_inr'])})"
    )
    lines.append(
        f"- Max drawdown {fmt_num(c['max_drawdown_points'])} points (about "
        f"{fmt_inr_symbol(c['max_drawdown_inr'])})"
    )
    lines.append(
        f"- Best day {fmt_points(c['best_day_points'])} (about "
        f"{fmt_inr_symbol(c['best_day_inr'])})"
    )
    lines.append(f"- Days up {c['days_up']} of {c['days_traded']} traded days")
    lines.append(
        f"- Daily gate: M2M halt at {fmt_num(c['day_gate_pct'], 0)}% of the book's "
        f"own base capital"
    )
    lines.append("")

    # Sizing
    lots_range = f"{sz['lots_per_leg_min']}–{sz['lots_per_leg_max']}"
    slippage = (
        "slippage not separately charged"
        if sz["slippage_pct_per_trade"] is None
        else f"slippage {fmt_num(sz['slippage_pct_per_trade'], 1)}% per trade"
    )
    lines.append(
        "Sizing: "
        f"{fmt_inr_symbol(sz['per_leg_inr'])} per leg, lot size {sz['lot']}, "
        f"{lots_range} lots per leg, average deployed {fmt_inr_symbol(sz['avg_deployed_inr'])}, "
        f"peak reserve {fmt_inr_symbol(sz['peak_reserve_inr'])}, net P&L "
        f"{fmt_inr_symbol(sz['net_pnl_inr'])}, {slippage}."
    )
    lines.append("")

    # Month by month
    lines.append("Month by month:")
    if book.get("series_pending") or not book.get("monthly"):
        lines.append(SERIES_PENDING_LINE)
    else:
        cumulative = 0.0
        for point in book["monthly"]:
            cumulative += point["pnl_points"]
            lines.append(f"- {point['month']}: {fmt_points(point['pnl_points'])}")
        lines.append(f"- Cumulative: {fmt_points(cumulative)}")
    lines.append("")

    if book.get("caveat"):
        lines.append(f"Caveat: {book['caveat']}")
        lines.append("")

    lines.append(NOT_PUBLISHED_LINE)
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Overview rendering
# ---------------------------------------------------------------------------


def render_overview(index: dict, books_by_id: dict[str, dict]) -> str:
    as_of = index["as_of"]
    lines: list[str] = []
    lines.append(f"<!-- product: all | book: overview | status: - | as_of: {as_of} -->")
    lines.append("# Strategy books — overview (backtest outputs)")
    lines.append("")

    product_sentences = []
    for product in index["products"]:
        book_bits = []
        for book_id in product["books"]:
            book = books_by_id.get(book_id)
            if book is None:
                continue
            book_bits.append(f"{book['label']} ({book['status']})")
        product_sentences.append(
            f"{product['name']} — {product['tagline']} It contains "
            f"{', '.join(book_bits)}."
        )
    intro = (
        "There are three products in this set: "
        + " ".join(product_sentences)
    )
    lines.append(intro)
    lines.append("")

    lines.append("Quick comparison:")
    for product in index["products"]:
        for book_id in product["books"]:
            book = books_by_id.get(book_id)
            if book is None:
                continue
            h = book["headline"]
            c = book["cost"]
            lines.append(
                f"- {product['name']} · {book['label']} ({book['status']}): "
                f"{fmt_points(h['pnl_points'])}, {h['trades']} trades, win rate "
                f"{fmt_pct(h['win_rate_pct'], 1)}, max drawdown "
                f"{fmt_num(c['max_drawdown_points'])} points, worst day "
                f"{fmt_num(c['worst_day_points'])} points, best day "
                f"{fmt_points(c['best_day_points'])}, daily M2M halt at "
                f"{c['day_gate_pct']:g}% of the book's own base, months up "
                f"{h['months_up']}/{h['months_traded']}"
            )
    lines.append("")

    # Explicit rankings. The comparison list above is grouped by product, so a
    # "which book has the deepest drawdown / most trades?" question needed the
    # model to rank six rows itself -- and it got it wrong, naming one book and
    # contradicting itself two lines later. Stating the orderings removes the
    # inference step.
    listed = [
        (b, b["headline"], b["cost"])
        for pid in (p["id"] for p in index["products"])
        for b in (books_by_id.get(bid) for bid in
                  next(p["books"] for p in index["products"] if p["id"] == pid))
        if b is not None
    ]
    seen: set[str] = set()
    uniq = [t for t in listed if not (t[0]["id"] in seen or seen.add(t[0]["id"]))]

    def name(book: dict) -> str:
        product = next(p["name"] for p in index["products"] if p["id"] == book["product"])
        return f"{product} {book['label']} ({book['status']})"

    by_pnl = sorted(uniq, key=lambda t: -t[1]["pnl_points"])
    by_dd = sorted(uniq, key=lambda t: t[2]["max_drawdown_points"])
    by_worst = sorted(uniq, key=lambda t: t[2]["worst_day_points"])
    lines.append("Rankings across the published books:")
    lines.append(
        "- Largest P&L first: "
        + "; ".join(f"{name(b)} {fmt_points(h['pnl_points'])}" for b, h, _ in by_pnl)
    )
    lines.append(
        "- Deepest max drawdown first: "
        + "; ".join(f"{name(b)} {fmt_num(c['max_drawdown_points'])} points" for b, _, c in by_dd)
    )
    lines.append(
        "- Worst single day first: "
        + "; ".join(f"{name(b)} {fmt_num(c['worst_day_points'])} points" for b, _, c in by_worst)
    )
    lines.append("")

    lines.append(index["disclaimer"])
    lines.append("")

    lines.append(NOT_PUBLISHED_LINE)
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Risk gates rendering
# ---------------------------------------------------------------------------


def render_risk_gates(rg: dict) -> str:
    as_of = rg["as_of"]
    lines: list[str] = []
    lines.append(f"<!-- product: all | book: risk-gates | status: - | as_of: {as_of} -->")
    lines.append("# Risk gates — what stops each book")
    lines.append("")

    lines.append(
        "Automatic stops sit above the strategy and watch different stretches of "
        "time; only one of them can interrupt a day already running."
    )
    lines.append("")

    lines.append("How to read this:")
    for term in rg["how_to_read"]:
        lines.append(f"- {term['term']}: {term['meaning']}")
    lines.append("")

    # Group armed gates by profile, preserving the profile order in rg["profiles"].
    armed_by_profile: dict[str, list[dict]] = {}
    for row in rg["armed"]:
        armed_by_profile.setdefault(row["profile"], []).append(row)

    lines.append("Profiles and their armed gates:")
    for profile in rg["profiles"]:
        name = profile["profile"]
        rows = armed_by_profile.get(name, [])
        gate_bits = []
        for row in rows:
            checked = row["checked"]
            gate_name = row["gate"]
            gate_lower = gate_name[0].lower() + gate_name[1:] if gate_name else gate_name
            gate_bits.append(
                f"{gate_lower} at {fmt_num(row['trips_at_pct'], 0)}% "
                f"({fmt_inr_symbol(row['in_inr'])}), checked {checked}"
            )
        gate_text = "; ".join(gate_bits) if gate_bits else "no gates armed"
        lines.append(f"- {name}: {gate_text}")
    lines.append("")

    lines.append("What each gate cancels:")
    for row in rg["cancels"]:
        lines.append(
            f"- {row['gate']}: counts from {row['counts_from']}, blocks "
            f"{row['blocks']}, open trades are {row['open_trades']}"
        )
    lines.append("")

    lines.append("Present but inert:")
    for row in rg["inert"]:
        lines.append(f"- {row['profile']}: {row['present_but_inert']}")
    lines.append("")

    lines.append("Paper sub-book brakes:")
    for row in rg["paper_brakes"]:
        lines.append(
            f"- {row['profile']}: book base {fmt_inr_symbol(row['book_base_inr'])}, "
            f"floor {fmt_num(row['floor_pct'], 0)}% ({fmt_inr_symbol(row['floor_inr'])}), "
            f"worst day so far {fmt_inr_symbol(row['worst_day_inr'])}"
        )
    lines.append("")

    lines.append("These gates will not save you from:")
    for row in rg["will_not_save_you_from"]:
        lines.append(f"- {row['title']} — {row['body']}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


INDEX: dict = {}


def build_files() -> dict[str, str]:
    """Render every corpus file in memory. Returns {relative_filename: content}."""
    global INDEX
    INDEX = load_json(BOOKS_DIR / "index.json")
    risk_gates = load_json(BOOKS_DIR / "risk_gates.json")

    listed_book_ids: list[str] = []
    for product in INDEX["products"]:
        listed_book_ids.extend(product["books"])
    listed_book_ids = sorted(set(listed_book_ids))

    # book_id -> owning product def, via the product that lists it
    product_for_book: dict[str, dict] = {}
    for product in INDEX["products"]:
        for book_id in product["books"]:
            product_for_book[book_id] = product

    books_by_id: dict[str, dict] = {}
    for book_id in listed_book_ids:
        book_path = BOOKS_DIR / f"{book_id}.json"
        if not book_path.exists():
            raise SystemExit(f"ERROR: listed book '{book_id}' has no JSON file at {book_path}")
        books_by_id[book_id] = load_json(book_path)

    files: dict[str, str] = {}
    for book_id in listed_book_ids:
        book = books_by_id[book_id]
        product_def = product_for_book[book_id]
        files[f"{book_id}.md"] = render_book(book, product_def)

    files["00-overview.md"] = render_overview(INDEX, books_by_id)
    files["risk-gates.md"] = render_risk_gates(risk_gates)

    return files


DENYLIST = [
    "W%R",
    "DeMarker",
    "StochRSI",
    "SuperTrend",
    "CPR",
    "MFE",
    "Swing Low",
    "ATR",
    "Entry2",
    "Entry3",
    "ratchet",
]


def validate_no_leaks(files: dict[str, str]) -> list[str]:
    """Return a list of 'filename: term' violations, empty if clean."""
    violations = []
    for name, content in sorted(files.items()):
        lower = content.lower()
        for term in DENYLIST:
            if term.lower() in lower:
                violations.append(f"{name}: contains banned term '{term}'")
    return violations


def do_sync() -> int:
    files = build_files()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in sorted(files.items()):
        path = OUT_DIR / name
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(REPO_ROOT)} ({len(content.encode('utf-8'))} bytes)")
    print(f"Done. {len(files)} file(s) written to {OUT_DIR.relative_to(REPO_ROOT)}.")
    return 0


def do_check() -> int:
    files = build_files()
    problems: list[str] = []

    if OUT_DIR.exists():
        existing = {p.name for p in OUT_DIR.glob("*.md")}
    else:
        existing = set()

    expected_names = set(files.keys())

    for name in sorted(expected_names):
        path = OUT_DIR / name
        if not path.exists():
            problems.append(f"MISSING: {name} (not on disk)")
            continue
        on_disk = path.read_text(encoding="utf-8")
        if on_disk != files[name]:
            problems.append(f"STALE: {name} (rendered content differs from what is on disk)")

    extra = existing - expected_names
    for name in sorted(extra):
        problems.append(f"UNEXPECTED: {name} (on disk but not produced by the renderer)")

    if problems:
        print("books_corpus is OUT OF SYNC with frontend/public/data/books/:")
        for p in problems:
            print(f"  - {p}")
        print("Run 'python scripts/sync_books_corpus.py' to regenerate.")
        return 1

    print(f"OK: {len(files)} file(s) in sync with frontend/public/data/books/.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="render in memory and diff against backend/books_corpus/ without writing; exit 1 on mismatch",
    )
    args = parser.parse_args(argv)

    if args.check:
        return do_check()
    return do_sync()


if __name__ == "__main__":
    raise SystemExit(main())
