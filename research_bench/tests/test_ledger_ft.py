"""Learn from the ledger, offline: seed separation, code labels, the dataset hash and the spend cap.
No GPU, no network, no AWS credentials."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("langgraph")

from llm_gateway import FakeProvider
from research_bench.ledger_ft import dataset, label, seeds, teacher
from research_bench.ledger_ft import evaluate as ev
from research_bench.ledger_ft.harness import ResearcherOnly, run_study
from research_bench.ledger_ft.spend import (
    BudgetExceeded,
    CappedProvider,
    SpendLedger,
    worst_case_usd,
)
from research_bench.schemas import Experiment, RoundProposal


# ---------- seed separation ----------
@pytest.mark.parametrize("bad", [1, 5, 12, 20, 0, 999, -3])
def test_benchmark_and_low_seeds_are_refused_everywhere_but_the_final_eval(bad: int) -> None:
    with pytest.raises(seeds.SeedLeak):
        seeds.require_calibration(bad)
    with pytest.raises(seeds.SeedLeak):
        seeds.calibration_case(bad)


def test_calibration_cases_are_half_edge_half_noise_and_benchmark_cases_are_1_to_20() -> None:
    cases = seeds.calibration_cases(1000, 1016)
    assert [k for k, _ in cases].count("noise") == 8 and all(s >= 1000 for _, s in cases)
    assert sorted(s for _, s in seeds.benchmark_cases()) == list(range(1, 21))
    with pytest.raises(seeds.SeedLeak):
        seeds.require_benchmark(1000)


def _trace(seed=1004, kind="trend", promote=True, families=None, proposals=None, **kw) -> dict:
    return {"seed": seed, "kind": kind, "truth": "edge" if kind != "noise" else "no_edge",
            "source": f"synthetic:{kind}:{seed}", "promote": promote, "families": families or [],
            "proposals": proposals or [], "agent_failures": 0, **kw}


def _fam(fid, rnd, oos, passed=True) -> dict:
    return {"id": fid, "round": rnd, "oos_sharpe": oos, "passed_walk_forward": passed, "trials": 16}


def _prop(rnd, stop=False, user="brief") -> dict:
    return {"round": rnd, "user": user, "model": "deepseek.v3.2", "usd": 0.001, "mode": "native",
            "output": {"diagnosis": "d", "hypothesis": "h", "experiments": [], "diagnose": [],
                       "stop": stop, "stop_reason": ""}}


def test_a_benchmark_seed_in_any_trace_or_dataset_is_refused(tmp_path, monkeypatch) -> None:
    leak = _trace(seed=12, kind="noise", promote=False)
    with pytest.raises(seeds.SeedLeak):
        label.label_trace(leak)
    with pytest.raises(seeds.SeedLeak):
        dataset.records_from([leak], "sys")
    monkeypatch.setattr(teacher, "TRACES", tmp_path)
    (tmp_path / "pilot.jsonl").write_text(json.dumps(leak) + "\n", encoding="utf-8")
    with pytest.raises(seeds.SeedLeak):
        teacher.load_traces()


def test_eval_seeds_may_not_overlap_the_training_seeds(tmp_path) -> None:
    t = _trace(families=[_fam("F1", 1, 0.2, False), _fam("F2", 2, 0.9)], proposals=[_prop(2)])
    m = dataset.build([t], tmp_path)
    (tmp_path / "ad").mkdir()
    (tmp_path / "ad" / "training_meta.json").write_text(json.dumps(
        {"manifest": str(tmp_path / "manifest.json"), "dataset": str(tmp_path / "train.jsonl"),
         "dataset_sha256": m["sha256"], "base": "b"}), encoding="utf-8")
    assert ev.check_adapter(str(tmp_path / "ad"), [1900, 1901])["records"] == 1
    with pytest.raises(ValueError, match="overlap"):
        ev.check_adapter(str(tmp_path / "ad"), [1004])


def test_final_eval_runs_once_per_tag(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    (tmp_path / "final_eval_base.started").write_text("x", encoding="utf-8")
    assert ev.main(["--final", "--model", "m", "--cap", "0.1"]) == 2


# ---------- labels ----------
def test_edge_win_when_a_new_family_clears_the_raised_bar() -> None:
    # 3 looks after round 2 -> bar = 0.4 + 0.1*log2(3) = 0.558
    t = _trace(families=[_fam("F1", 1, 0.3), _fam("F2", 1, 0.2), _fam("F3", 2, 0.56)], proposals=[_prop(2)])
    assert label.label_trace(t)[0]["label"] == "win"
    t["families"][2]["oos_sharpe"] = 0.55
    assert label.label_proposal(t["proposals"][0], t) == ("loss", "edge: new families did not clear the bar")


def test_edge_efficient_stop_is_a_win_only_if_an_earlier_family_cleared() -> None:
    t = _trace(families=[_fam("F1", 1, 0.8)], proposals=[_prop(2, stop=True)])
    assert label.label_proposal(t["proposals"][0], t)[0] == "win"
    t["families"][0]["oos_sharpe"] = 0.1
    assert label.label_proposal(t["proposals"][0], t)[0] == "loss"


def test_noise_win_only_for_a_stop_with_zero_new_trials() -> None:
    stop = _trace(kind="noise", seed=1002, promote=False, families=[_fam("F1", 1, 0.1, False)],
                  proposals=[_prop(2, stop=True)])
    assert label.label_trace(stop)[0]["label"] == "win"
    spend = _trace(kind="noise", seed=1002, promote=False,
                   families=[_fam("F1", 1, 0.1, False), _fam("F2", 2, 0.9)], proposals=[_prop(2)])
    assert label.label_proposal(spend["proposals"][0], spend) == ("loss", "noise: spent trials")


def test_a_wrong_verdict_makes_every_proposal_a_loss() -> None:
    t = _trace(kind="noise", seed=1002, promote=True, families=[_fam("F1", 1, 0.9)], proposals=[_prop(2, stop=True)])
    assert label.label_proposal(t["proposals"][0], t) == ("loss", "study verdict wrong")


# ---------- dataset ----------
def test_dataset_keeps_only_wins_from_clean_studies_and_its_hash_is_stable(tmp_path) -> None:
    win = _trace(families=[_fam("F1", 1, 0.2, False), _fam("F2", 2, 0.9)], proposals=[_prop(2, user="A")])
    loss = _trace(seed=1008, families=[_fam("F1", 1, 0.2, False), _fam("F2", 2, 0.1, False)],
                  proposals=[_prop(2, user="B")])
    degraded = {**_trace(seed=1012, families=[_fam("F1", 1, 0.2, False), _fam("F2", 2, 0.9)],
                         proposals=[_prop(2, user="C")]), "agent_failures": 1}
    m1 = dataset.build([win, loss, degraded], tmp_path / "a")
    m2 = dataset.build([degraded, loss, win], tmp_path / "b")
    assert m1["records"] == 1 and m1["sha256"] == m2["sha256"] and m1["seeds"]["min"] >= 1000
    rec = dataset.verify(tmp_path / "a" / "train.jsonl", m1)[0]
    assert [m["role"] for m in rec["messages"]] == ["system", "user", "assistant"]
    assert rec["messages"][1]["content"] == "A" and json.loads(rec["messages"][2]["content"])["stop"] is False
    (tmp_path / "a" / "train.jsonl").write_bytes((tmp_path / "a" / "train.jsonl").read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash"):
        dataset.verify(tmp_path / "a" / "train.jsonl", m1)


def test_training_prompt_is_the_serving_prompt() -> None:
    from llm_gateway.base import schema_instruction
    from research_bench.agents import SYSTEM
    assert dataset.system_prompt() == SYSTEM["researcher"] + schema_instruction(RoundProposal)


# ---------- spend cap ----------
def _deepseek(cost: float, n: int = 20) -> FakeProvider:
    return FakeProvider([RoundProposal(diagnosis="d", hypothesis="h")] * n, model="deepseek.v3.2",
                        cost_per_call=cost)


def test_cap_refuses_before_the_call_and_logs_every_call(tmp_path) -> None:
    led = SpendLedger(tmp_path / "s.jsonl", total_cap=5.0, stage_caps={"pilot": 0.03})
    inner = _deepseek(0.004)
    p = CappedProvider(inner, led, "pilot", "researcher", "s1")
    kw = {"system": "s" * 2000, "messages": [{"role": "user", "content": "u" * 4000}], "max_tokens": 900,
          "schema": RoundProposal}
    est = worst_case_usd("deepseek.v3.2", **kw)
    made = 0
    with pytest.raises(BudgetExceeded):
        while True:
            p.complete(**kw)
            made += 1
    assert made == inner.round_trips and made >= 1
    assert led.spent("pilot") + est > 0.03                      # the refused call could have passed the cap
    assert led.spent("pilot") <= 0.03
    rows = [json.loads(x) for x in (tmp_path / "s.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == made and all(r["usd"] == 0.004 and r["role"] == "researcher" for r in rows)
    assert SpendLedger(tmp_path / "s.jsonl", stage_caps={"pilot": 0.03}).spent() == pytest.approx(0.004 * made)


def test_total_cap_binds_across_stages_and_a_failed_call_is_charged_in_full(tmp_path) -> None:
    led = SpendLedger(tmp_path / "s.jsonl", total_cap=0.02, stage_caps={"a": 1.0, "b": 1.0})
    kw = {"system": "s", "messages": [{"role": "user", "content": "u" * 3000}], "max_tokens": 900, "schema": None}
    boom = FakeProvider([RuntimeError("throttled")], model="deepseek.v3.2")
    with pytest.raises(RuntimeError):
        CappedProvider(boom, led, "a", "critic").complete(**kw)
    assert led.spent("a") == pytest.approx(worst_case_usd("deepseek.v3.2", **kw), abs=1e-6)
    with pytest.raises(BudgetExceeded):
        for _ in range(20):
            CappedProvider(FakeProvider(["x"], model="deepseek.v3.2", cost_per_call=0.002), led, "b", "c").complete(**kw)
    assert led.spent() <= 0.02


def test_unknown_or_uncapped_spend_is_refused(tmp_path) -> None:
    led = SpendLedger(tmp_path / "s.jsonl", stage_caps={"pilot": 0.5})
    kw = {"system": "s", "messages": [], "max_tokens": 10}
    with pytest.raises(BudgetExceeded, match="price"):
        CappedProvider(FakeProvider(["x"], model="mystery-1"), led, "pilot", "r").complete(**kw)
    with pytest.raises(BudgetExceeded, match="no cap"):
        CappedProvider(_deepseek(0.0), led, "nostage", "r").complete(**kw)


# ---------- the harness, offline ----------
def test_a_local_researcher_study_records_its_proposals_and_labels_them() -> None:
    props = [RoundProposal(diagnosis="d", hypothesis="h",
                           experiments=[Experiment(template="ema_cross", params={"trend_ema": [200]},
                                                   rationale="r")]),
             RoundProposal(diagnosis="d", hypothesis="h", stop=True, stop_reason="done")]
    agents = ResearcherOnly(FakeProvider(props, model="local"))
    t = run_study("trend", 1004, agents)
    assert t["proposals"] and t["proposals"][0]["round"] == 2 and t["agent_failures"] == 0
    assert t["proposals"][0]["user"].startswith("{") and '"catalogue"' in t["proposals"][0]["user"]
    assert {r["label"] for r in label.label_trace(t)} <= {"win", "loss"}


def test_the_local_provider_imports_without_torch() -> None:
    code = ("import sys; import llm_gateway.hf_local_provider, research_bench.ledger_ft.dataset; "
            "print(sorted({'torch', 'transformers', 'peft', 'bitsandbytes'} & set(sys.modules)))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_collection_counts_only_clean_wins_toward_its_target() -> None:
    win = _trace(families=[_fam("F1", 1, 0.2, False), _fam("F2", 2, 0.9)], proposals=[_prop(2)])
    degraded = {**win, "seed": 1008, "agent_failures": 1}
    cut = {**win, "seed": 1012, "cut_by_cap": True}
    assert teacher.clean_wins([win, degraded, cut]) == 1
