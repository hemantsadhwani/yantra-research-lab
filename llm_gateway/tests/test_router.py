"""The provider seam, offline: no API key, no AWS credential, no Ollama server."""

from __future__ import annotations

import io
import json

import pytest

pytest.importorskip("pydantic")

from pydantic import BaseModel, Field, ValidationError

from llm_gateway import (
    FakeProvider,
    LLMResponse,
    Provider,
    get_provider,
    pricing,
)
from llm_gateway.anthropic_provider import AnthropicProvider
from llm_gateway.base import ProviderUnavailable, extract_json
from llm_gateway.bedrock_provider import BedrockProvider
from llm_gateway.ollama_provider import OllamaProvider


class Pick(BaseModel):
    ticker: str
    weight: float = Field(ge=0, le=1)


GOOD = '{"ticker": "NIFTY", "weight": 0.5}'
BAD = "Sure! I think NIFTY at half weight."


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "LLM_BEDROCK_CLIENT",
                "AWS_REGION", "OLLAMA_HOST", "OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)


# ------------------------------------------------------------------- router
@pytest.mark.parametrize("name,cls", [("anthropic", AnthropicProvider),
                                      ("bedrock", BedrockProvider),
                                      ("ollama", OllamaProvider)])
def test_env_selects_the_provider_class(monkeypatch, name, cls):
    monkeypatch.setenv("LLM_PROVIDER", name)
    p = get_provider()                   # no client is built, so no network / creds
    assert isinstance(p, cls)
    assert isinstance(p, Provider)
    assert p.name == name


def test_default_is_anthropic_haiku_and_llm_model_overrides(monkeypatch):
    p = get_provider()
    assert (p.name, p.model) == ("anthropic", "claude-haiku-4-5")
    monkeypatch.setenv("LLM_MODEL", "claude-other")
    assert get_provider().model == "claude-other"
    assert get_provider("ollama", model="llama3").model == "llama3"


def test_unknown_provider_raises_with_the_valid_names():
    with pytest.raises(ValueError) as e:
        get_provider("openai")
    for valid in ("anthropic", "bedrock", "ollama"):
        assert valid in str(e.value)


def test_anthropic_without_a_key_fails_loudly_on_first_call():
    with pytest.raises(ProviderUnavailable, match="ANTHROPIC_API_KEY"):
        get_provider("anthropic").complete(system="s", messages=[], max_tokens=8)


# ------------------------------------------------------------------- FakeProvider
def test_fake_provider_validates_and_repairs_once():
    fake = FakeProvider([BAD, GOOD])
    resp = fake.complete(system="s", messages=[{"role": "user", "content": "go"}],
                         max_tokens=64, schema=Pick)
    assert isinstance(resp, LLMResponse)
    assert resp.parsed == Pick(ticker="NIFTY", weight=0.5)
    assert resp.structured_mode == "prompt"
    assert len(fake.calls) == 2
    assert "not valid JSON for this schema" in fake.calls[1]["messages"][-1]["content"]


def test_fake_provider_raises_when_the_repair_is_bad_too():
    with pytest.raises(ValidationError):
        FakeProvider([BAD, BAD]).complete(system="s", messages=[], max_tokens=8, schema=Pick)


def test_fake_provider_returns_models_natively_and_raises_exceptions():
    fake = FakeProvider([Pick(ticker="X", weight=1.0), RuntimeError("boom")], cost_per_call=0.01)
    resp = fake.complete(system="s", messages=[], max_tokens=8, schema=Pick)
    assert resp.structured_mode == "native" and resp.cost_usd == 0.01
    with pytest.raises(RuntimeError, match="boom"):
        fake.complete(system="s", messages=[], max_tokens=8)


# ------------------------------------------------------------------- Ollama
class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_payload_shape_and_token_mapping(monkeypatch):
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append((req.full_url, json.loads(req.data.decode())))
        return _Body(json.dumps({"message": {"role": "assistant", "content": GOOD},
                                 "prompt_eval_count": 42, "eval_count": 7}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:11434/")
    resp = OllamaProvider().complete(system="be terse",
                                     messages=[{"role": "user", "content": "pick"}],
                                     max_tokens=99, schema=Pick)
    url, payload = sent[0]
    assert url == "http://gpu-box:11434/api/chat"
    assert payload["model"] == "qwen2.5:7b-instruct"
    assert payload["stream"] is False
    assert payload["format"] == Pick.model_json_schema()
    assert payload["options"] == {"num_predict": 99}
    assert payload["messages"][0] == {"role": "system", "content": "be terse"}
    assert (resp.input_tokens, resp.output_tokens, resp.cost_usd) == (42, 7, 0.0)
    assert resp.parsed == Pick(ticker="NIFTY", weight=0.5)


def test_ollama_repairs_once(monkeypatch):
    replies = iter([BAD, GOOD])
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Body(
        json.dumps({"message": {"content": next(replies)}, "prompt_eval_count": 1,
                    "eval_count": 1}).encode()))
    resp = OllamaProvider().complete(system="s", messages=[], max_tokens=8, schema=Pick)
    assert resp.parsed.ticker == "NIFTY" and resp.input_tokens == 2


def test_ollama_unreachable_is_a_clear_error(monkeypatch):
    import urllib.error

    def refuse(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(ProviderUnavailable, match="ollama serve"):
        OllamaProvider().complete(system="s", messages=[], max_tokens=8)


# ------------------------------------------------------------------- Bedrock
def test_bedrock_client_is_constructed_with_the_region(monkeypatch):
    import anthropic

    made = []

    class Recording:
        def __init__(self, **kw):
            made.append((type(self).__name__, kw))

    monkeypatch.setattr(anthropic, "AnthropicBedrock", type("AnthropicBedrock", (Recording,), {}))
    monkeypatch.setattr(anthropic, "AnthropicBedrockMantle",
                        type("AnthropicBedrockMantle", (Recording,), {}))
    monkeypatch.setenv("AWS_REGION", "ap-south-1")

    p = get_provider("bedrock")
    assert p.model == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    p.client  # noqa: B018 - builds the client
    assert made == [("AnthropicBedrock", {"aws_region": "ap-south-1"})]

    monkeypatch.setenv("LLM_BEDROCK_CLIENT", "mantle")
    m = get_provider("bedrock")
    assert m.model == "anthropic.claude-haiku-4-5"
    m.client  # noqa: B018
    assert made[-1] == ("AnthropicBedrockMantle", {"aws_region": "ap-south-1"})


def test_bedrock_haiku_is_priced_at_list_price():
    a = pricing.estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000, 1_000_000, 1_000_000)
    b = pricing.estimate_cost("us.anthropic.claude-haiku-4-5-20251001-v1:0",
                              1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert a == b == pytest.approx(1.00 + 5.00 + 0.10 + 1.25)
    assert BedrockProvider.cost_label == "list price"
    assert pricing.estimate_cost("mystery-model", 10, 10) == 0.0


# ------------------------------------------------------------------- Anthropic ladder
class _Usage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 3
    cache_creation_input_tokens = 2


class _Resp:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = _Usage()


class _NoParseClient:
    """``messages.parse`` is missing and ``output_config`` is a 400 → prompt rung."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def parse(self, **kw):
        raise AttributeError("parse")

    def create(self, **kw):
        self.calls.append(kw)
        if "output_config" in kw:
            err = Exception("output_config not supported")
            err.status_code = 400
            raise err
        return _Resp(self.replies.pop(0))


def test_anthropic_ladder_falls_from_parse_to_json_schema_to_prompt():
    client = _NoParseClient(["```json\n" + GOOD + "\n```"])
    resp = AnthropicProvider(client=client).complete(
        system="sys", messages=[{"role": "user", "content": "pick"}], max_tokens=50, schema=Pick)
    assert resp.structured_mode == "prompt"
    assert resp.parsed == Pick(ticker="NIFTY", weight=0.5)
    assert "output_config" in client.calls[0]                    # json_schema rung was tried
    assert "JSON schema" in client.calls[1]["system"][0]["text"]  # schema in the prompt
    assert client.calls[1]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert (resp.input_tokens, resp.cache_read_tokens, resp.cache_write_tokens) == (10, 3, 2)
    assert resp.cost_usd > 0


def test_anthropic_prompt_rung_repairs_once_then_gives_up():
    client = _NoParseClient([BAD, GOOD])
    resp = AnthropicProvider(client=client).complete(
        system="s", messages=[], max_tokens=50, schema=Pick, cache_system=False)
    assert resp.parsed.ticker == "NIFTY" and resp.input_tokens == 20
    assert client.calls[-1]["system"].startswith("s")            # uncached: plain string
    with pytest.raises(ValidationError):
        AnthropicProvider(client=_NoParseClient([BAD, BAD])).complete(
            system="s", messages=[], max_tokens=50, schema=Pick)


def test_anthropic_json_schema_rung_when_create_accepts_output_config():
    class Client(_NoParseClient):
        def create(self, **kw):
            self.calls.append(kw)
            return _Resp(GOOD)

    resp = AnthropicProvider(client=Client([])).complete(
        system="s", messages=[], max_tokens=50, schema=Pick)
    assert resp.structured_mode == "json_schema"


def test_anthropic_native_rung_uses_parsed_output():
    class Client(_NoParseClient):
        def parse(self, **kw):
            self.calls.append(kw)
            r = _Resp(GOOD)
            r.parsed_output = Pick(ticker="NIFTY", weight=0.5)
            return r

    client = Client([])
    resp = AnthropicProvider(client=client).complete(
        system="s", messages=[], max_tokens=50, schema=Pick)
    assert resp.structured_mode == "native"
    assert client.calls[0]["output_format"] is Pick


def test_anthropic_plain_text_has_no_structured_mode():
    resp = AnthropicProvider(client=_NoParseClient(["hello"])).complete(
        system="s", messages=[], max_tokens=5)
    assert (resp.text, resp.parsed, resp.structured_mode) == ("hello", None, "none")


# ------------------------------------------------------------------- JSON extraction
def test_extract_json_strips_fences_and_preamble():
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Here you go:\n{"a": {"b": 2}} hope it helps') == '{"a": {"b": 2}}'
    assert extract_json("I would rather not.") == "I would rather not."
