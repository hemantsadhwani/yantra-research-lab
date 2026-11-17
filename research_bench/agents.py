"""The agents: one role each, a short system prompt, and a brief built from the ledger.

``LLMAgents`` calls a provider per role (open models on Bedrock by default, chosen per role).
``OfflineAgents`` is a deterministic policy with the same methods, for tests and CI: it needs
no key and no network. Both return the schemas in ``research_bench.schemas``; code clamps
whatever they propose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

from research_bench import tools
from research_bench.schemas import (
    CriticReview,
    Experiment,
    Plan,
    PlanReview,
    Report,
    RoundProposal,
    StrategySpec,
)

ROLE_MODELS = {
    "intake": ("converse", "google.gemma-3-12b-it"),
    "planner": ("converse", "deepseek.v3.2"),
    "researcher": ("converse", "deepseek.v3.2"),
    "critic": ("converse", "deepseek.v3.2"),
    "reporter": ("converse", "google.gemma-3-12b-it"),
}
GEMMA, DEEPSEEK = ("converse", "google.gemma-3-12b-it"), ("converse", "deepseek.v3.2")
MODEL_SETS = {
    "mixed": ROLE_MODELS,
    "gemma": dict.fromkeys(ROLE_MODELS, GEMMA),
    "deepseek": dict.fromkeys(ROLE_MODELS, DEEPSEEK),
}

SUCCESS_TEST = (
    f"Fixed in code: walk-forward over {tools.PROTO.folds} test blocks with parameters re-chosen "
    f"before each block; out-of-sample Sharpe >= {tools.PROTO.oos_sharpe_min} and at least "
    f"{int(tools.PROTO.positive_folds_min * tools.PROTO.folds)} of {tools.PROTO.folds} blocks positive; then ONE "
    f"look at a sealed holdout (last ~2 years), Sharpe >= {tools.PROTO.holdout_sharpe_min}. Costs "
    f"{tools.PROTO.cost_bps} bps per change, signal at the close, fill next open, long/flat. The "
    f"walk-forward bar rises with every family tested: OOS Sharpe >= {tools.PROTO.oos_sharpe_min} + "
    f"{tools.LOOK_PENALTY} x log2(looks)."
)

SYSTEM = {
    "intake": (
        "You turn a researcher's trading idea into a testable spec for DAILY index data (NIFTY 50 "
        "with India VIX). Infer the style (continuation = trend following/breakouts, reversal = "
        "buying oversold dips, pullback = buying retracements in an uptrend). Ask a question only "
        "when the style truly cannot be inferred, at most 3, and never when questions are not allowed."
    ),
    "planner": (
        "You plan a strategy study. Choose 1-3 templates from the catalogue that test the idea, a "
        "trial budget and a number of rounds. Every trial raises the chance of a false discovery, "
        "so ask for no more trials than the idea needs. You cannot change the success test."
    ),
    "researcher": (
        "You are a quant researcher running experiments through tools. Read the ledger and the "
        "diagnostics, say what they mean, then propose at most 3 experiment families for the next "
        "round using only catalogue values. Be targeted: change one thing at a time and give a "
        "reason (e.g. losses cluster when VIX is high -> try vix_max). Each walk-forward result you "
        "react to is a counted look, so do not chase small gains. Request diagnostics on promising "
        f"families. Stop when nothing is likely to improve the result. At most {tools.ROUND_TRIAL_CAP} "
        "new trials per round."
    ),
    "critic": (
        "You are a sceptical reviewer of quant research. Decide whether the best result so far is "
        "believable: enough positive test blocks, better than buy-and-hold, not dependent on one "
        "period, stable across neighbouring parameters, and not the product of many looks. Ask for "
        "a robustness check when stability is unknown; say stop when further rounds would only fit noise."
    ),
    "plan_critic": (
        "You review a study plan before any test runs. Approve it unless the templates do not test "
        "the idea or the trial budget is larger than the idea needs."
    ),
    "reporter": (
        "You write the study's report for a portfolio manager in plain English. Use ONLY numbers "
        "that appear in the facts, copied exactly. Say what was tested, what held up, what failed "
        "and the verdict. Short sentences."
    ),
}


def brief(state: dict, extra: dict | None = None) -> str:
    """The ledger, summarised: what an agent needs this turn, nothing else."""
    led = state["ledger"]
    fams = sorted(led["families"], key=lambda f: f["oos_sharpe"], reverse=True)
    rows = [{k: f[k] for k in ("id", "round", "template", "trials", "in_sample_sharpe", "oos_sharpe",
                               "positive_folds", "passed_walk_forward", "buy_hold_oos_sharpe")}
            | {"space": {k: v for k, v in f["space"].items() if v != [0]}} for f in fams[:8]]
    payload = {
        "idea": state["idea"], "spec": state.get("spec"), "plan": state.get("plan"),
        "success_test": SUCCESS_TEST,
        "budget": {"trials_used": led["trials"], "trial_budget": (state.get("plan") or {}).get("trial_budget"),
                   "walk_forward_looks": led["looks"],
                   "required_oos_sharpe_now": tools.required_oos_sharpe(led["looks"]),
                   "required_oos_sharpe_after_one_more_look": tools.required_oos_sharpe(led["looks"] + 1),
                   "round": state["round"],
                   "rounds": (state.get("plan") or {}).get("rounds")},
        "families_best_first": rows,
        "diagnostics": list(led["diagnostics"].values())[-3:],
        "neighbourhood": list(led["neighbourhood"].values())[-3:],
        "last_critic": (state["reviews"][-1] if state["reviews"] else None),
        "refused_by_code_recently": led["dropped"][-6:],
        "note": "Filters only change a family if you put their values in params; a repeat of an earlier "
                "family is refused and wastes the round.",
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, default=str)


@dataclass
class LLMAgents:
    providers: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 900
    role_models: dict[str, tuple[str, str]] = field(default_factory=lambda: dict(ROLE_MODELS))

    def _provider(self, role: str) -> Any:
        if role not in self.providers:
            from llm_gateway.router import get_provider
            name, model = self.role_models["critic" if role == "plan_critic" else role]
            self.providers[role] = get_provider(name, model)
        return self.providers[role]

    def _ask(self, role: str, user: str, schema: type[BaseModel]) -> tuple[BaseModel, dict]:
        p = self._provider(role)
        r = p.complete(system=SYSTEM[role], messages=[{"role": "user", "content": user}],
                       max_tokens=self.max_tokens, schema=schema)
        return r.parsed, {"role": role, "model": r.model, "usd": r.cost_usd,
                          "in": r.input_tokens, "out": r.output_tokens, "mode": r.structured_mode}

    def intake(self, state: dict) -> tuple[StrategySpec, dict]:
        allow = state["mode"] != "benchmark"
        return self._ask("intake", json.dumps({"idea": state["idea"], "answers": state.get("answers", []),
                                               "questions_allowed": allow}), StrategySpec)

    def plan(self, state: dict) -> tuple[Plan, dict]:
        extra = {"catalogue": state.get("catalogue") or tools.catalogue(), "critic_changes": (state.get("plan_review") or {}).get("changes")}
        return self._ask("planner", brief(state, extra), Plan)

    def review_plan(self, state: dict) -> tuple[PlanReview, dict]:
        return self._ask("plan_critic", brief(state), PlanReview)

    def research(self, state: dict) -> tuple[RoundProposal, dict]:
        cat = {t: c for t, c in (state.get("catalogue") or tools.catalogue()).items()
               if t in state["plan"]["templates"]}
        return self._ask("researcher", brief(state, {"catalogue": cat}), RoundProposal)

    def critique(self, state: dict) -> tuple[CriticReview, dict]:
        return self._ask("critic", brief(state), CriticReview)

    def report(self, state: dict, facts: dict, fix: list[str] | None = None) -> tuple[Report, dict]:
        msg = {"facts": facts}
        if fix:
            msg["fix"] = f"These numbers are not in the facts; remove or correct them: {fix}"
        return self._ask("reporter", json.dumps(msg, default=str), Report)


class OfflineAgents:
    """Deterministic stand-in for every role (tests, CI, the zero-dependency path)."""

    STYLE_TEMPLATES: ClassVar[dict[str, list[str]]] = {"continuation": ["ema_cross", "donchian_breakout"],
                       "reversal": ["rsi_reversion", "bollinger_reversion"],
                       "pullback": ["fib_pullback"], "unsure": ["ema_cross", "rsi_reversion"]}
    NONE: ClassVar[dict] = {"role": "offline", "model": "rules", "usd": 0.0, "in": 0, "out": 0, "mode": "none"}

    def intake(self, state: dict) -> tuple[StrategySpec, dict]:
        idea = state["idea"].lower()
        style = ("reversal" if any(w in idea for w in ("dip", "oversold", "revers", "rsi"))
                 else "pullback" if any(w in idea for w in ("pullback", "retrace", "fib"))
                 else "continuation" if any(w in idea for w in ("trend", "breakout", "momentum", "ema"))
                 else "unsure")
        return StrategySpec(style=style, summary=state["idea"]), self.NONE

    def plan(self, state: dict) -> tuple[Plan, dict]:
        style = state["spec"]["style"]
        return Plan(hypothesis=state["spec"]["summary"], templates=self.STYLE_TEMPLATES[style],
                    trial_budget=300, rounds=3, rationale="templates matching the style"), self.NONE

    def review_plan(self, state: dict) -> tuple[PlanReview, dict]:
        return PlanReview(approve=True, changes=""), self.NONE

    def research(self, state: dict) -> tuple[RoundProposal, dict]:
        led, r = state["ledger"], state["round"]
        templates = state["plan"]["templates"]
        if r == 1:
            exps = [Experiment(template=t, params={}, rationale="baseline grid") for t in templates]
            return RoundProposal(diagnosis="no results yet", hypothesis="baseline", experiments=exps), self.NONE
        best = max(led["families"], key=lambda f: f["oos_sharpe"])
        base = {k: v for k, v in best["space"].items() if k not in tools.FILTER_SPACE}
        if r == 2:
            exps = [Experiment(template=best["template"], params={**base, "trend_ema": [0, 200]},
                               rationale="add a trend filter")]
        elif r == 3:
            exps = [Experiment(template=best["template"], params={**base, "atr_stop": [0, 2.0]},
                               rationale="add an ATR stop")]
        else:
            return RoundProposal(diagnosis="done", hypothesis="", stop=True, stop_reason="plan complete"), self.NONE
        return RoundProposal(diagnosis="refine the best family", hypothesis="filters help",
                             experiments=exps, diagnose=[best["id"]]), self.NONE

    def critique(self, state: dict) -> tuple[CriticReview, dict]:
        return CriticReview(verdict="continue"), self.NONE

    def report(self, state: dict, facts: dict, fix: list[str] | None = None) -> tuple[Report, dict]:
        v = facts["verdict"]
        return Report(title=f"Study: {state['idea']}", summary=f"Verdict: {v['decision']}.",
                      findings=[f"{f['template']}: out-of-sample Sharpe {f['oos_sharpe']}"
                                for f in facts["families"][:3]],
                      verdict=v["reason"]), self.NONE
