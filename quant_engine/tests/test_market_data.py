"""Market data without the network: allow-list, IST dating, counted drops, the join, the cache."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from quant_engine import market_data as md

IST = 19800  # +05:30


def payload(days: list[tuple[str, float | None]]) -> bytes:
    """Chart-API shaped JSON; timestamps at 09:15 IST (03:45 UTC) as the real feed sends."""
    ts = [int(dt.datetime.fromisoformat(f"{d}T03:45:00+00:00").timestamp()) for d, _ in days]
    closes = [c for _, c in days]
    q = {"open": closes, "high": [None if c is None else c + 1 for c in closes],
         "low": [None if c is None else c - 1 for c in closes], "close": closes}
    return json.dumps({"chart": {"result": [{"meta": {"gmtoffset": IST}, "timestamp": ts,
                                             "indicators": {"quote": [q]}}]}}).encode()


def fake_opener(urls: list[str]):
    def opener(url: str) -> bytes:
        urls.append(url)
        if "NSEI" in url:
            return payload([("2026-11-10", 100.0), ("2026-11-11", None), ("2026-11-12", 102.0),
                            ("2026-11-13", 103.0)])
        return payload([("2026-11-10", 14.0), ("2026-11-12", 15.0), ("2026-11-14", 16.0)])
    return opener


def test_only_allow_listed_series() -> None:
    with pytest.raises(ValueError):
        md.fetch("AAPL", dt.date(2020, 1, 1), dt.date(2020, 2, 1), opener=lambda u: b"")


def test_join_counts_every_drop_and_dates_are_ist(tmp_path) -> None:
    urls: list[str] = []
    b, card = md.nifty_with_vix(dt.date(2026, 11, 10), dt.date(2026, 11, 14),
                                opener=fake_opener(urls), cache=tmp_path)
    assert b.date == ["2026-11-10", "2026-11-12"] and b.vix == [14.0, 15.0]
    assert card["dropped"] == {"nifty_missing_values": 1, "vix_missing_values": 0,
                               "nifty_dates_without_vix": 1, "vix_dates_without_nifty": 1,
                               "duplicate_rows": 0}
    assert card["passed"] and len(urls) == 2 and all("query1.finance.yahoo.com" in u for u in urls)


def test_second_call_is_served_from_the_cache(tmp_path) -> None:
    urls: list[str] = []
    md.nifty_with_vix(dt.date(2026, 11, 10), dt.date(2026, 11, 14), opener=fake_opener(urls), cache=tmp_path)
    b, _ = md.nifty_with_vix(dt.date(2026, 11, 10), dt.date(2026, 11, 14), opener=fake_opener(urls),
                             cache=tmp_path)
    assert len(urls) == 2 and len(b) == 2
