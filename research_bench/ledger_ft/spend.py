"""Hard USD caps for every paid call, per stage and in total, logged per call.

``CappedProvider`` wraps any gateway provider. Before a call it RESERVES the call's worst-case
cost (all structured-output rungs: native, prompt, repair; full ``max_tokens`` out on each;
input counted at 2.5 characters a token, which overestimates JSON). If spent + reserved + this
reservation would pass the stage cap or the total cap, it raises ``BudgetExceeded`` and makes no
call. After the call it settles the reservation at the provider's reported cost. If the call
raises, the whole reservation is charged (the provider may have billed rungs before failing).

So the logged spend can only overstate the bill, and the caps cannot be passed, even with
studies running in parallel threads. One process at a time per ledger file.
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any

from llm_gateway import pricing

TOTAL_CAP_USD = 8.00            # raised from $5.00 by Hemant on 19 Nov 2026 (to $7, then "7-8$ is fine"), after the pilot gate failed on cost
STAGE_CAPS_USD = {"pilot": 0.50}          # other stages get a cap on the command line, <= what is left
CHARS_PER_TOKEN = 2.5
SPEND_LOG = Path(".cache") / "ledger_ft" / "spend.jsonl"


class BudgetExceeded(RuntimeError):
    """A call was refused before it was made: it could pass a cap."""


class SpendLedger:
    def __init__(self, path: str | Path = SPEND_LOG, total_cap: float = TOTAL_CAP_USD,
                 stage_caps: dict[str, float] | None = None) -> None:
        self.path = Path(path)
        self.total_cap = total_cap
        self.stage_caps = dict(STAGE_CAPS_USD if stage_caps is None else stage_caps)
        self._lock = threading.Lock()
        self._spent: dict[str, float] = {}
        self._reserved: dict[int, tuple[str, float]] = {}
        self._next = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self._spent[r["stage"]] = self._spent.get(r["stage"], 0.0) + float(r["usd"])

    # ---- reading ----
    def spent(self, stage: str | None = None) -> float:
        with self._lock:
            return round(sum(self._spent.values()) if stage is None else self._spent.get(stage, 0.0), 6)

    def remaining(self, stage: str) -> float:
        with self._lock:
            return self._room(stage)

    def _room(self, stage: str) -> float:
        res_all = sum(u for _, u in self._reserved.values())
        res_stage = sum(u for s, u in self._reserved.values() if s == stage)
        room = self.total_cap - sum(self._spent.values()) - res_all
        if stage in self.stage_caps:
            room = min(room, self.stage_caps[stage] - self._spent.get(stage, 0.0) - res_stage)
        return room

    # ---- writing ----
    def set_stage_cap(self, stage: str, cap: float) -> None:
        with self._lock:
            self.stage_caps[stage] = cap

    def reserve(self, stage: str, usd: float) -> int:
        if stage not in self.stage_caps:
            raise BudgetExceeded(f"stage {stage!r} has no cap; set one before spending")
        with self._lock:
            if usd > self._room(stage):
                raise BudgetExceeded(
                    f"refused: worst case ${usd:.4f} > room ${self._room(stage):.4f} "
                    f"(stage {stage} cap ${self.stage_caps[stage]:.2f}, total cap ${self.total_cap:.2f})")
            self._next += 1
            self._reserved[self._next] = (stage, usd)
            return self._next

    def settle(self, token: int, usd: float, **record: Any) -> None:
        with self._lock:
            stage, reserved = self._reserved.pop(token)
            usd = usd if record.get("ok", True) else reserved      # a failed call is charged in full
            if usd > reserved:
                record["over_reservation"] = True                   # logged, never hidden
            self._spent[stage] = self._spent.get(stage, 0.0) + usd
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": round(time.time(), 3), "stage": stage, "usd": round(usd, 8),
                                    "reserved": round(reserved, 8), **record}) + "\n")


def worst_case_usd(model: str, system: str, messages: list[dict], max_tokens: int,
                   schema: Any = None) -> float:
    row = pricing._row(model)
    if row is None:
        raise BudgetExceeded(f"no price row for {model!r}: refusing to spend unaccountable money")
    p_in, p_out = row[0], row[1]
    chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
    if schema is not None:
        chars += len(json.dumps(schema.model_json_schema()))
    tin = math.ceil(chars / CHARS_PER_TOKEN)
    rungs = [tin] if schema is None else [tin, tin, tin + max_tokens + 200]   # native, prompt, repair
    return sum(t * p_in + max_tokens * p_out for t in rungs) / 1_000_000


class CappedProvider:
    """Any provider, behind the ledger. Same ``complete`` signature as the gateway's Provider."""

    def __init__(self, inner: Any, ledger: SpendLedger, stage: str, role: str, study: str = "") -> None:
        self.inner, self.ledger, self.stage, self.role, self.study = inner, ledger, stage, role, study
        self.name, self.model = inner.name, inner.model

    def complete(self, *, system: str, messages: list[dict], max_tokens: int,
                 schema: Any = None, cache_system: bool = True) -> Any:
        est = worst_case_usd(self.model, system, messages, max_tokens, schema)
        token = self.ledger.reserve(self.stage, est)
        base = {"role": self.role, "model": self.model, "study": self.study}
        try:
            r = self.inner.complete(system=system, messages=messages, max_tokens=max_tokens,
                                    schema=schema, cache_system=cache_system)
        except Exception as e:
            self.ledger.settle(token, est, ok=False, error=f"{type(e).__name__}: {str(e)[:120]}", **base)
            raise
        self.ledger.settle(token, float(r.cost_usd), ok=True, input_tokens=r.input_tokens,
                           output_tokens=r.output_tokens, mode=r.structured_mode, **base)
        return r
