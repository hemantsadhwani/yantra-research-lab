"""Fill in monthly/daily P&L series for a public strategy "book" JSON.

Workflow (run from the PRIVATE trading repo, where the real trades CSV lives):
  1. Point this script at a book's trades CSV with --csv (plus --date-col/--pnl-col
     if your columns are not named "date"/"pnl_points" — see --help for defaults).
  2. It aggregates P&L by day and by month and fills in that book's "monthly" and
     "daily" arrays, leaving headline/cost/sizing/caveat/blurb untouched.
  3. It cross-checks sum(daily) against the existing headline.pnl_points and warns
     (non-zero exit) if they disagree by more than 0.5 points.
  4. The CSV itself NEVER enters this repo -- only the aggregated JSON output does.
     Review the diff, then commit the JSON here by hand.

Single book:
  python scripts/export_books.py --book nifty-weekday-high-vix --csv path/to/trades.csv

Batch, via a tab-separated manifest (book_id, csv_path, optional date_col, pnl_col;
"#" starts a comment line):
  python scripts/export_books.py --manifest books.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_BOOKS_DIR = "frontend/public/data/books"
DEFAULT_DATE_COL = "exit_date"
DEFAULT_PNL_COL = "pnl_points"
MISMATCH_TOLERANCE_POINTS = 0.5

# Accepted date formats, tried in order. "auto" (the default) tries all of them.
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d-%m-%Y",
]


class ExportError(Exception):
    """Raised for problems that should stop the export with a clear message."""


def parse_date(raw: str) -> str:
    """Parse one date string into a YYYY-MM-DD string. Accepts ISO-with-T too."""
    raw = raw.strip()
    if not raw:
        raise ExportError("empty date value")

    # ISO 8601 with a literal "T" separator, e.g. 2026-01-05T14:30:00
    candidate = raw
    if "T" in candidate:
        candidate = candidate.split("T", 1)[0]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            pass

    # If there's a space-separated time component, keep only the date part
    # once we know which format matched.
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ExportError(
        "could not parse date value %r -- accepted formats: YYYY-MM-DD, "
        "YYYY-MM-DD HH:MM[:SS], DD-MM-YYYY, or ISO with T" % raw
    )


def load_book(books_dir: Path, book_id: str) -> tuple[Path, dict]:
    book_path = books_dir / f"{book_id}.json"
    if not book_path.exists():
        raise ExportError(
            "no existing book JSON at %s -- create the book file first "
            "(headline/cost/sizing/blurb) before exporting a series into it" % book_path
        )
    with open(book_path, encoding="utf-8") as f:
        data = json.load(f)
    return book_path, data


def read_csv_rows(csv_path: Path, date_col: str, pnl_col: str) -> list[dict]:
    if not csv_path.exists():
        raise ExportError("CSV not found: %s" % csv_path)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        missing = [c for c in (date_col, pnl_col) if c not in fieldnames]
        if missing:
            raise ExportError(
                "CSV %s is missing column(s) %s. Actual header: %s. "
                "Pass --date-col/--pnl-col to match your CSV."
                % (csv_path, missing, fieldnames)
            )
        rows = list(reader)

    if not rows:
        raise ExportError("CSV %s has a header but no data rows" % csv_path)
    return rows


def aggregate(rows: list[dict], date_col: str, pnl_col: str) -> tuple[list[dict], list[dict]]:
    """Return (monthly, daily) point lists, each sorted ascending."""
    daily_totals: dict[str, float] = defaultdict(float)

    for i, row in enumerate(rows, start=2):  # start=2: header is line 1
        raw_date = row.get(date_col)
        raw_pnl = row.get(pnl_col)
        if raw_date is None or raw_pnl is None or str(raw_date).strip() == "":
            raise ExportError("row %d: missing %s or %s value" % (i, date_col, pnl_col))
        try:
            pnl = float(str(raw_pnl).strip())
        except ValueError:
            raise ExportError("row %d: could not parse pnl value %r" % (i, raw_pnl))
        day = parse_date(str(raw_date))
        daily_totals[day] += pnl

    daily = [
        {"date": d, "pnl_points": round(daily_totals[d], 2)}
        for d in sorted(daily_totals)
    ]

    monthly_totals: dict[str, float] = defaultdict(float)
    for d, pnl in daily_totals.items():
        month = d[:7]  # YYYY-MM
        monthly_totals[month] += pnl
    monthly = [
        {"month": m, "pnl_points": round(monthly_totals[m], 2)}
        for m in sorted(monthly_totals)
    ]

    return monthly, daily


def check_consistency(book_id: str, data: dict, monthly: list[dict], daily: list[dict]) -> bool:
    """Print consistency checks. Returns True if everything lines up."""
    ok = True

    headline_pnl = data.get("headline", {}).get("pnl_points")
    daily_sum = round(sum(p["pnl_points"] for p in daily), 2)
    print("[%s] headline.pnl_points = %s, sum(daily) = %s" % (book_id, headline_pnl, daily_sum))
    if headline_pnl is not None and abs(daily_sum - headline_pnl) > MISMATCH_TOLERANCE_POINTS:
        print(
            "WARNING: [%s] sum(daily) differs from headline.pnl_points by more than %.1f points"
            % (book_id, MISMATCH_TOLERANCE_POINTS)
        )
        ok = False

    period = data.get("period", {})
    period_from, period_to = period.get("from"), period.get("to")
    months_covered = [m["month"] for m in monthly]
    print(
        "[%s] period.from/to = %s .. %s, months covered = %s .. %s (%d months)"
        % (
            book_id,
            period_from,
            period_to,
            months_covered[0] if months_covered else None,
            months_covered[-1] if months_covered else None,
            len(months_covered),
        )
    )
    if months_covered and (
        (period_from and months_covered[0] < period_from)
        or (period_to and months_covered[-1] > period_to)
    ):
        print("WARNING: [%s] daily/monthly series extends outside period.from/to" % book_id)
        ok = False

    return ok


def export_one(
    book_id: str,
    csv_path: Path,
    books_dir: Path,
    date_col: str,
    pnl_col: str,
    dry_run: bool,
) -> bool:
    """Export one book. Returns True if consistency checks passed."""
    book_path, data = load_book(books_dir, book_id)
    rows = read_csv_rows(csv_path, date_col, pnl_col)
    monthly, daily = aggregate(rows, date_col, pnl_col)

    ok = check_consistency(book_id, data, monthly, daily)

    if dry_run:
        print("[%s] DRY RUN -- nothing written. Summary:" % book_id)
        print("  trades parsed: %d" % len(rows))
        print("  daily points:  %d" % len(daily))
        print("  monthly points: %d" % len(monthly))
        head = daily[:3]
        tail = daily[-3:] if len(daily) > 3 else []
        print("  first daily rows: %s" % head)
        print("  last daily rows:  %s" % tail)
        return ok

    data["monthly"] = monthly
    data["daily"] = daily
    data["series_pending"] = False

    with open(book_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("[%s] wrote %s (%d monthly points, %d daily points)" % (book_id, book_path, len(monthly), len(daily)))
    return ok


def read_manifest(manifest_path: Path) -> list[dict]:
    entries = []
    with open(manifest_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                raise ExportError(
                    "manifest line %d: expected at least book_id<TAB>csv_path, got %r"
                    % (lineno, line)
                )
            book_id = parts[0].strip()
            csv_path = parts[1].strip()
            date_col = parts[2].strip() if len(parts) > 2 and parts[2].strip() else DEFAULT_DATE_COL
            pnl_col = parts[3].strip() if len(parts) > 3 and parts[3].strip() else DEFAULT_PNL_COL
            entries.append(
                {"book_id": book_id, "csv_path": csv_path, "date_col": date_col, "pnl_col": pnl_col}
            )
    return entries


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fill monthly/daily P&L series in a public strategy book JSON from a trades CSV."
    )
    parser.add_argument("--book", help="book id, e.g. nifty-weekday-high-vix")
    parser.add_argument("--csv", help="path to the trades CSV (never committed to this repo)")
    parser.add_argument("--manifest", help="tab-separated file: book_id<TAB>csv_path[<TAB>date_col<TAB>pnl_col]")
    parser.add_argument("--date-col", default=DEFAULT_DATE_COL, help="CSV column with the trade/exit date (default: %(default)s)")
    parser.add_argument("--pnl-col", default=DEFAULT_PNL_COL, help="CSV column with the P&L in points (default: %(default)s)")
    parser.add_argument("--date-format", default="auto", help="reserved for future use; dates are auto-detected (default: %(default)s)")
    parser.add_argument("--books-dir", default=DEFAULT_BOOKS_DIR, help="directory holding book JSON files (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="print the summary but write nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.manifest and not (args.book and args.csv):
        parser.error("pass --manifest, or both --book and --csv")

    books_dir = Path(args.books_dir)
    if not books_dir.exists():
        print("ERROR: books dir not found: %s" % books_dir, file=sys.stderr)
        return 2

    all_ok = True

    try:
        if args.manifest:
            entries = read_manifest(Path(args.manifest))
            if not entries:
                print("ERROR: manifest %s has no entries" % args.manifest, file=sys.stderr)
                return 2
            for entry in entries:
                ok = export_one(
                    entry["book_id"],
                    Path(entry["csv_path"]),
                    books_dir,
                    entry["date_col"],
                    entry["pnl_col"],
                    args.dry_run,
                )
                all_ok = all_ok and ok
        else:
            all_ok = export_one(
                args.book,
                Path(args.csv),
                books_dir,
                args.date_col,
                args.pnl_col,
                args.dry_run,
            )
    except ExportError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2

    if not all_ok:
        print("WARNING: one or more consistency checks failed -- do not commit without review.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
