"""Every number in the report must come from the facts. Numbers are matched after rounding, so
"0.73" in prose matches 0.734 in the ledger; anything else is flagged, never silently kept."""

from __future__ import annotations

import re
from collections.abc import Iterable

NUM = re.compile(r"(?<![A-Za-z_])-?\d+(?:\.\d+)?")


def _walk(x: object) -> Iterable[float]:
    if isinstance(x, bool):
        return
    if isinstance(x, int | float):
        yield float(x)
    elif isinstance(x, str):
        for m in NUM.findall(x):
            yield float(m)
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _walk(k)
            yield from _walk(v)
    elif isinstance(x, list | tuple):
        for v in x:
            yield from _walk(v)


def allowed(facts: dict) -> set[str]:
    out: set[str] = set()
    for x in _walk(facts):
        for v in (x, abs(x)):
            out.add(f"{v:g}")
            for d in (0, 1, 2, 3):
                out.add(f"{round(v, d):.{d}f}")
    return out


def unsupported(text: str, facts: dict) -> list[str]:
    ok = allowed(facts)
    bad = []
    for m in NUM.findall(text):
        v = float(m)
        if v.is_integer() and 0 <= v <= 10:      # small counts and ordinals ("2 rounds", "3 templates")
            continue
        if m.lstrip("-") not in ok and f"{abs(v):g}" not in ok:
            bad.append(m)
    return sorted(set(bad))
