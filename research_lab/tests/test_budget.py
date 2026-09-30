"""Bounded autonomy, enforced: a USD / LLM-call budget stops the loop early with a reason.

Offline — a scripted FakeProvider stands in for the model; no key, no network. Also
covers the observability wrapper (no-op without logfire; attributes with a stub).
"""
from __future__ import annotations

import contextlib
import sys
import types

import pytest

from research_lab.budget import Budget


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)


# A known-good point for seed 3 (scores 'promote?'), so the gate fires after a budget stop.
GOOD = {"lookback": 69.793, "z_entry": 0.802, "z_exit": 0.924, "stop_pct": 1.921}


def _fake(calls: int, cost: float = 0.10, n: int = 3):
    pytest.importorskip("pydantic")
    from llm_gateway import FakeProvider
    from research_lab.schemas_llm import Proposal, ProposalBatch

    batch = ProposalBatch(variants=[Proposal(params=GOOD, rationale=f"idea {i}")
                                    for i in range(n)])
    return FakeProvider([batch] * calls, cost_per_call=cost)


def _graph_run(fake, **limits):
    pytest.importorskip("langgraph")
    from langgraph.checkpoint.memory import InMemorySaver

    from research_lab.graph import build_graph, initial_state

    graph = build_graph(InMemorySaver(), provider=fake)
    cfg = {"configurable": {"thread_id": "budget"}}
    out = graph.invoke(initial_state(seed=3, iterations=5, variants_per_iter=3,
                                     use_llm=True, **limits), cfg)
    return graph, cfg, out


# ------------------------------------------------------------------ Budget unit
def test_budget_dataclass():
    b = Budget(max_usd=0.15)
    assert not b.exhausted()
    b.charge(0.10)
    assert not b.exhausted()
    b.charge(0.10)
    assert b.exhausted() and b.llm_calls == 2
    assert b.footer("budget") == ("budget: $0.2000/$0.1500 · llm calls 2/∞ · "
                                  "stopped: budget ($0.2000 ≥ $0.1500)")
    assert Budget().footer(None) == "budget: $0.0000/∞ · llm calls 0/∞ · stopped: iterations"
    assert Budget.from_dict(b.to_dict()) == b


# ------------------------------------------------------------------ graph arm
def test_budget_stops_loop_with_reason():
    fake = _fake(calls=5)
    graph, cfg, out = _graph_run(fake, max_usd=0.15)
    state = graph.get_state(cfg).values
    assert len(fake.calls) == 2               # $0.10, $0.20 ≥ $0.15 → no third call
    assert state["stop_reason"] == "budget"
    assert state["iteration"] == 3            # < 5: the denied batch ran heuristic, then stop
    assert state["budget_exhausted_at_iteration"] == 3
    assert state["budget"]["spent_usd"] == pytest.approx(0.20) == state["llm_cost_usd"]
    assert state["budget"]["llm_calls"] == state["llm_calls"] == 2
    assert state["llm_failures"] == 0         # a budget stop is not a failure
    from research_lab.graph import best_ranked
    assert best_ranked(state["ranked"])["evaluation"]["verdict"] == "promote?"
    assert "__interrupt__" in out             # the human gate still fires
    assert graph.get_state(cfg).next == ("gate",)


def test_budget_stop_keeps_reason_through_finalize():
    pytest.importorskip("langgraph")
    from langgraph.types import Command

    fake = _fake(calls=5)
    graph, cfg, _ = _graph_run(fake, max_usd=0.15)
    final = graph.invoke(Command(resume="reject"), cfg)
    assert final["stop_reason"] == "budget"


def test_max_llm_calls_stops_loop():
    fake = _fake(calls=5)
    graph, cfg, _ = _graph_run(fake, max_llm_calls=1)
    state = graph.get_state(cfg).values
    assert len(fake.calls) == 1
    assert state["stop_reason"] == "budget"
    assert state["iteration"] == 2
    assert all("llm[" not in p["rationale"] for p in state["proposals"])   # heuristic batch


def test_no_budget_means_unbounded():
    fake = _fake(calls=5)
    graph, cfg, out = _graph_run(fake)
    if "__interrupt__" in out:
        from langgraph.types import Command
        out = graph.invoke(Command(resume="reject"), cfg)
    assert out["iteration"] == 5
    assert out["stop_reason"] == "iterations"
    assert len(fake.calls) == 5
    assert out["budget"]["spent_usd"] == pytest.approx(len(fake.calls) * 0.10)


def test_footer_reports_budget_stop():
    pytest.importorskip("langgraph")
    from research_lab.run_graph import budget_footer

    fake = _fake(calls=5)
    graph, cfg, _ = _graph_run(fake, max_usd=0.15)
    footer = budget_footer(graph.get_state(cfg).values)
    print(footer)
    assert footer == ("budget: $0.2000/$0.1500 · llm calls 2/∞ · "
                      "stopped: budget ($0.2000 ≥ $0.1500)")


# ------------------------------------------------------------------ stdlib arm
def test_stdlib_arm_honours_budget():
    from research_lab.agents.proposer import Proposer
    from research_lab.supervisor import Supervisor

    fake = _fake(calls=5, n=5)
    budget = Budget(max_llm_calls=1)
    sup = Supervisor(seed=3, budget=budget,
                     proposer=Proposer(seed=3, use_llm=True, provider=fake))
    run = sup.run()
    assert budget.llm_calls == 1
    assert len(fake.calls) == 1
    assert sup.stop_reason == "budget"
    assert run.iterations == 2 and run.variants_tested == 10


def test_stdlib_default_is_unchanged():
    from research_lab.supervisor import Supervisor

    a = Supervisor(seed=3).run(iterations=3, variants_per_iter=4)
    b = Supervisor(seed=3, budget=Budget()).run(iterations=3, variants_per_iter=4)
    assert [rv.variant.id for rv in a.ranked] == [rv.variant.id for rv in b.ranked]
    assert a.iterations == b.iterations == 3


# ------------------------------------------------------------------ observability
@pytest.fixture
def obs(monkeypatch):
    from research_lab import observability

    monkeypatch.setattr(observability, "_logfire", None)
    return observability


def test_observability_noop_without_logfire(obs, monkeypatch):
    monkeypatch.setitem(sys.modules, "logfire", None)     # import logfire → ImportError
    monkeypatch.setenv("LOGFIRE_TOKEN", "x")
    assert obs.configure() is False
    assert not obs.enabled()

    @obs.traced("demo")
    def node(state):
        return {"iteration": 1, "llm_cost_usd": 0.5}

    update = node({"iteration": 0})
    assert update == {"iteration": 1, "llm_cost_usd": 0.5}
    with obs.span("x", a=1) as sp:
        obs.set_attributes(sp, {"b": 2})


def test_configure_without_token_never_calls_logfire(obs, monkeypatch):
    stub = types.SimpleNamespace(configure=lambda **k: pytest.fail("configured"))
    monkeypatch.setitem(sys.modules, "logfire", stub)
    assert obs.configure() is False


class _StubLogfire(types.ModuleType):
    def __init__(self):
        super().__init__("logfire")
        self.spans: list[dict] = []
        self.configured = False

    def configure(self, **kwargs):
        self.configured = True

    def instrument_anthropic(self):
        pass

    @contextlib.contextmanager
    def span(self, name, **attrs):
        rec = {"name": name, **attrs}
        self.spans.append(rec)
        yield types.SimpleNamespace(set_attributes=rec.update,
                                    set_attribute=lambda k, v: rec.__setitem__(k, v))


def test_traced_node_sets_attributes(obs, monkeypatch):
    stub = _StubLogfire()
    monkeypatch.setitem(sys.modules, "logfire", stub)
    monkeypatch.setenv("LOGFIRE_TOKEN", "test-token")
    monkeypatch.setenv("YANTRA_ENV", "production")
    monkeypatch.delenv("YANTRA_TRACE_PARAMS", raising=False)
    assert obs.configure() is True and stub.configured

    fake = _fake(calls=5)
    _graph_run(fake, max_usd=0.15)
    names = {s["name"] for s in stub.spans}
    assert {"node.baseline", "node.propose", "node.backtest_all", "node.record",
            "node.gate"} <= names
    propose = [s for s in stub.spans if s["name"] == "node.propose"]
    assert "llm_cost_usd" in propose[0] and "spent_usd" in propose[0]
    assert propose[1]["spent_usd"] == pytest.approx(0.20)
    assert propose[-1]["stop_reason"] == "budget"
    assert propose[0]["n_variants"] == 3 and propose[0]["provider"] == "fake"
    assert all("proposals" not in s for s in stub.spans)      # privacy by default
    gate = [s for s in stub.spans if s["name"] == "node.gate"]
    assert gate[0].get("interrupted") is True


def test_configure_skipped_outside_production(obs, monkeypatch):
    """A token in a laptop's .env is not enough: local runs never export spans."""
    stub = types.SimpleNamespace(configure=lambda **k: pytest.fail("configured"))
    monkeypatch.setitem(sys.modules, "logfire", stub)
    monkeypatch.setenv("LOGFIRE_TOKEN", "abc")
    monkeypatch.delenv("YANTRA_TRACE_LOCAL", raising=False)
    for env in ("local", "test", "eval"):
        monkeypatch.setenv("YANTRA_ENV", env)
        assert obs.configure() is False
    monkeypatch.delenv("YANTRA_ENV")
    assert obs.configure() is False


def test_configure_local_opt_in_tags_environment(obs, monkeypatch):
    seen: dict = {}
    stub = _StubLogfire()
    stub.configure = lambda **k: seen.update(k)
    monkeypatch.setitem(sys.modules, "logfire", stub)
    monkeypatch.setenv("LOGFIRE_TOKEN", "abc")
    monkeypatch.setenv("YANTRA_ENV", "local")
    monkeypatch.setenv("YANTRA_TRACE_LOCAL", "1")
    assert obs.configure() is True
    assert seen["environment"] == "local"


def test_trace_params_opt_in(obs, monkeypatch):
    monkeypatch.setenv("YANTRA_TRACE_PARAMS", "1")
    attrs = obs.node_attributes({}, {"proposals": [{"id": "v1", "params": {"a": 1},
                                                    "rationale": "r"}]})
    assert "rationale" in attrs["proposals"]
    monkeypatch.delenv("YANTRA_TRACE_PARAMS")
    assert "proposals" not in obs.node_attributes({}, {"proposals": []})
