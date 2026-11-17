"""The supervisor: a LangGraph StateGraph that routes the agents, enforces the stop rules, opens
the holdout once and stops for a human before anything is promoted.

    intake ─(questions?)→ ask ─→ intake
      └→ plan → review_plan ─(revise once)→ plan
                  └→ data → research → run → critique → decide ─→ research   (next round)
                                                          └→ finalize → report → gate → END

Round 1 is the baseline (each planned template's full grid, by code); the researcher refines from
round 2, so a plan always has at least 2 rounds and a budget of baseline + 40 trials or more.

Agents decide (what to ask, plan, test, believe); code verifies (clamping, trials, walk-forward,
the sealed holdout, numbers in the report). State is plain JSON, so any checkpointer works.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from research_bench import checker, tools

MAX_ROUNDS = 6
NO_GAIN_ROUNDS = 2
MIN_GAIN = 0.05


class State(TypedDict, total=False):
    idea: str
    mode: str                 # "interactive" | "benchmark"
    source: str
    answers: list[str]
    intake_turns: int
    spec: dict
    plan: dict
    plan_review: dict
    plan_revisions: int
    card: dict
    ledger: dict
    round: int
    proposals: list[dict]
    reviews: list[dict]
    best_history: list[float]
    stop_reason: str
    holdout: dict
    verdict: dict
    report: dict
    report_check: dict
    human: str
    spend: dict
    budget_usd: float
    log: list[str]
    catalogue: dict
    study: str
    protocol_text: str
    bar: dict


def new_state(idea: str, source: str, mode: str = "interactive", budget_usd: float = 0.05) -> State:
    return State(idea=idea, source=source, mode=mode, answers=[], intake_turns=0, plan_revisions=0,
                 ledger={"families": [], "trials": 0, "looks": 0, "diagnostics": {}, "neighbourhood": {},
                         "dropped": []},
                 round=1, proposals=[], reviews=[], best_history=[], spend={"usd": 0.0, "calls": []},
                 budget_usd=budget_usd, log=[])


def _spent(s: State, use: dict) -> dict:
    sp = s["spend"]
    return {"usd": round(sp["usd"] + use["usd"], 6), "calls": [*sp["calls"], use]}


def _over_budget(s: State) -> bool:
    return s["spend"]["usd"] >= s["budget_usd"]


def build(agents: Any, checkpointer: Any = None, engine: Any = None, study: str | None = None):
    """``engine``: LocalEngine by default, or MCPEngine for a (private) MCP server. ``study`` names
    the run for the engine's holdout seal (a fresh id when not given)."""
    import uuid

    from research_bench.engine import LocalEngine
    eng = engine or LocalEngine()
    study_id = study or uuid.uuid4().hex[:12]

    from research_bench.agents import OfflineAgents
    fallback = OfflineAgents()

    def call(role: str, s: State, *args: Any, **kw: Any) -> tuple[Any, dict]:
        """Unusable model output (bad schema, provider error) falls back to the deterministic
        policy AND is recorded as a failure, so a degraded run never looks like a clean one."""
        try:
            return getattr(agents, role)(s, *args, **kw)
        except Exception as e:  # any model or provider failure takes the same path
            if isinstance(agents, OfflineAgents):
                raise
            out, use = getattr(fallback, role)(s, *args, **kw)
            return out, {**use, "role": role, "failure": f"{type(e).__name__}: {str(e)[:160]}"}

    def intake(s: State) -> dict:
        cat = s.get("catalogue") or eng.catalogue()
        spec, use = call("intake", {**s, "catalogue": cat})
        proto = s.get("protocol_text") or eng.protocol(s["source"], 0)["text"]
        return {"spec": spec.model_dump(), "spend": _spent(s, use), "intake_turns": s["intake_turns"] + 1,
                "catalogue": cat, "study": s.get("study") or study_id, "protocol_text": proto}

    def ask(s: State) -> dict:
        answers = interrupt({"questions": s["spec"]["questions"]})
        return {"answers": [*s["answers"], *([answers] if isinstance(answers, str) else answers)]}

    def after_intake(s: State) -> str:
        wants = s["spec"]["questions"] and s["mode"] == "interactive" and s["intake_turns"] < 2
        return "ask" if wants else "plan"

    def plan(s: State) -> dict:
        p, use = call("plan", s)
        cat = s["catalogue"]
        templates = [t for t in p.templates if t in cat] or [next(iter(cat))]
        baseline = sum(tools.n_trials(tools.clamp(t, {}, cat)[0]) for t in templates)
        return {"plan": {**p.model_dump(), "templates": templates, "rounds": min(max(p.rounds, 2), MAX_ROUNDS),
                         "trial_budget": max(p.trial_budget, baseline + 40)}, "spend": _spent(s, use)}

    def review_plan(s: State) -> dict:
        r, use = call("review_plan", s)
        return {"plan_review": r.model_dump(), "spend": _spent(s, use),
                "plan_revisions": s["plan_revisions"] + (0 if r.approve else 1)}

    def after_review(s: State) -> str:
        return "plan" if (not s["plan_review"]["approve"] and s["plan_revisions"] <= 1) else "data"

    def data(s: State) -> dict:
        c = eng.dataset_card(s["source"])
        line = (f"data {s['source']}: {c['rows']} rows, checks "
                f"{'passed' if c['passed'] else 'FAILED'}, sha {c['sha256']}")
        return {"card": c, "log": [*s["log"], line]}

    def research(s: State) -> dict:
        if _over_budget(s):
            return {"stop_reason": "budget"}
        if s["round"] == 1:
            # Coverage before refinement: the first look is each planned template's full grid,
            # filters off, run by code. Models open with textbook values (RSI 14) and miss the
            # rest of the space; the agents refine from a baseline instead of guessing one.
            exps = [{"template": t, "params": {}, "rationale": "baseline: full template grid, filters off"}
                    for t in s["plan"]["templates"]]
            return {"proposals": [*s["proposals"], {"round": 1, "diagnosis": "no results yet",
                                                     "hypothesis": "baseline", "experiments": exps,
                                                     "diagnose": [], "stop": False, "stop_reason": ""}]}
        p, use = call("research", s)
        return {"proposals": [*s["proposals"], {"round": s["round"], **p.model_dump()}],
                "spend": _spent(s, use)}

    def run(s: State) -> dict:
        if s.get("stop_reason"):
            return {}
        prop = s["proposals"][-1]
        led = {**s["ledger"], "families": list(s["ledger"]["families"]),
               "diagnostics": dict(s["ledger"]["diagnostics"]), "dropped": list(s["ledger"]["dropped"])}
        budget = s["plan"]["trial_budget"]
        round_left = tools.ROUND_TRIAL_CAP
        seen = {(f["template"], str(f["space"])) for f in led["families"]}
        for e in prop["experiments"]:
            if e["template"] not in s["plan"]["templates"]:
                led["dropped"].append(f"round {s['round']}: {e['template']} not in plan")
                continue
            sub, dropped = tools.clamp(e["template"], e["params"], s["catalogue"])
            led["dropped"] += [f"round {s['round']}: {d}" for d in dropped]
            n = tools.n_trials(sub)
            if (e["template"], str(sub)) in seen:
                led["dropped"].append(f"round {s['round']}: repeat of an earlier family")
                continue
            if n > round_left or led["trials"] + n > budget:
                led["dropped"].append(f"round {s['round']}: {e['template']} needs {n} trials, over budget")
                continue
            fid = f"F{len(led['families']) + 1}"
            led["families"].append(eng.run_family(s["source"], e["template"], sub, fid, s["round"]))
            led["trials"] += n
            led["looks"] += 1
            round_left -= n
            seen.add((e["template"], str(sub)))
        by_id = {f["id"]: f for f in led["families"]}
        for fid in prop.get("diagnose", []):
            if fid in by_id and fid not in led["diagnostics"]:
                led["diagnostics"][fid] = eng.diagnostics(s["source"], by_id[fid])
        best = max((tools.score(f) for f in led["families"]), default=float("-inf"))
        bar = eng.protocol(s["source"], led["looks"])
        return {"ledger": led, "best_history": [*s["best_history"], best],
                "bar": {"required_now": bar["required_now"], "required_next": bar["required_next"]}}

    def critique(s: State) -> dict:
        if s.get("stop_reason") or not s["ledger"]["families"] or _over_budget(s):
            return {}
        r, use = call("critique", s)
        led = {**s["ledger"], "neighbourhood": dict(s["ledger"]["neighbourhood"])}
        by_id = {f["id"]: f for f in led["families"]}
        for fid in r.check:
            if fid in by_id and fid not in led["neighbourhood"]:
                led["neighbourhood"][fid] = eng.neighbourhood(s["source"], by_id[fid])
        return {"reviews": [*s["reviews"], {"round": s["round"], **r.model_dump()}],
                "ledger": led, "spend": _spent(s, use)}

    def decide(s: State) -> dict:
        if s.get("stop_reason"):
            return {}
        reason = None
        prop = s["proposals"][-1] if s["proposals"] else {}
        h = s["best_history"]
        if prop.get("stop"):
            reason = f"researcher: {prop.get('stop_reason') or 'nothing left to try'}"
        elif s["reviews"] and s["reviews"][-1]["round"] == s["round"] and s["reviews"][-1]["verdict"] == "stop":
            reason = "critic: further rounds would fit noise"
        elif s["round"] >= s["plan"]["rounds"]:
            reason = "planned rounds done"
        elif s["ledger"]["trials"] >= s["plan"]["trial_budget"]:
            reason = "trial budget used"
        elif len(h) > NO_GAIN_ROUNDS and h[-1] - h[-1 - NO_GAIN_ROUNDS] < MIN_GAIN:
            reason = f"no gain in {NO_GAIN_ROUNDS} rounds"
        elif _over_budget(s):
            reason = "budget"
        return {"stop_reason": reason} if reason else {"round": s["round"] + 1}

    def after_decide(s: State) -> str:
        return "finalize" if s.get("stop_reason") else "research"

    def finalize(s: State) -> dict:
        bar = eng.protocol(s["source"], s["ledger"]["looks"])["required_now"]
        fails = sum(1 for c in s["spend"]["calls"] if c.get("failure"))
        metric = "OOS score" if any("score" in f for f in s["ledger"]["families"]) else "OOS Sharpe"
        passed = [f for f in s["ledger"]["families"] if f["passed_walk_forward"] and tools.score(f) >= bar]
        if not passed:
            return {"verdict": {"decision": "reject", "family": None, "required_oos_sharpe": bar,
                                "agent_failures": fails,
                                "reason": f"no family cleared walk-forward at the bar for "
                                          f"{s['ledger']['looks']} looks ({metric} >= {bar}); holdout left sealed"}}
        best = max(passed, key=tools.score)
        ho = eng.open_holdout(s["source"], best, s["study"])    # the only read; the engine seals it
        decision = "promote?" if ho["passed"] else "reject"
        reason = (f"{best['id']} passed walk-forward ({metric} {tools.score(best)}) and the holdout "
                  f"(Sharpe {ho['sharpe']})" if ho["passed"] else
                  f"{best['id']} passed walk-forward ({metric} {tools.score(best)}) but failed the holdout "
                  f"(Sharpe {ho['sharpe']})")
        return {"holdout": ho, "verdict": {"decision": decision, "reason": reason, "family": best["id"],
                                           "required_oos_sharpe": bar, "agent_failures": fails}}

    def report(s: State) -> dict:
        if s["mode"] == "benchmark":
            return {}
        facts = {"idea": s["idea"], "plan": s["plan"], "dataset": s["card"],
                 "families": sorted(s["ledger"]["families"], key=tools.score, reverse=True)[:5],
                 "trials": s["ledger"]["trials"], "walk_forward_looks": s["ledger"]["looks"],
                 "diagnostics": s["ledger"]["diagnostics"], "neighbourhood": s["ledger"]["neighbourhood"],
                 "holdout": s.get("holdout"), "verdict": s["verdict"], "stop_reason": s["stop_reason"],
                 "cost_usd": s["spend"]["usd"]}
        rep, use = call("report", s, facts)
        spend = _spent(s, use)
        text = " ".join([rep.title, rep.summary, *rep.findings, rep.verdict])
        bad = checker.unsupported(text, facts)
        if bad:
            rep, use = call("report", s, facts, fix=bad)
            spend = {"usd": round(spend["usd"] + use["usd"], 6), "calls": [*spend["calls"], use]}
            bad = checker.unsupported(" ".join([rep.title, rep.summary, *rep.findings, rep.verdict]), facts)
        return {"report": rep.model_dump(), "report_check": {"unsupported_numbers": bad, "passed": not bad},
                "spend": spend}

    def gate(s: State) -> dict:
        if s["mode"] == "benchmark" or s["verdict"]["decision"] != "promote?":
            return {}
        decision = interrupt({"verdict": s["verdict"], "holdout": s.get("holdout")})
        return {"human": str(decision)}

    g = StateGraph(State)
    for name, fn in [("intake", intake), ("ask", ask), ("plan", plan), ("review_plan", review_plan),
                     ("data", data), ("research", research), ("run", run), ("critique", critique),
                     ("decide", decide), ("finalize", finalize), ("report", report), ("gate", gate)]:
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", after_intake, {"ask": "ask", "plan": "plan"})
    g.add_edge("ask", "intake")
    g.add_edge("plan", "review_plan")
    g.add_conditional_edges("review_plan", after_review, {"plan": "plan", "data": "data"})
    g.add_edge("data", "research")
    g.add_edge("research", "run")
    g.add_edge("run", "critique")
    g.add_edge("critique", "decide")
    g.add_conditional_edges("decide", after_decide, {"research": "research", "finalize": "finalize"})
    g.add_edge("finalize", "report")
    g.add_edge("report", "gate")
    g.add_edge("gate", END)
    return g.compile(checkpointer=checkpointer)
