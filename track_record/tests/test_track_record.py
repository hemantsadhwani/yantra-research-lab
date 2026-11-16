"""The public track record: strategy assignment, exclusions, risk maths, and the privacy rule
that nothing per-trade (symbol, price, time, quantity, exit reason) reaches the JSON."""

from __future__ import annotations

import datetime as dt
import io
import json

import pytest

from track_record import build
from track_record.ledger import (
    LedgerError,
    backtest_record,
    monthly_expiry,
    parse_symbol,
    summarise,
    track_record,
)

HEADER = "trade_date,exit_time,symbol,entry_price,exit_price,pnl_percent,trade_status,exit_reason,source"


def row(date: str, symbol: str, pnl: float, status: str = "EXECUTED", source: str = "prod") -> str:
    return f"{date},10:15:00,{symbol},101.5,{101.5 * (1 + pnl / 100):.2f},{pnl},{status},Fixed % SL,{source}"


def csv_text(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


def rows(*lines: str) -> list[dict[str, str]]:
    from track_record.ledger import read_csv
    return read_csv(csv_text(*lines))


def by_id(doc: dict) -> dict[str, dict]:
    return {s["id"]: s for s in doc["strategies"] + doc["other"]}


def test_weekly_symbol_carries_its_expiry() -> None:
    assert parse_symbol("NIFTY2650524250PE") == ("NIFTY", dt.date(2026, 5, 5))
    assert parse_symbol("SENSEX26N1281800PE") == ("SENSEX", dt.date(2026, 11, 12))
    assert parse_symbol("NIFTY26O2025000CE") == ("NIFTY", dt.date(2026, 10, 20))


def test_monthly_expiry_is_last_tuesday_or_thursday_moved_back_for_holidays() -> None:
    assert monthly_expiry("NIFTY", 2026, 10) == dt.date(2026, 10, 27)      # last Tuesday
    assert monthly_expiry("SENSEX", 2026, 7) == dt.date(2026, 7, 30)       # last Thursday
    assert monthly_expiry("SENSEX", 2026, 5) == dt.date(2026, 5, 27)       # 28 May: Bakri Id
    assert parse_symbol("NIFTY26APR24400CE") == ("NIFTY", dt.date(2026, 4, 28))


def test_unknown_symbol_or_year_is_an_error_not_a_skip() -> None:
    with pytest.raises(LedgerError):
        parse_symbol("BANKNIFTY26N1250000CE")
    with pytest.raises(LedgerError):
        monthly_expiry("NIFTY", 2031, 1)


def test_trades_go_to_the_right_strategy() -> None:
    doc = track_record(rows(
        row("2026-11-11", "NIFTY26N1725000CE", 4.0),     # Wed, weekly expiring 17 Nov
        row("2026-11-17", "NIFTY26N1725000CE", -2.0),    # its expiry day
        row("2026-10-27", "NIFTY26OCT25000PE", 3.0),     # monthly, on its expiry (last Tue)
        row("2026-10-22", "NIFTY26OCT25000PE", 1.0),     # monthly, before expiry
        row("2026-11-12", "SENSEX26N1281800PE", 5.0),    # SENSEX expiry day
        row("2026-06-01", "SENSEX2660474800CE", -1.0),   # SENSEX weekday trial
    ), "t")
    s = by_id(doc)
    assert s["nifty-weekday"]["summary"]["trades"] == 2
    assert s["nifty-expiry"]["summary"]["trades"] == 2
    assert s["sensex-expiry"]["summary"]["total_pnl_pct"] == 5.0
    assert s["sensex-weekday"]["summary"]["total_pnl_pct"] == -1.0
    assert doc["first_day"] == "2026-06-01" and doc["kind"] == "live" and doc["as_of"] == "2026-11-17"


def test_paper_trades_are_left_out_and_counted() -> None:
    doc = track_record(rows(
        row("2026-11-11", "NIFTY26N1725000CE", 4.0, source="prod_pyramid"),
        row("2026-11-11", "NIFTY26N1725000CE", 9.0, status="PAPER (PYRAMID)", source="paper_pyramid"),
    ), "t")
    assert by_id(doc)["nifty-weekday"]["summary"]["total_pnl_pct"] == 4.0
    assert doc["left_out"] == {"paper_or_not_executed": 1}
    assert doc["other"] == []


def test_day_is_the_simple_sum_and_drawdown_is_peak_to_trough() -> None:
    days = {"2026-01-01": {"trades": 2, "wins": 1, "pnl": 10.0},
            "2026-01-02": {"trades": 1, "wins": 0, "pnl": -4.0},
            "2026-01-05": {"trades": 1, "wins": 0, "pnl": -3.0},
            "2026-02-02": {"trades": 1, "wins": 1, "pnl": 8.0}}
    out = summarise(days)
    s = out["summary"]
    assert s["total_pnl_pct"] == 11.0 and s["max_drawdown_pct"] == 7.0
    assert s["win_days"] == 2 and s["win_day_pct"] == 50.0
    assert s["best_day_pct"] == 10.0 and s["worst_day_pct"] == -4.0
    assert [d["cum_pct"] for d in out["days"]] == [10.0, 6.0, 3.0, 11.0]
    assert [(m["month"], m["pnl_pct"]) for m in out["months"]] == [("2026-01", 3.0), ("2026-02", 8.0)]


def test_nothing_per_trade_reaches_the_public_json() -> None:
    doc = track_record(rows(
        row("2026-11-11", "NIFTY26N1725000CE", 4.0),
        row("2026-11-12", "SENSEX26N1281800PE", 5.0),
    ), "t")
    text = json.dumps(doc)
    for leak in ("NIFTY26N1725000CE", "SENSEX26N", "101.5", "10:15", "Fixed % SL", "symbol",
                 "entry_price", "exit_price", "exit_time", "quantity", "exit_reason"):
        assert leak not in text, leak
    allowed = {"date", "trades", "wins", "pnl_pct", "cum_pct"}
    for s in doc["strategies"]:
        for d in s["days"]:
            assert set(d) == allowed


class FakeS3:
    """Just enough S3 for the Lambda: a listing, objects, and the write."""

    def __init__(self, objects: dict[str, str]) -> None:
        self.objects = objects
        self.put: dict = {}

    def get_paginator(self, _name: str):
        objs = self.objects

        class P:
            def paginate(self, Bucket: str, Prefix: str):
                return [{"Contents": [{"Key": k} for k in objs if k.startswith(Prefix)]}]
        return P()

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.objects[Key].encode("utf-8"))}

    def put_object(self, **kw) -> None:
        self.put = kw


FEED_HEAD = "date,n_trades,day_pnl_pct,wins\n"
FEED = {
    "public_feed/nifty_weekday.csv": FEED_HEAD + "2025-10-23,3,12.5,2\n2025-10-24,1,-4.0,0\n",
    "public_feed/nifty_expiry.csv": FEED_HEAD + "2025-09-09,2,20.0,1\n",
    "public_feed/sensex_expiry.csv": FEED_HEAD + "2025-09-04,5,-7.5,2\n",
    "public_feed/manifest.json": '{"generated_at": "2026-11-16T16:31+05:30", "from": "2025-09-01"}',
}


def test_lambda_reads_only_the_feed_and_writes_the_json(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3(dict(FEED))
    monkeypatch.setenv("FEED_BUCKET", "b")
    monkeypatch.setenv("FEED_PREFIX", "public_feed/")
    monkeypatch.setenv("SITE_BUCKET", "site")
    out = build.handler({}, None, client=s3)
    assert out == {"kind": "backtest", "as_of": "2025-10-24", "updated": "2026-11-16T16:31+05:30",
                   "days": {"nifty-weekday": 2, "nifty-expiry": 1, "sensex-expiry": 1}}
    assert s3.put["Bucket"] == "site" and s3.put["Key"] == "data/track_record.json"
    assert s3.put["CacheControl"] == "max-age=300"
    doc = json.loads(s3.put["Body"])
    assert by_id(doc)["nifty-weekday"]["summary"]["total_pnl_pct"] == 8.5


def test_a_missing_feed_file_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    feed = dict(FEED)
    del feed["public_feed/sensex_expiry.csv"]
    monkeypatch.setenv("FEED_BUCKET", "b")
    monkeypatch.setenv("FEED_PREFIX", "public_feed/")
    monkeypatch.setenv("SITE_BUCKET", "site")
    s3 = FakeS3(feed)
    with pytest.raises(KeyError):
        build.handler({}, None, client=s3)
    assert s3.put == {}          # the page keeps yesterday's JSON


def test_live_ledger_from_s3_reads_only_files_under_the_prefix() -> None:
    s3 = FakeS3({
        "logs/pnl_ledger/nifty_2026-11.csv": csv_text(row("2026-11-11", "NIFTY26N1725000CE", 4.0)),
        "logs/pnl_ledger/old/nifty_2026-11.csv": csv_text(row("2026-11-11", "NIFTY26N1725000CE", 99)),
        "logs/pnl_ledger_sensex_kite/sensex_2026-08.csv": "duplicate copy, must not be read",
    })
    rows = build.rows_from_s3("b", "logs/pnl_ledger/", client=s3)
    assert len(rows) == 1 and rows[0]["pnl_percent"] == "4.0"


def test_cli_from_a_feed_folder(tmp_path) -> None:
    for key, text in FEED.items():
        (tmp_path / key.split("/")[1]).write_text(text, encoding="utf-8")
    out = tmp_path / "site" / "track_record.json"
    assert build.main(["--feed-dir", str(tmp_path), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["kind"] == "backtest" and doc["generated_at"] == "2026-11-16T16:31+05:30"


def test_cli_from_a_folder(tmp_path) -> None:
    (tmp_path / "nifty_2026-11.csv").write_text(csv_text(row("2026-11-11", "NIFTY26N1725000CE", 4.0)),
                                               encoding="utf-8")
    out = tmp_path / "site" / "track_record.json"
    assert build.main(["--ledger-dir", str(tmp_path), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["as_of"] == "2026-11-11"


def test_backtest_record_from_daily_books_is_labelled_backtest() -> None:
    head = "date,n_trades,day_pnl_pct,wins\n"
    books = {
        "nifty-weekday": head + "2025-10-23,3,12.5,2\n2025-10-24,1,-4.0,0\n",
        "nifty-expiry": head + "2025-09-09,2,20.0,1\n",
        "sensex-expiry": head + "2025-09-04,5,-7.5,2\n",
    }
    doc = backtest_record(books, "t")
    assert doc["kind"] == "backtest" and doc["title"] == "Backtest record"
    assert "In-sample" in doc["definition"] and "not live" in doc["lede"]
    assert doc["first_day"] == "2025-09-04" and doc["as_of"] == "2025-10-24"
    s = by_id(doc)
    assert s["nifty-weekday"]["summary"]["total_pnl_pct"] == 8.5
    assert s["nifty-weekday"]["summary"]["trades"] == 4 and doc["other"] == []
