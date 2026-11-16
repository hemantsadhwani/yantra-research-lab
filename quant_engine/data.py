"""Daily bars, loading, and the dataset card (checks + content hash) every run cites."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
from dataclasses import dataclass


@dataclass
class Bars:
    date: list[str]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    vix: list[float] | None = None

    def __len__(self) -> int:
        return len(self.date)

    def slice(self, a: int, b: int) -> Bars:
        return Bars(self.date[a:b], self.open[a:b], self.high[a:b], self.low[a:b],
                    self.close[a:b], None if self.vix is None else self.vix[a:b])

    def to_csv(self) -> str:
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["date", "open", "high", "low", "close", "vix"])
        for i in range(len(self)):
            w.writerow([self.date[i], self.open[i], self.high[i], self.low[i], self.close[i],
                        "" if self.vix is None else self.vix[i]])
        return out.getvalue()


def from_csv(text: str) -> Bars:
    rows = list(csv.DictReader(io.StringIO(text)))
    vix = [float(r["vix"]) for r in rows] if rows and rows[0].get("vix") not in (None, "") else None
    return Bars([r["date"] for r in rows], [float(r["open"]) for r in rows],
                [float(r["high"]) for r in rows], [float(r["low"]) for r in rows],
                [float(r["close"]) for r in rows], vix)


def dataset_card(b: Bars, source: str) -> dict:
    """What the data agent hands over: provenance, range, checks, and a content hash that the
    backtests and the final report cite. A failed check is reported, never silently fixed."""
    checks: dict[str, int] = {"duplicate_dates": 0, "out_of_order": 0, "bad_ohlc": 0,
                              "non_positive": 0, "gaps_over_5_days": 0}
    for i in range(len(b)):
        o, h, lo, c = b.open[i], b.high[i], b.low[i], b.close[i]
        checks["bad_ohlc"] += not (lo <= min(o, c) and h >= max(o, c))
        checks["non_positive"] += min(o, h, lo, c) <= 0
        if i:
            d0, d1 = dt.date.fromisoformat(b.date[i - 1]), dt.date.fromisoformat(b.date[i])
            checks["duplicate_dates"] += d1 == d0
            checks["out_of_order"] += d1 < d0
            checks["gaps_over_5_days"] += (d1 - d0).days > 5
    return {
        "source": source,
        "first": b.date[0] if len(b) else None,
        "last": b.date[-1] if len(b) else None,
        "rows": len(b),
        "has_vix": b.vix is not None,
        "checks": checks,
        "passed": all(v == 0 for k, v in checks.items() if k != "gaps_over_5_days"),
        "sha256": hashlib.sha256(b.to_csv().encode("utf-8")).hexdigest()[:16],
    }
