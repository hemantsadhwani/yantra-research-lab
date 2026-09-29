"""The LLM proposer through the llm_gateway seam, offline with a scripted FakeProvider.

What is under test is the contract around the model: schema-validated replies are still
clamped and verified, unusable replies fall back to the heuristic AND are counted, and
the graph arm accumulates accounting across iterations.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from llm_gateway import FakeProvider
from research_lab.agents.proposer import Proposer
from research_lab.memory import Memory
from research_lab.schemas import Evaluation, StrategyVariant
from research_lab.schemas_llm import Proposal, ProposalBatch
from research_lab.verify import verify_variant
from synthetic_engine import PARAM_SPACE, get_baseline


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)


def _memory() -> Memory:
    m = Memory()
    for i in range(4):
        v = StrategyVariant(id=f"v{i:03d}", params=dict(get_baseline()), rationale="t")
        m.observe(v, Evaluation(variant_id=v.id, score=float(i), verdict="hold",
                                beats_baseline=True))
    return m


def _batch(n: int = 3, **override) -> ProposalBatch:
    params = {**get_baseline(), **override}
    return ProposalBatch(variants=[Proposal(params=params, rationale=f"idea {i}")
                                   for i in range(n)])


def test_validated_batch_is_still_clamped_and_verified():
    fake = FakeProvider([_batch(3, lookback=9999.0)], cost_per_call=0.002)
    p = Proposer(seed=0, use_llm=True, provider=fake)
    variants = p.propose(3, _memory())
    assert len(variants) == 3
    for v in variants:
        verify_variant(v)
        assert v.params["lookback"] == PARAM_SPACE["lookback"][1]
        assert v.rationale.startswith("llm[compacted]: idea")
    assert (p.llm_calls, p.llm_failures) == (1, 0)
    assert p.llm_structured_mode == "native"
    assert p.llm_cost_usd == pytest.approx(0.002)
    assert fake.calls[0]["schema"] is ProposalBatch
    assert fake.calls[0]["cache_system"] is True
    assert (p.provider_name, p.model) == ("fake", "fake-1")


def test_garbage_twice_falls_back_and_is_counted():
    p = Proposer(seed=0, use_llm=True, provider=FakeProvider(["no json", "still no json"]))
    variants = p.propose(4, _memory())
    assert len(variants) == 4
    assert (p.llm_calls, p.llm_failures) == (0, 1)
    assert all("llm[" not in v.rationale for v in variants)
    for v in variants:
        verify_variant(v)


def test_provider_exception_falls_back_and_is_counted():
    p = Proposer(seed=0, use_llm=True, provider=FakeProvider([TimeoutError("slow")]))
    assert len(p.propose(3, _memory())) == 3
    assert p.llm_failures == 1


def test_empty_batch_is_rejected_by_the_schema_and_counted():
    p = Proposer(seed=0, use_llm=True,
                 provider=FakeProvider(['{"variants": []}', '{"variants": []}']))
    assert len(p.propose(2, _memory())) == 2
    assert p.llm_failures == 1


def test_repaired_reply_is_used():
    good = _batch(2).model_dump_json()
    p = Proposer(seed=0, use_llm=True, provider=FakeProvider(["oops", good]))
    variants = p.propose(2, _memory())
    assert p.llm_failures == 0 and p.llm_structured_mode == "prompt"
    assert all(v.rationale.startswith("llm[") for v in variants)


def test_no_key_falls_back_instead_of_crashing():
    """The real anthropic provider with no key: heuristic batch, counted as a failure."""
    p = Proposer(seed=0, use_llm=True)
    assert len(p.propose(3, _memory())) == 3
    assert (p.llm_calls, p.llm_failures) == (0, 1)
    assert p.provider_name == "anthropic"


def test_graph_arm_accumulates_llm_accounting_across_iterations():
    pytest.importorskip("langgraph")
    from langgraph.checkpoint.memory import InMemorySaver

    from research_lab.graph import build_graph, initial_state

    iters, n = 3, 3
    fake = FakeProvider([_batch(n) for _ in range(iters)], cost_per_call=0.001)
    graph = build_graph(InMemorySaver(), provider=fake)
    cfg = {"configurable": {"thread_id": "llm"}}
    state = graph.invoke(initial_state(seed=3, iterations=iters, variants_per_iter=n,
                                       use_llm=True), cfg)
    assert state["llm_calls"] == iters
    assert state["llm_failures"] == 0
    assert state["llm_cost_usd"] == pytest.approx(0.003)
    assert state["llm_structured_mode"] == "native"
    assert (state["llm_provider"], state["llm_model"]) == ("fake", "fake-1")
    assert len(state["ranked"]) == iters * n
    assert len(fake.calls) == iters


def test_proposal_params_match_the_param_space():
    from research_lab.schemas_llm import ProposalParams

    assert set(ProposalParams.model_fields) == set(PARAM_SPACE)


def test_proposal_schema_survives_strict_transform():
    """Structured outputs close every object; a dict[str, float] would become ``{}``."""
    pytest.importorskip("anthropic")
    try:
        from anthropic.lib._parse._transform import transform_schema
    except ImportError:
        pytest.skip("SDK has no structured-output transform")
    strict = transform_schema(ProposalBatch.model_json_schema())
    defs = strict.get("$defs", {})
    params = defs["ProposalParams"]
    assert set(params["properties"]) == set(PARAM_SPACE)
    assert set(params["required"]) == set(PARAM_SPACE)
