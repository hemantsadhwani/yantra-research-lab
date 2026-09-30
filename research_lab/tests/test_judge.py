"""The veto-only LLM judge, offline with a scripted FakeProvider (no key, no network)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic")

from llm_gateway import FakeProvider
from research_lab.agents.judge import SYSTEM_PROMPT, Judge, veto_line
from research_lab.budget import Budget
from research_lab.schemas import BacktestResult, Evaluation, RankedVariant, StrategyVariant
from research_lab.schemas_llm import JudgeVerdict

REPO = Path(__file__).resolve().parents[2]
BASELINE = BacktestResult("baseline", 8.96, 19, 0.4737, 6.11, 0.791)


def _v(consistent: bool = True, risk: str = "low", plaus: int = 3,
       note: str = "ok") -> JudgeVerdict:
    return JudgeVerdict(rationale_consistent=consistent, overfit_risk=risk,
                        plausibility=plaus, note=note)


def _eval(verdict: str = "promote?", score: float = 30.0) -> Evaluation:
    return Evaluation(variant_id="v001", score=score, verdict=verdict, beats_baseline=True)


def _rv(i: int, score: float, verdict: str = "promote?") -> RankedVariant:
    vid = f"v{i:03d}"
    return RankedVariant(
        StrategyVariant(vid, {"lookback": 22.0, "z_entry": 1.95, "z_exit": 0.2,
                              "stop_pct": 2.65}, "shorter lookback: expect higher return"),
        BacktestResult(vid, 30.0, 60, 0.75, 9.0, 2.0),
        Evaluation(variant_id=vid, score=score, verdict=verdict, beats_baseline=True),
    )


# ----------------------------------------------------------------- the veto rule
def test_inconsistent_rationale_vetoes_promote():
    out = Judge.apply(_eval(), _v(consistent=False))
    assert out.verdict == "hold"
    assert out.judge["rationale_consistent"] is False
    assert out.score == 30.0                      # the arithmetic score is never touched


def test_high_overfit_vetoes_promote():
    out = Judge.apply(_eval(), _v(risk="high", note="stop_pct at range floor"))
    assert out.verdict == "hold" and out.judge["overfit_risk"] == "high"


def test_clean_verdict_leaves_promote_unchanged():
    ev = _eval()
    assert Judge.apply(ev, _v(risk="medium")) == ev
    assert Judge.apply(ev, _v()).verdict == "promote?"
    assert Judge.apply(ev, _v()).judge is None


def test_never_upgrades_hold():
    assert Judge.apply(_eval("hold"), _v(plaus=5)).verdict == "hold"


def test_reject_never_changes():
    for verdict in (_v(), _v(consistent=False), _v(risk="high")):
        assert Judge.apply(_eval("reject"), verdict).verdict == "reject"


def test_abstain_leaves_verdict_unchanged():
    assert Judge.apply(_eval(), None).verdict == "promote?"


# ----------------------------------------------------------------- abstention
def test_provider_exception_abstains_and_counts():
    judge = Judge(provider=FakeProvider([TimeoutError("slow")]))
    rv = _rv(1, 30.0)
    verdict = judge.judge(rv.variant, rv.result, BASELINE, "history")
    assert verdict is None
    assert judge.judge_failures == 1 and judge.judge_calls == 0
    assert Judge.apply(rv.evaluation, verdict) == rv.evaluation


def test_schema_garbage_twice_abstains():
    fake = FakeProvider(["not json", '{"rationale_consistent": "maybe"}'])
    judge = Judge(provider=fake)
    rv = _rv(1, 30.0)
    assert judge.judge(rv.variant, rv.result, BASELINE, "history") is None
    assert len(fake.calls) == 2                    # the gateway's one repair was attempted
    assert judge.judge_failures == 1


def test_plausibility_and_note_are_bounded():
    with pytest.raises(ValueError):
        JudgeVerdict(rationale_consistent=True, overfit_risk="low", plausibility=6, note="")
    with pytest.raises(ValueError):
        JudgeVerdict(rationale_consistent=True, overfit_risk="low", plausibility=3,
                     note="x" * 301)


# ----------------------------------------------------------------- top-k, prompt, budget
def test_only_top_k_promote_candidates_are_judged():
    ranked = [_rv(1, 20.0), _rv(2, 40.0), _rv(3, 35.0, "hold"), _rv(4, 30.0), _rv(5, 25.0)]
    fake = FakeProvider([_v(risk="high"), _v()])
    judge = Judge(provider=fake, top_k=2)
    out = judge.review(ranked, BASELINE, "history")
    assert len(fake.calls) == 2
    judged = [c["messages"][0]["content"] for c in fake.calls]
    assert '"v002"' in judged[0] and '"v004"' in judged[1]      # by score, promote? only
    assert [rv.evaluation.verdict for rv in out] == ["promote?", "hold", "hold",
                                                     "promote?", "promote?"]
    assert judge.vetoes and judge.vetoes[0][0] == "v002"
    assert [rv.variant.id for rv in out] == [rv.variant.id for rv in ranked]   # order kept


def test_prompt_is_cacheable_and_states_the_rubric():
    fake = FakeProvider([_v(), _v()])
    judge = Judge(provider=fake, top_k=2)
    judge.review([_rv(1, 40.0), _rv(2, 30.0)], BASELINE, "history")
    assert fake.calls[0]["system"] == fake.calls[1]["system"] == SYSTEM_PROMPT
    assert all(c["cache_system"] for c in fake.calls)
    assert "v001" not in SYSTEM_PROMPT                         # variant details in the user turn
    for needle in ("0.5 * max_drawdown_pct", "stop_pct", "[0.5, 6.0]", "boundary", "trades"):
        assert needle in SYSTEM_PROMPT


def test_judge_charges_the_shared_budget():
    budget = Budget(max_llm_calls=10)
    judge = Judge(provider=FakeProvider([_v(), _v()], cost_per_call=0.001), top_k=2,
                  budget=budget)
    judge.review([_rv(1, 40.0), _rv(2, 30.0)], BASELINE, "history")
    assert budget.llm_calls == 2 and budget.spent_usd == pytest.approx(0.002)
    assert judge.judge_calls == 2


def test_exhausted_budget_abstains_without_calling():
    fake = FakeProvider([_v(risk="high")])
    budget = Budget(max_llm_calls=3, llm_calls=3)
    judge = Judge(provider=fake, top_k=3, budget=budget)
    out = judge.review([_rv(1, 40.0)], BASELINE, "history")
    assert fake.calls == []
    assert judge.judge_failures == 1 and out[0].evaluation.verdict == "promote?"


def test_veto_line_format():
    line = veto_line("v012", _v(risk="high", note="stop_pct at range floor").model_dump())
    assert line == "judge: v012 promote? → hold (overfit_risk=high: stop_pct at range floor)"


def test_demo_prints_a_veto_line(capsys):
    """``pytest -s -k demo`` shows the console line the CLIs print for a veto."""
    judge = Judge(provider=FakeProvider([_v(risk="high", note="stop_pct at range floor")]))
    judge.review([_rv(12, 40.0)], BASELINE, "history")
    vid, verdict = judge.vetoes[0]
    print(veto_line(vid, verdict))
    assert "judge: v012 promote? → hold (overfit_risk=high" in capsys.readouterr().out


# ----------------------------------------------------------------- stdlib arm
def test_supervisor_applies_judge_after_the_loop():
    from research_lab.supervisor import Supervisor

    fake = FakeProvider([_v(risk="high")] * 3)
    judge = Judge(provider=fake, top_k=3)
    run = Supervisor(seed=3, judge=judge).run(iterations=2, variants_per_iter=3)
    assert len(fake.calls) == 3 and len(judge.vetoes) == 3
    assert not any(rv.evaluation.verdict == "promote?" for rv in run.ranked)
    scores = [rv.evaluation.score for rv in run.ranked]
    assert scores == sorted(scores, reverse=True)


# ----------------------------------------------------------------- graph arm
def _graph_run(verdicts):
    pytest.importorskip("langgraph")
    from langgraph.checkpoint.memory import InMemorySaver

    from research_lab.graph import build_graph, initial_state

    fake = FakeProvider(verdicts)
    graph = build_graph(InMemorySaver(), judge_provider=fake)
    cfg = {"configurable": {"thread_id": "j"}}
    out = graph.invoke(initial_state(seed=3, iterations=2, variants_per_iter=3, judge=True),
                       cfg)
    return graph, cfg, out, fake


def test_graph_all_vetoed_finalizes_without_interrupt():
    graph, cfg, out, fake = _graph_run([_v(risk="high", note="boundary")] * 3)
    assert "__interrupt__" not in out
    assert graph.get_state(cfg).next == ()
    assert out["judge_vetoes"] == len(fake.calls) == 3
    assert out["judge_calls"] == 3 and out["judge_failures"] == 0
    assert out["llm_calls"] == 3                       # shared budget counts judge calls
    assert not any(d["evaluation"]["verdict"] == "promote?" for d in out["ranked"])
    vetoed = [d for d in out["ranked"] if d["evaluation"].get("judge")]
    assert len(vetoed) == 3 and out["approval"] is None


def test_graph_clean_verdicts_still_interrupt():
    graph, cfg, out, fake = _graph_run([_v()] * 3)
    assert "__interrupt__" in out
    assert graph.get_state(cfg).next == ("gate",)
    assert out["judge_vetoes"] == 0 and len(fake.calls) == 3


def test_graph_without_judge_flag_never_calls_the_judge():
    pytest.importorskip("langgraph")
    from langgraph.checkpoint.memory import InMemorySaver

    from research_lab.graph import build_graph, initial_state

    fake = FakeProvider([])
    graph = build_graph(InMemorySaver(), judge_provider=fake)
    out = graph.invoke(initial_state(seed=3, iterations=2, variants_per_iter=3),
                       {"configurable": {"thread_id": "n"}})
    assert "__interrupt__" in out and fake.calls == []


# ----------------------------------------------------------------- golden set
def test_golden_set_loads_and_validates():
    from eval.judge_eval import load_golden
    from synthetic_engine import PARAM_SPACE

    rows = load_golden()
    assert len(rows) == 12 and len({r["id"] for r in rows}) == 12
    for r in rows:
        JudgeVerdict(**r["expected"], plausibility=3, note="")
        for k, val in r["variant"]["params"].items():
            lo, hi = PARAM_SPACE[k]
            assert lo <= val <= hi
    assert sum(not r["expected"]["rationale_consistent"] for r in rows) == 3
    assert sum(r["expected"]["overfit_risk"] == "high" for r in rows) == 5


def test_judge_eval_fake_mode_exits_zero():
    out = subprocess.run([sys.executable, "-m", "eval.judge_eval", "--fake"], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8", check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "case agreement (veto-relevant): 12/12" in out.stdout


def test_vetoed_top_scorer_does_not_hide_the_runner_up():
    """If the judge vetoes #1 but #2 survives, the human gate must still fire on #2."""
    pytest.importorskip("langgraph")
    from research_lab.graph import best_candidate

    ranked = [
        {"variant": {"id": "v001"}, "evaluation": {"score": 30.0, "verdict": "hold"}},
        {"variant": {"id": "v002"}, "evaluation": {"score": 25.0, "verdict": "promote?"}},
        {"variant": {"id": "v003"}, "evaluation": {"score": 20.0, "verdict": "promote?"}},
    ]
    best = best_candidate(ranked)
    assert best is not None and best["variant"]["id"] == "v002"
    assert best_candidate([ranked[0]]) is None
