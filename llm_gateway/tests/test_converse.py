"""Converse provider, offline: forced-tool output, prompt fallback, temperature retry, and the
fail-closed price check."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from llm_gateway.converse_provider import ConverseProvider
from llm_gateway.router import get_provider


class Verdict(BaseModel):
    promote: bool
    reason: str


class ClientError(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.response = {"Error": {"Code": "ValidationException", "Message": msg}}


class FakeClient:
    def __init__(self, replies: list) -> None:
        self.replies, self.calls = list(replies), []

    def converse(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(text: str = "", tool: dict | None = None, i: int = 10, o: int = 5) -> dict:
    content = [{"text": text}] if text else []
    if tool is not None:
        content.append({"toolUse": {"name": "submit", "input": tool}})
    return {"output": {"message": {"content": content}}, "usage": {"inputTokens": i, "outputTokens": o}}


def test_native_tool_output_is_validated_and_costed() -> None:
    c = FakeClient([reply(tool={"promote": False, "reason": "failed holdout"}, i=1000, o=100)])
    r = ConverseProvider("deepseek.v3.2", client=c).complete(
        system="s", messages=[{"role": "user", "content": "q"}], max_tokens=50, schema=Verdict)
    assert r.parsed == Verdict(promote=False, reason="failed holdout") and r.structured_mode == "native"
    assert r.cost_usd == pytest.approx((1000 * 0.74 + 100 * 2.22) / 1e6)
    assert c.calls[0]["toolConfig"]["toolChoice"] == {"tool": {"name": "submit"}}
    assert c.calls[0]["messages"] == [{"role": "user", "content": [{"text": "q"}]}]


def test_falls_back_to_prompt_mode_with_one_repair() -> None:
    c = FakeClient([ClientError("This model doesn't support tool use"),
                    reply('{"promote": "maybe"}'), reply('{"promote": true, "reason": "ok"}')])
    r = ConverseProvider(client=c).complete(system="s", messages=[{"role": "user", "content": "q"}],
                                            max_tokens=50, schema=Verdict)
    assert r.parsed.promote is True and r.structured_mode == "prompt" and len(c.calls) == 3
    assert "JSON schema" in c.calls[1]["system"][0]["text"]


def test_temperature_is_dropped_once_if_refused() -> None:
    c = FakeClient([ClientError("temperature is not supported"), reply("hello")])
    p = ConverseProvider(client=c)
    assert p.complete(system="s", messages=[{"role": "user", "content": "q"}], max_tokens=5).text == "hello"
    assert "temperature" in c.calls[0]["inferenceConfig"] and "temperature" not in c.calls[1]["inferenceConfig"]


def test_unpriced_model_is_refused_before_any_call() -> None:
    c = FakeClient([])
    with pytest.raises(ValueError, match="no price row"):
        ConverseProvider("some.unknown-model", client=c).complete(
            system="s", messages=[{"role": "user", "content": "q"}], max_tokens=5)
    assert c.calls == []


def test_router_builds_it() -> None:
    p = get_provider("converse", "deepseek.v3.2")
    assert isinstance(p, ConverseProvider) and p.model == "deepseek.v3.2"
