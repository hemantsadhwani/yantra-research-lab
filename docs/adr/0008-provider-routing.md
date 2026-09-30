# ADR-0008 — One `Provider` protocol in front of every model; a thin adapter, not LiteLLM

**Status:** accepted · 2026-09-29

## Context
The LLM proposer and the chatbot each called the Anthropic SDK directly, with hand-rolled JSON
slicing of the reply. The business target runs Claude on AWS Bedrock, and the compliance story
needs a local open-weight option. Three call sites times three backends is the wrong shape.

## Decision
- **One protocol** (`llm_gateway/base.py`):
  `Provider.complete(*, system, messages, max_tokens, schema=None, cache_system=True) -> LLMResponse`.
  `LLMResponse` carries text, the parsed object, provider, model, token counts (including cache
  reads and writes), `cost_usd`, and `structured_mode`: which rung produced the output.
- **Three providers**, picked by `LLM_PROVIDER` (or `--provider`) in `llm_gateway/router.py`:
  `anthropic` (direct API, `claude-haiku-4-5`), `bedrock` (the same Messages-API code with an
  `AnthropicBedrock` client, AWS credential chain, `LLM_BEDROCK_CLIENT=mantle` optional) and
  `ollama` (stdlib `urllib` against `/api/chat`, no SDK, default `qwen2.5:7b-instruct`).
  `llm_gateway/testing.py` has a scripted `FakeProvider`, so every test runs offline.
- **Structured output walks a ladder**, strongest guarantee first:
  1. `native`: `messages.parse(output_format=Schema)` (constrained decoding, validated instance);
  2. `json_schema`: `messages.create(output_config={"format": {"type": "json_schema", ...}})`;
  3. `prompt`: the schema goes in the system prompt, the reply is validated, and one repair
     round-trip quotes the validation error back to the model.
  A rung is skipped only when the call is unsupported or its reply fails validation. If the last
  rung fails, `ValidationError` reaches the caller, which decides what failure means (the proposer
  falls back to the heuristic and counts `llm_failures`; the judge abstains). Ollama sends the
  schema as `format` and still validates and repairs.
- **Costs are estimates at list price.** `llm_gateway/pricing.py` holds one row
  (`claude-haiku-4-5`: $1 / $5 / $0.10 / $1.25 per million input / output / cache-read /
  cache-write tokens), labelled `"list price"`. Bedrock model ids containing `haiku-4-5` use the
  same row. Ollama is $0. An unknown model estimates to $0 and logs one warning, so a missing row
  shows up in the logs rather than as a silently wrong bill. Nothing reads an invoice.

## Why a thin adapter and not LiteLLM
There are three providers, two of them the same SDK, one process, and one team. The adapter
is under 700 lines including its test double, and the ladder records *which* guarantee held on each call. That is what the
proposer's footer and the budget depend on, and it is the part a generic proxy hides. LiteLLM
was in `pyproject.toml` unused; WP0 removed it.

**LiteLLM wins when** several services (or languages) need one place for keys, spend limits,
fallbacks and rate limits, or when the provider count grows past what one module can test
against. That is a proxy in front of `llm_gateway/`, not a replacement for it, and it is listed
in [ROADMAP.md](../../ROADMAP.md) Phase 2.

## Trade-offs
- Adding a provider means writing and testing an adapter, not editing a config line.
- List-price cost is an estimate. It is right for enforcing a budget and wrong for accounting.

## The lesson: validate the schema the API actually sees
`ProposalBatch` first declared `params: dict[str, float]`. Pydantic's schema for that is an
open object, and every unit test passed against it. But structured-output decoding closes
every object (`additionalProperties: false`), so after the SDK's strict transform the params
object had *no allowed keys*: the model could only return `"params": {}`, and `_clamp` quietly
filled the values from the heuristic's sample. A live run showed an "LLM" run that was really the
heuristic. The fix is an explicit `ProposalParams` model with one field per `PARAM_SPACE` key,
and the guard is `research_lab/tests/test_proposer_llm.py::test_proposal_schema_survives_strict_transform`,
which runs the SDK's own transform and asserts the four keys survive as required properties.
The rule: test the schema after every transform the provider applies, not the one you wrote.

## As built (2026-09-30)
`llm_gateway/` is used by the proposer, the judge and the backend chatbot (`get_llm_provider()`).
Tests: `pytest llm_gateway/tests` (offline, `FakeProvider` and stubbed clients). Routing by task
difficulty is **not built**: there is still one model per task, so there is nothing to route
between yet ([architecture/07](../../architecture/07-model-routing-finetune.md)).
