"""Any Bedrock model through the Converse API, in-region in Mumbai (ap-south-1).

The research agents run on open models chosen per role by measurement, not on one frontier
model: ``google.gemma-3-12b-it`` (cheap: intake, data, report) and ``deepseek.v3.2``
(reasoning: planner, researcher, critic). Claude stays available through the other
providers but is not the default. Credentials come from the standard AWS chain
(``AWS_PROFILE``); nothing is stored in the repo. ``AWS_REGION`` overrides the region.

Structured output, strongest first (``LLMResponse.structured_mode``):
1. ``native``: one tool whose input schema is the Pydantic schema, forced with toolChoice;
2. ``prompt``: the schema in the system prompt, the reply validated, one repair round-trip.

Cost is estimated from Bedrock's token counts at the model's price row; a model with no price
row is refused before any call, so a run can never spend money it cannot account for.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ValidationError

from llm_gateway import pricing
from llm_gateway.base import (
    REPAIR_TEMPLATE,
    LLMResponse,
    ProviderUnavailable,
    StructuredMode,
    schema_instruction,
    short_error,
    validate_text,
)

DEFAULT_MODEL = "google.gemma-3-12b-it"
TOOL_NAME = "submit"


def _messages(msgs: list[dict]) -> list[dict]:
    out = []
    for m in msgs:
        content = m["content"]
        out.append({"role": m["role"],
                    "content": [{"text": content}] if isinstance(content, str) else content})
    return out


def _text(resp: dict) -> str:
    blocks = resp.get("output", {}).get("message", {}).get("content", [])
    return "".join(b.get("text", "") for b in blocks)


def _tool_input(resp: dict) -> Any | None:
    for b in resp.get("output", {}).get("message", {}).get("content", []):
        if "toolUse" in b:
            return b["toolUse"].get("input")
    return None


def _is_unsupported(err: Exception) -> bool:
    """A 400 about the request shape (tools, temperature), not a throttle or an outage."""
    code = getattr(err, "response", {}).get("Error", {}).get("Code", "")
    return code == "ValidationException"


class ConverseProvider:
    name = "converse"

    def __init__(self, model: str | None = None, client: Any = None, region: str | None = None) -> None:
        self.model = model or DEFAULT_MODEL
        self.region = region or os.environ.get("AWS_REGION") or "ap-south-1"
        self._client = client
        self._temperature: float | None = 0.0       # dropped if the model refuses it

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError as e:   # pragma: no cover - boto3 is in the llm extra
                raise ProviderUnavailable("boto3 is not installed") from e
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def _call(self, **kw: Any) -> dict:
        cfg: dict[str, Any] = {"maxTokens": kw.pop("max_tokens")}
        if self._temperature is not None:
            cfg["temperature"] = self._temperature
        try:
            return self.client.converse(modelId=self.model, inferenceConfig=cfg, **kw)
        except Exception as e:
            if _is_unsupported(e) and "temperature" in str(e) and self._temperature is not None:
                self._temperature = None
                return self._call(max_tokens=cfg["maxTokens"], **kw)
            raise

    def complete(self, *, system: str, messages: list[dict], max_tokens: int,
                 schema: type[BaseModel] | None = None, cache_system: bool = True) -> LLMResponse:
        pricing.require_price(self.model)            # fail closed before spending anything
        usage = [0, 0]

        def call(sys_text: str, msgs: list[dict], **extra: Any) -> dict:
            resp = self._call(system=[{"text": sys_text}], messages=_messages(msgs),
                              max_tokens=max_tokens, **extra)
            u = resp.get("usage", {})
            usage[0] += int(u.get("inputTokens", 0))
            usage[1] += int(u.get("outputTokens", 0))
            return resp

        if schema is None:
            resp = call(system, messages)
            return self._response(_text(resp), None, usage, "none")

        tool = {"tools": [{"toolSpec": {
                    "name": TOOL_NAME, "description": "Submit the answer as structured data.",
                    "inputSchema": {"json": schema.model_json_schema()}}}],
                "toolChoice": {"tool": {"name": TOOL_NAME}}}
        try:
            resp = call(system, messages, toolConfig=tool)
            data = _tool_input(resp)
            if data is not None:
                try:
                    return self._response(_text(resp), schema.model_validate(data), usage, "native")
                except ValidationError:
                    pass
        except Exception as e:
            if not _is_unsupported(e):
                raise

        prompt_system = system + schema_instruction(schema)
        resp = call(prompt_system, messages)
        text = _text(resp)
        try:
            return self._response(text, validate_text(schema, text), usage, "prompt")
        except ValidationError as err:
            repair = [*messages, {"role": "assistant", "content": text or "(empty)"},
                      {"role": "user", "content": REPAIR_TEMPLATE.format(error=short_error(err))}]
            resp = call(prompt_system, repair)
            text = _text(resp)
            return self._response(text, validate_text(schema, text), usage, "prompt")

    def _response(self, text: str, parsed: Any, usage: list[int], mode: StructuredMode) -> LLMResponse:
        return LLMResponse(text=text, parsed=parsed, provider=self.name, model=self.model,
                           input_tokens=usage[0], output_tokens=usage[1],
                           cost_usd=pricing.estimate_cost(self.model, usage[0], usage[1]),
                           structured_mode=mode)
