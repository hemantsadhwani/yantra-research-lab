"""The public track record: live (from the bot's per-trade ledger) or backtest (from its daily books).

The bot writes one row per closed trade (``trade_date, exit_time, symbol, entry_price,
exit_price, pnl_percent, trade_status, exit_reason, source``). This module keeps the live
executed trades, assigns each to a strategy, and returns daily totals per strategy in percent.

What leaves this module is percentages and counts only. No symbol, price, time, quantity or
exit reason is copied into the output: per-trade timing would show when the strategies enter.

What the numbers mean: ``pnl_percent`` is one trade's return on the option premium, net of
brokerage, taxes and slippage (it is computed from actual fills). A day's figure is the simple
sum over that day's trades. It is not account return and it is not compounded.

Stdlib only, like the research loop's core.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import re
from collections import defaultdict
from collections.abc import Iterable

# Exchange trading holidays (NSE and BSE publish the same list for 2026). Only monthly
# contracts need them: a monthly symbol names the month, not the day, so the expiry day is
# the last Tuesday (NIFTY) or Thursday (SENSEX), moved to the previous session if closed.
HOLIDAYS: dict[int, frozenset[dt.date]] = {
    2026: frozenset(dt.date.fromisoformat(d) for d in (
        "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
        "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
        "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
    )),
}
EXPIRY_WEEKDAY = {"NIFTY": calendar.TUESDAY, "SENSEX": calendar.THURSDAY}

STRATEGIES = [
    {"id": "nifty-weekday", "name": "NIFTY weekday", "index": "NIFTY", "expiry_day": False},
    {"id": "nifty-expiry", "name": "NIFTY expiry day", "index": "NIFTY", "expiry_day": True},
    {"id": "sensex-expiry", "name": "SENSEX expiry day", "index": "SENSEX", "expiry_day": True},
]
# SENSEX traded on non-expiry days for three sessions as a trial (29 May - 2 Jun 2026).
# It is shown, apart from the three strategies, so that every live trade is accounted for.
OTHER = {"id": "sensex-weekday", "name": "SENSEX weekday (trial)", "index": "SENSEX",
         "expiry_day": False}

TEXT = {
    "live": {
        "title": "Live track record",
        "lede": "Three intraday index-options strategies, run live on my own account and updated "
                "every weekday at 16:00 IST from the trading system's ledger.",
        "since_label": "Live since",
        "definition": "Each trade's return on the option premium from actual fills (so slippage "
                      "is included), summed per day. Broker charges and taxes are not deducted. "
                      "Not account return, not compounded. Every live executed trade is included; "
                      "paper trades are excluded.",
    },
    "backtest": {
        "title": "Backtest record",
        "lede": "Three intraday index-options strategies, backtested on NIFTY and SENSEX options "
                "with each strategy's current rules, and refreshed every weekday after the market "
                "closes. These are backtest results, not live trading.",
        "since_label": "Backtest from",
        "definition": "Each simulated trade's return on the option premium, after a modelled "
                      "per-trade slippage cost, summed per day. Broker charges and taxes are not "
                      "deducted. In-sample: the rules were developed and tuned on this same "
                      "period, and the whole history is recomputed when a rule changes, so live "
                      "results will differ. Not account return, not compounded.",
    },
}
DISCLAIMER = ("Past and simulated results do not predict future results. Not investment advice "
              "and not an offer of any service.")

_WEEKLY = re.compile(r"^(NIFTY|SENSEX)(\d\d)([1-9OND])(\d\d)\d+(CE|PE)$")
_MONTHLY = re.compile(r"^(NIFTY|SENSEX)(\d\d)([A-Z]{3})\d+(CE|PE)$")
_WEEKLY_MONTH = {**{str(i): i for i in range(1, 10)}, "O": 10, "N": 11, "D": 12}
_MONTHS = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}


class LedgerError(ValueError):
    """A row the track record cannot place. Raised, never skipped silently."""


def monthly_expiry(index: str, year: int, month: int) -> dt.date:
    """The last Tuesday (NIFTY) or Thursday (SENSEX) of the month, holiday-shifted back."""
    if year not in HOLIDAYS:
        raise LedgerError(f"no holiday list for {year}: add it to HOLIDAYS")
    day = dt.date(year, month, calendar.monthrange(year, month)[1])
    while day.weekday() != EXPIRY_WEEKDAY[index]:
        day -= dt.timedelta(days=1)
    while day in HOLIDAYS[year] or day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def parse_symbol(symbol: str) -> tuple[str, dt.date]:
    """(index, expiry date) from an NSE/BSE option symbol, weekly or monthly form."""
    m = _WEEKLY.match(symbol)
    if m:
        return m[1], dt.date(2000 + int(m[2]), _WEEKLY_MONTH[m[3]], int(m[4]))
    m = _MONTHLY.match(symbol)
    if m and m[3] in _MONTHS:
        return m[1], monthly_expiry(m[1], 2000 + int(m[2]), _MONTHS[m[3]])
    raise LedgerError(f"unrecognised option symbol {symbol!r}")


def strategy_of(index: str, trade_date: dt.date, expiry: dt.date) -> str:
    on_expiry = trade_date == expiry
    for s in (*STRATEGIES, OTHER):
        if s["index"] == index and s["expiry_day"] == on_expiry:
            return s["id"]
    raise LedgerError(f"no strategy for {index} on_expiry={on_expiry}")


def read_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def is_live(row: dict[str, str]) -> bool:
    return row.get("trade_status") == "EXECUTED" and row.get("source", "").startswith("prod")


def daily(rows: Iterable[dict[str, str]]) -> tuple[dict[str, dict[str, dict]], dict[str, int]]:
    """Per strategy, per date: trades, winning trades, summed pnl %. Plus counts of rows left out."""
    days: dict[str, dict[str, dict]] = defaultdict(dict)
    left_out = {"paper_or_not_executed": 0}
    for row in rows:
        if not is_live(row):
            left_out["paper_or_not_executed"] += 1
            continue
        trade_date = dt.date.fromisoformat(row["trade_date"])
        index, expiry = parse_symbol(row["symbol"])
        sid = strategy_of(index, trade_date, expiry)
        pnl = float(row["pnl_percent"])
        d = days[sid].setdefault(row["trade_date"], {"trades": 0, "wins": 0, "pnl": 0.0})
        d["trades"] += 1
        d["wins"] += pnl > 0
        d["pnl"] += pnl
    return days, left_out


def summarise(by_date: dict[str, dict]) -> dict:
    """Totals and risk for one strategy's daily series, in percentage points."""
    dates = sorted(by_date)
    series, cum, peak, max_dd = [], 0.0, 0.0, 0.0
    months: dict[str, dict] = {}
    for date in dates:
        d = by_date[date]
        cum += d["pnl"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        series.append({"date": date, "trades": d["trades"], "wins": d["wins"],
                       "pnl_pct": round(d["pnl"], 2), "cum_pct": round(cum, 2)})
        m = months.setdefault(date[:7], {"month": date[:7], "days": 0, "trades": 0, "pnl_pct": 0.0})
        m["days"] += 1
        m["trades"] += d["trades"]
        m["pnl_pct"] += d["pnl"]
    pnls = [by_date[x]["pnl"] for x in dates]
    win_days = sum(p > 0 for p in pnls)
    summary = {
        "first_day": dates[0] if dates else None,
        "last_day": dates[-1] if dates else None,
        "days_traded": len(dates),
        "trades": sum(by_date[x]["trades"] for x in dates),
        "win_days": win_days,
        "win_day_pct": round(100 * win_days / len(dates), 1) if dates else None,
        "total_pnl_pct": round(cum, 2),
        "avg_day_pct": round(cum / len(dates), 2) if dates else None,
        "best_day_pct": round(max(pnls), 2) if pnls else None,
        "worst_day_pct": round(min(pnls), 2) if pnls else None,
        "max_drawdown_pct": round(max_dd, 2),
    }
    for m in months.values():
        m["pnl_pct"] = round(m["pnl_pct"], 2)
    return {"summary": summary, "days": series, "months": list(months.values())}


def document(days: dict[str, dict[str, dict]], kind: str, generated_at: str,
             left_out: dict[str, int] | None = None) -> dict:
    """The public JSON document. Percentages and counts only."""
    unknown = set(days) - {s["id"] for s in (*STRATEGIES, OTHER)}
    if unknown:
        raise LedgerError(f"unexpected strategies {sorted(unknown)}")

    def block(s: dict) -> dict:
        return {"id": s["id"], "name": s["name"], **summarise(days.get(s["id"], {}))}

    all_days = sorted({d for s in days.values() for d in s})
    return {
        "kind": kind,
        **TEXT[kind],
        "generated_at": generated_at,
        "first_day": all_days[0] if all_days else None,
        "as_of": all_days[-1] if all_days else None,
        "strategies": [block(s) for s in STRATEGIES],
        "other": [block(OTHER)] if OTHER["id"] in days else [],
        "left_out": left_out or {},
        "disclaimer": DISCLAIMER,
    }


def track_record(rows: Iterable[dict[str, str]], generated_at: str) -> dict:
    """Live record from the bot's per-trade ledger."""
    days, left_out = daily(rows)
    return document(days, "live", generated_at, left_out)


def backtest_record(daily_csv: dict[str, str], generated_at: str) -> dict:
    """Backtest record from per-day books: {strategy id: CSV text with
    ``date, n_trades, day_pnl_pct, wins``} (the trading system's honest daily books)."""
    days: dict[str, dict[str, dict]] = {}
    for sid, text in daily_csv.items():
        days[sid] = {r["date"]: {"trades": int(r["n_trades"]), "wins": int(r["wins"]),
                                 "pnl": float(r["day_pnl_pct"])} for r in read_csv(text)}
    return document(days, "backtest", generated_at)
