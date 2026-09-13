"""The LLM proposer must not be trusted, and the cheap context must stay cheap.

These run offline — no API key, no network. The LLM path is exercised through a
fake client, because what needs testing is the code around the model (parsing,
clamping, fallback, accounting), not the model itself.
"""
from __future__ import annotations

from research_lab.agents.context import CONSTRUCTIONS, build_context
from research_lab.agents.proposer import Proposer, _clamp, _parse_proposals
from research_lab.memory import Memory
from research_lab.schemas import Evaluation, StrategyVariant
from research_lab.verify import verify_variant
from synthetic_engine import PARAM_SPACE, get_baseline

GOOD = get_baseline()


def _seed_memory(n: int = 12) -> Memory:
    m = Memory()
    for i in range(n):
        params = dict(GOOD)
        params["lookback"] = 10 + i * 0.5          # spread, stays inside the space
        v = StrategyVariant(id=f"v{i:03d}", params=params, rationale="test")
        e = Evaluation(variant_id=v.id, score=float(i), verdict="hold", beats_baseline=True)
        m.observe(v, e)
    return m


def _ctx_args(m: Memory):
    return m.trials(), m.best_params(), m.best_score()


# --------------------------------------------------------------- memory history
def test_memory_records_every_trial_without_changing_best():
    m = _seed_memory(5)
    assert m.trial_count() == 5
    assert m.best_score() == 4.0            # unchanged best-so-far semantics
    assert [t.variant_id for t in m.trials()] == [f"v{i:03d}" for i in range(5)]


def test_trials_are_copies_so_a_prompt_builder_cannot_corrupt_memory():
    m = _seed_memory(3)
    m.trials()[0].params["lookback"] = 999
    assert m.trials()[0].params["lookback"] != 999


# ------------------------------------------------------------ context builders
def test_every_construction_names_the_whole_param_space():
    m = _seed_memory()
    for c in CONSTRUCTIONS:
        ctx = build_context(c, *_ctx_args(m))
        for key in PARAM_SPACE:
            assert key in ctx, f"{c} omitted {key}"


def test_cheap_contexts_are_actually_cheaper():
    """The study is meaningless if the constructions do not differ in size."""
    m = _seed_memory(20)
    sizes = {c: len(build_context(c, *_ctx_args(m))) for c in CONSTRUCTIONS}
    assert sizes["best_only"] < sizes["compacted"] < sizes["everything"]


def test_compaction_stays_flat_as_history_grows():
    """Compaction that grows with history is not compaction."""
    small = build_context("compacted", *_ctx_args(_seed_memory(8)))
    large = build_context("compacted", *_ctx_args(_seed_memory(80)))
    assert len(large) < len(small) * 1.5
    # ...while the full dump grows roughly linearly.
    dump_small = build_context("everything", *_ctx_args(_seed_memory(8)))
    dump_large = build_context("everything", *_ctx_args(_seed_memory(80)))
    assert len(dump_large) > len(dump_small) * 5


def test_empty_memory_is_handled_by_every_construction():
    m = Memory()
    for c in CONSTRUCTIONS:
        ctx = build_context(c, *_ctx_args(m))
        assert "first batch" in ctx


def test_unknown_construction_is_rejected():
    m = Memory()
    try:
        build_context("telepathy", *_ctx_args(m))
    except ValueError as e:
        assert "telepathy" in str(e)
    else:
        raise AssertionError("an unknown construction must raise")


# -------------------------------------------------------- parsing and clamping
def test_parses_json_wrapped_in_a_code_fence():
    text = '```json\n{"variants": [{"params": {"lookback": 40}, "rationale": "x"}]}\n```'
    assert len(_parse_proposals(text)) == 1


def test_parses_json_with_preamble_prose():
    text = 'Here are my proposals:\n{"variants": [{"params": {}, "rationale": "x"}]}'
    assert len(_parse_proposals(text)) == 1


def test_unparseable_output_yields_no_proposals_rather_than_raising():
    assert _parse_proposals("I would rather not.") == []
    assert _parse_proposals('{"variants": "not a list"}') == []


def test_clamp_forces_hallucinated_params_into_the_declared_space():
    fallback = dict(GOOD)
    out = _clamp({"lookback": 9999, "z_entry": -50, "z_exit": "nonsense"}, fallback)
    for key, (lo, hi) in PARAM_SPACE.items():
        assert lo <= out[key] <= hi, f"{key}={out[key]} escaped [{lo}, {hi}]"
    assert out["lookback"] == PARAM_SPACE["lookback"][1]     # clamped to the top
    assert out["z_entry"] == PARAM_SPACE["z_entry"][0]       # clamped to the bottom
    assert out["z_exit"] == fallback["z_exit"]               # non-numeric -> fallback


def test_missing_params_fall_back_rather_than_crashing():
    out = _clamp({}, dict(GOOD))
    assert set(out) == set(PARAM_SPACE)


# ------------------------------------------------------------- the LLM path
class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 100, "output_tokens": 50,
                                    "cache_creation_input_tokens": 0,
                                    "cache_read_input_tokens": 0})()


class _FakeClient:
    """Stands in for anthropic.Anthropic — records the prompt, returns canned text."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.last_kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(self._text)


def _llm_proposer(text: str, **kw):
    p = Proposer(seed=0, use_llm=True, **kw)
    client = _FakeClient(text)
    p._client = client          # bypass _get_client: no key, no network
    return p, client


GOOD_JSON = '{"variants": [{"params": {"lookback": 40}, "rationale": "x"}]}'


def test_llm_proposals_always_survive_verification():
    """Even a model returning garbage must not produce an unverifiable variant."""
    bad = '{"variants": [{"params": {"lookback": 10000, "z_entry": -99}, "rationale": "?"}]}'
    p, _ = _llm_proposer(bad)
    for v in p.propose(3, _seed_memory()):
        verify_variant(v)       # raises if the clamp failed


def test_llm_returns_the_requested_number_of_variants():
    p, _ = _llm_proposer(GOOD_JSON)
    assert len(p.propose(4, _seed_memory())) == 4    # topped up from the heuristic


def test_unusable_output_falls_back_to_the_heuristic_and_is_counted():
    p, _ = _llm_proposer("no json here")
    variants = p.propose(3, _seed_memory())
    assert len(variants) == 3
    assert p.llm_failures == 1
    assert all("llm[" not in v.rationale for v in variants)


def test_token_accounting_accumulates():
    p, _ = _llm_proposer(GOOD_JSON)
    p.propose(1, _seed_memory())
    p.propose(1, _seed_memory())
    assert p.llm_calls == 2
    assert p.input_tokens == 200
    assert p.output_tokens == 100


def test_context_mode_reaches_the_prompt():
    """A study that silently sent the same context three times would prove nothing."""
    sent = {}
    for mode in CONSTRUCTIONS:
        p, client = _llm_proposer(GOOD_JSON, context_mode=mode)
        p.propose(1, _seed_memory(20))
        sent[mode] = client.last_kwargs["messages"][0]["content"]
    assert len(set(sent.values())) == 3, "constructions produced identical prompts"
    assert len(sent["best_only"]) < len(sent["everything"])


def test_the_system_prompt_is_identical_across_constructions():
    """Otherwise a token delta between constructions is not a delta in history."""
    systems = set()
    for mode in CONSTRUCTIONS:
        p, client = _llm_proposer(GOOD_JSON, context_mode=mode)
        p.propose(1, _seed_memory())
        systems.add(client.last_kwargs["system"][0]["text"])
    assert len(systems) == 1


def test_deterministic_path_needs_no_client_at_all():
    """The offline story: default construction, no key, no SDK, still works."""
    p = Proposer(seed=0)
    variants = p.propose(3, _seed_memory())
    assert len(variants) == 3
    assert p.llm_calls == 0
    for v in variants:
        verify_variant(v)
