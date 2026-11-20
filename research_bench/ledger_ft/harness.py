"""One way to run a study, shared by the teacher, the untuned base model and the tuned student.

Two harnesses:
  ``mixed``          the v2 benchmark harness: Gemma 3 12B intake, DeepSeek V3.2 planner, plan
                     critic and critic (paid, capped); the researcher is the teacher (DeepSeek) or a
                     local model. Only the researcher differs between arms.
  ``offline-roles``  every role except the researcher is the deterministic rule policy; $0. Used
                     for the Stage 0 baseline and for smoke checks on calibration seeds.

The graph is unchanged: unusable researcher output falls back to the rule policy and is counted
(``agent_failures``), so a degraded study never looks clean. Only model-written proposals are
recorded; a fallback proposal is not a teacher sample.
"""

from __future__ import annotations

import time
from typing import Any

from research_bench import tools
from research_bench.agents import MODEL_SETS, LLMAgents, OfflineAgents
from research_bench.ledger_ft.spend import CappedProvider, SpendLedger
from research_bench.schemas import RoundProposal

ROLES = ("intake", "planner", "plan_critic", "researcher", "critic", "reporter")
STUDY_BUDGET_USD = 0.05          # the graph's own per-study cap, as in the v2 benchmark


class RecordingAgents(LLMAgents):
    """LLMAgents that records each researcher call: the exact prompt and the validated output."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.records: list[dict] = []

    def research(self, state: dict) -> tuple[RoundProposal, dict]:
        user = self.research_brief(state)
        out, use = self._ask("researcher", user, RoundProposal)
        self.records.append({"round": state["round"], "user": user, "output": out.model_dump(),
                             "model": use["model"], "usd": use["usd"], "mode": use["mode"]})
        return out, use


class ResearcherOnly:
    """The rule policy for every role except the researcher (not an OfflineAgents subclass, so
    the graph's fallback-and-count path applies to the researcher's failures)."""

    def __init__(self, researcher: Any) -> None:
        self._llm = RecordingAgents(providers={"researcher": researcher})
        self._off = OfflineAgents()
        self.records = self._llm.records

    def research(self, state: dict) -> tuple[RoundProposal, dict]:
        return self._llm.research(state)

    def __getattr__(self, role: str) -> Any:
        return getattr(self._off, role)


def mixed_agents(ledger: SpendLedger, stage: str, study: str, researcher: Any = None) -> RecordingAgents:
    """The v2 harness with every paid role behind the ledger. ``researcher``: a local provider
    (student or base); None means the teacher (DeepSeek V3.2, paid and capped)."""
    from llm_gateway.router import get_provider
    models = MODEL_SETS["mixed"]
    providers = {}
    for role in ROLES:
        name, model = models["critic" if role == "plan_critic" else role]
        providers[role] = CappedProvider(get_provider(name, model), ledger, stage, role, study)
    if researcher is not None:
        providers["researcher"] = researcher
    return RecordingAgents(providers=providers, role_models=dict(models))


def run_study(kind: str, seed: int, agents: Any) -> dict:
    """Run one benchmark-mode study and return its trace (the input of ``label.label_trace``)."""
    from eval.planted_benchmark import idea_for
    from research_bench.graph import build, new_state
    idea, _ = idea_for(kind, seed)
    source = f"synthetic:{kind}:{seed}"
    t0 = time.perf_counter()
    base = {"seed": seed, "kind": kind, "truth": "edge" if kind != "noise" else "no_edge",
            "source": source, "idea": idea}
    try:
        out = build(agents).invoke(new_state(idea, source, mode="benchmark", budget_usd=STUDY_BUDGET_USD),
                                   {"recursion_limit": 80})
    except Exception as e:  # noqa: BLE001 - a crashed study is a reject, recorded as an error
        return {**base, "promote": False, "error": f"{type(e).__name__}: {e}"[:300], "trials": 0,
                "families": [], "proposals": list(getattr(agents, "records", [])),
                "agent_failures": 0, "failures": [], "usd": 0.0,
                "seconds": round(time.perf_counter() - t0, 1)}
    led, verdict = out["ledger"], out["verdict"]
    fails = [{"role": c["role"], "failure": c["failure"]} for c in out["spend"]["calls"] if c.get("failure")]
    fams = [{k: f[k] for k in ("id", "round", "template", "space", "trials", "oos_sharpe", "positive_folds",
                               "passed_walk_forward", "score") if k in f} for f in led["families"]]
    return {**base, "promote": verdict["decision"] == "promote?", "reason": verdict["reason"],
            "templates": out["plan"]["templates"], "rounds": out["round"], "stop": out["stop_reason"],
            "trials": led["trials"], "looks": led["looks"], "refused_by_code": len(led["dropped"]),
            "best_oos_sharpe": max((tools.score(f) for f in led["families"]), default=None),
            "families": fams, "proposals": list(getattr(agents, "records", [])),
            "agent_failures": len(fails), "failures": fails,
            "model_calls": len(out["spend"]["calls"]), "usd": out["spend"]["usd"],
            "seconds": round(time.perf_counter() - t0, 1)}


def summarise(traces: list[dict]) -> dict:
    edge = [t for t in traces if t["truth"] == "edge"]
    noise = [t for t in traces if t["truth"] == "no_edge"]
    secs = sorted(t["seconds"] for t in traces)
    return {"studies": len(traces),
            "edges_recovered": f"{sum(t['promote'] for t in edge)}/{len(edge)}",
            "noise_promoted": f"{sum(t['promote'] for t in noise)}/{len(noise)}",
            "trials": sum(t["trials"] for t in traces),
            "trials_per_study": round(sum(t["trials"] for t in traces) / max(1, len(traces)), 1),
            "usd": round(sum(t.get("usd", 0.0) for t in traces), 4),
            "usd_per_study": round(sum(t.get("usd", 0.0) for t in traces) / max(1, len(traces)), 5),
            "median_seconds_per_study": secs[len(secs) // 2] if secs else None,
            "errors": sum("error" in t for t in traces),
            "researcher_calls_ok": sum(len(t["proposals"]) for t in traces),
            "agent_failures_fell_back": sum(t.get("agent_failures", 0) for t in traces)}
