"""Persistent memory: trials survive the process, priors come from previous runs' winners,
recall is nearest-neighbour over rationale text, and only a human approval is ever
written as a promotion. Offline: hashed embedder, no network, no API key."""
from __future__ import annotations

import math

import pytest

from research_lab.agents.context import CONSTRUCTIONS, build_context
from research_lab.memory import Memory
from research_lab.memory_store import SqliteMemory
from research_lab.schemas import Evaluation, StrategyVariant
from research_lab.supervisor import Supervisor
from synthetic_engine import PARAM_SPACE, get_baseline

STRAT = "nifty-expiry"


@pytest.fixture(autouse=True)
def _hashed_embedder(monkeypatch):
    monkeypatch.setenv("YANTRA_EMBEDDER", "hashed")


def _obs(mem, vid: str, score: float, rationale: str = "test", **overrides) -> None:
    params = dict(get_baseline(STRAT))
    params.update(overrides)
    mem.observe(StrategyVariant(id=vid, params=params, rationale=rationale),
                Evaluation(variant_id=vid, score=score, verdict="hold", beats_baseline=True))


def _in_box(params, box) -> bool:
    return all(box[k][0] - 1e-9 <= params[k] <= box[k][1] + 1e-9 for k in box)


def test_trials_persist_across_instances(tmp_path):
    db = tmp_path / "m.sqlite"
    with SqliteMemory(db, STRAT, run_id="A") as m:
        _obs(m, "v001", 1.0)
        _obs(m, "v002", 5.0, lookback=12.0)
        _obs(m, "v002", 99.0)                      # duplicate id: ignored (idempotent)
    with SqliteMemory(db, STRAT, run_id="A") as m2:
        assert m2.trial_count() == 2
        assert m2.best_id() == "v002" and m2.best_score() == 5.0
        assert m2.best_params()["lookback"] == 12.0
        assert [t.variant_id for t in m2.trials()] == ["v001", "v002"]
    with SqliteMemory(db, STRAT, run_id="B") as other:
        assert other.trial_count() == 0            # Memory surface is scoped to its run
        assert {r["run_id"]: r["n_trials"] for r in other.runs()} == {"A": 2, "B": 0}


def test_priors_none_below_five_trials(tmp_path):
    db = tmp_path / "m.sqlite"
    with SqliteMemory(db, STRAT, run_id="A") as a:
        for i in range(4):
            _obs(a, f"v{i:03d}", float(i))
        assert a.priors() is None                  # own run never counts
    with SqliteMemory(db, STRAT, run_id="B") as b:
        assert b.priors() is None                  # 4 prior trials < 5


def test_priors_reflect_top_quartile_of_previous_runs(tmp_path):
    db = tmp_path / "m.sqlite"
    with SqliteMemory(db, STRAT, run_id="A") as a:
        # 8 trials -> top quartile = 2 best (scores 7 and 6: lookback 17 and 16)
        for i in range(8):
            _obs(a, f"v{i:03d}", float(i), lookback=10.0 + i, z_entry=1.0 + i / 10)
    with SqliteMemory(db, "nifty-weekday", run_id="W") as w:
        for i in range(8):                          # other strategy: must not leak
            _obs(w, f"v{i:03d}", 100.0 + i, lookback=40.0)
    with SqliteMemory(db, STRAT, run_id="B") as b:
        box = b.priors()
        assert box is not None
        assert box["lookback"] == (16.0, 17.0)
        assert box["z_entry"] == pytest.approx((1.6, 1.7))
        base = get_baseline(STRAT)
        assert box["stop_pct"] == (base["stop_pct"], base["stop_pct"])
        assert b.prior_run_count() == 1
        b.refresh_priors()
        rows = b._conn.execute("SELECT param, lo, hi, n_runs FROM priors "
                               "WHERE strategy = ? AND param = 'lookback'", (STRAT,)).fetchall()
        assert rows == [("lookback", 16.0, 17.0, 1)]


def test_second_run_explorer_samples_inside_priors(tmp_path):
    db = tmp_path / "m.sqlite"
    with SqliteMemory(db, STRAT, run_id="A") as mem_a:
        run_a = Supervisor(seed=3, strategy=STRAT, memory=mem_a).run(3, 5)
        assert run_a.variants_tested == 15
        assert mem_a.priors() is None
        assert mem_a.refresh_priors() is not None

    with SqliteMemory(db, STRAT, run_id="B") as mem_b:
        box = mem_b.priors()
        assert box is not None
        ranked = sorted(_trials_of(db, "A"), key=lambda t: -t.score)
        top = [t.params for t in ranked[:math.ceil(15 / 4)]]
        assert box == {k: (min(p[k] for p in top), max(p[k] for p in top)) for k in PARAM_SPACE}

        sup = Supervisor(seed=3, strategy=STRAT, memory=mem_b)
        first = sup.proposer.propose(5, mem_b)          # no best yet: all explorers
        from_priors = [v for v in first if "learned priors" in v.rationale]
        assert sup.proposer.used_priors >= 1
        assert len(from_priors) == sup.proposer.used_priors
        assert any(_in_box(v.params, box) for v in first)
        assert all(_in_box(v.params, box) for v in from_priors)


def _trials_of(db, run_id):
    with SqliteMemory(db, STRAT, run_id=run_id) as m:
        return m.trials()


def test_recall_similar_returns_nearest_rationale(tmp_path):
    db = tmp_path / "m.sqlite"
    with SqliteMemory(db, STRAT, run_id="A") as a:
        _obs(a, "v001", 1.0, rationale="tighten the stop loss to cut drawdown")
        _obs(a, "v002", 2.0, rationale="lengthen lookback window for slower mean reversion")
        _obs(a, "v003", 3.0, rationale="raise z entry threshold for fewer better trades")
    with SqliteMemory(db, STRAT, run_id="B") as b:
        hits = b.recall_similar("slower mean reversion with a longer lookback window", k=2)
        assert hits[0].variant_id == "v002"
        assert len(hits) == 2
        again = b.recall_similar("slower mean reversion with a longer lookback window", k=2)
        assert [t.variant_id for t in again] == [t.variant_id for t in hits]   # deterministic
        assert b.recall_similar("stop loss drawdown", k=1)[0].variant_id == "v001"
        assert b.recall_similar("anything", exclude_current_run=True, k=10) != []


def test_promotion_only_written_on_human_approval(tmp_path):
    pytest.importorskip("langgraph")
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from research_lab.graph import build_graph, initial_state

    db = tmp_path / "m.sqlite"
    graph = build_graph(InMemorySaver())

    def start(run_id: str):
        cfg = {"configurable": {"thread_id": run_id}}
        first = graph.invoke(initial_state(seed=3, iterations=5, variants_per_iter=6,
                                           memory="sqlite", memory_db=str(db),
                                           run_id=run_id), cfg)
        assert "__interrupt__" in first
        return cfg

    def promotions():
        with SqliteMemory(db, "synthetic-meanrev", run_id="probe") as m:
            return m.promotions()

    cfg = start("r-reject")
    assert promotions() == []                      # paused at gate: nothing written
    graph.invoke(Command(resume="reject"), cfg)
    assert promotions() == []

    cfg = start("r-approve")
    final = graph.invoke(Command(resume="approve"), cfg)
    rows = promotions()
    assert len(rows) == 1
    assert rows[0]["run_id"] == "r-approve"
    assert rows[0]["variant_id"] == final["promoted_id"]
    assert rows[0]["decided_by"] == "human"
    with SqliteMemory(db, "synthetic-meanrev", run_id="probe") as m:
        counts = {r["run_id"]: r["n_trials"] for r in m.runs()}
        assert counts["r-reject"] == counts["r-approve"] == 30   # record wrote through
        with pytest.raises(ValueError):
            m.record_promotion("v001", decided_by="agent")


def test_inmem_memory_unchanged():
    m = Memory()
    assert (m.best_params(), m.best_id(), m.best_score(), m.trials(), m.trial_count()) == \
        (None, None, None, [], 0)
    for vid, score in [("v001", 3.0), ("v002", 7.5), ("v003", 7.5), ("v004", -1.0)]:
        _obs(m, vid, score, lookback=10.0 + int(vid[1:]))
    assert m.best_id() == "v002"                   # ties keep the earliest
    assert m.best_score() == 7.5
    assert m.best_params()["lookback"] == 12.0
    assert m.trial_count() == 4
    assert [(t.variant_id, t.score, t.verdict) for t in m.trials()] == [
        ("v001", 3.0, "hold"), ("v002", 7.5, "hold"), ("v003", 7.5, "hold"),
        ("v004", -1.0, "hold")]
    assert not hasattr(m, "priors") and not hasattr(m, "recall_similar")


def test_context_compacted_includes_procedural_block_when_priors_exist(tmp_path):
    db = tmp_path / "m.sqlite"
    with SqliteMemory(db, STRAT, run_id="A") as a:
        for i in range(8):
            _obs(a, f"v{i:03d}", float(i), rationale="exploit near best",
                 lookback=10.0 + i)
    with SqliteMemory(db, STRAT, run_id="B") as b:
        _obs(b, "v001", 2.0, rationale="exploit near best")
        args = (b.trials(), b.best_params(), b.best_score())
        ctx = build_context("compacted", *args, memory=b)
        assert f"Across 1 prior run on {STRAT}, top variants had lookback 16–17" in ctx
        assert "Similar trials from previous runs:" in ctx
        assert ctx.count("exploit near best") >= 1
        # the other two constructions ignore cross-run memory entirely
        for c in CONSTRUCTIONS:
            if c != "compacted":
                assert build_context(c, *args, memory=b) == build_context(c, *args)
        plain = Memory()
        _obs(plain, "v001", 2.0, rationale="exploit near best")
        assert "prior run" not in build_context("compacted", plain.trials(),
                                                plain.best_params(), plain.best_score(),
                                                memory=plain)
