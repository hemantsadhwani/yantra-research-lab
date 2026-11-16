"""Public market data for the research engine: NIFTY 50 and India VIX daily bars.

The data agent may only call these fetchers (an allow-list, never a URL of its choosing).
Data is fetched at run time and cached locally (``.cache/market_data/``, git-ignored); it is
never committed. Rows with missing values are dropped and COUNTED, and the two series are
joined on dates both have; the dataset card reports every drop, so nothing is fixed silently.

Source: the public Yahoo Finance chart endpoint (no key). For research and education.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from quant_engine.data import Bars, dataset_card

ALLOWED = {"NIFTY50": "^NSEI", "INDIAVIX": "^INDIAVIX"}
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d"
CACHE = Path(".cache") / "market_data"
Opener = Callable[[str], bytes]


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research-client)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch(series: str, start: dt.date, end: dt.date, opener: Opener = _http_get) -> tuple[list[dict], int]:
    """Daily OHLC rows for an allow-listed series, dated in the exchange's time zone.
    Returns (rows, dropped) where dropped counts rows with any missing value."""
    if series not in ALLOWED:
        raise ValueError(f"{series!r} is not an allowed series: {sorted(ALLOWED)}")
    p1 = int(dt.datetime.combine(start, dt.time(), dt.UTC).timestamp())
    p2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time(), dt.UTC).timestamp())
    url = URL.format(sym=urllib.parse.quote(ALLOWED[series]), p1=p1, p2=p2)
    res = json.loads(opener(url))["chart"]["result"][0]
    offset = dt.timedelta(seconds=res["meta"].get("gmtoffset", 0))
    q = res["indicators"]["quote"][0]
    rows, dropped = [], 0
    for i, ts in enumerate(res.get("timestamp", [])):
        o, h, lo, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, lo, c):
            dropped += 1
            continue
        day = (dt.datetime.fromtimestamp(ts, dt.UTC) + offset).date().isoformat()
        rows.append({"date": day, "open": o, "high": h, "low": lo, "close": c})
    return rows, dropped


def nifty_with_vix(start: dt.date = dt.date(2008, 3, 3), end: dt.date | None = None,
                   opener: Opener = _http_get, cache: Path | None = CACHE) -> tuple[Bars, dict]:
    """NIFTY 50 bars with the India VIX close on the same date, plus the dataset card."""
    end = end or dt.date.today()
    key = f"nifty_vix_{start}_{end}.json"
    if cache is not None and (cache / key).exists():
        saved = json.loads((cache / key).read_text(encoding="utf-8"))
        n_rows, v_rows, drops = saved["nifty"], saved["vix"], saved["dropped"]
    else:
        n_rows, n_drop = fetch("NIFTY50", start, end, opener)
        v_rows, v_drop = fetch("INDIAVIX", start, end, opener)
        drops = {"nifty_missing_values": n_drop, "vix_missing_values": v_drop}
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            (cache / key).write_text(json.dumps({"nifty": n_rows, "vix": v_rows, "dropped": drops}),
                                     encoding="utf-8")
    vix = {r["date"]: r["close"] for r in v_rows}
    nifty = {r["date"]: r for r in n_rows}           # last row wins on a duplicate date
    days = sorted(d for d in nifty if d in vix)
    b = Bars(days, [nifty[d]["open"] for d in days], [nifty[d]["high"] for d in days],
             [nifty[d]["low"] for d in days], [nifty[d]["close"] for d in days],
             [vix[d] for d in days])
    card = dataset_card(b, "Yahoo Finance daily: ^NSEI (NIFTY 50) joined with ^INDIAVIX close")
    card["dropped"] = {**drops, "nifty_dates_without_vix": len(set(nifty) - set(vix)),
                       "vix_dates_without_nifty": len(set(vix) - set(nifty)),
                       "duplicate_rows": len(n_rows) - len(nifty)}
    return b, card
