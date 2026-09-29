"""Claude via the Anthropic SDK — shared by the direct API and AWS Bedrock.

Structured output walks a ladder, strongest guarantee first, and records which rung
succeeded in ``LLMResponse.structured_mode``:

1. ``native``      — ``client.messages.parse(output_format=Schema)``: the SDK constrains
                     decoding and returns a validated instance in ``.parsed_output``.
2. ``json_schema`` — ``messages.create(output_config={"format": {"type": "json_schema",
                     ...}})`` for SDK/platform combinations without ``parse``.
3. ``prompt``      — the schema is appended to the system prompt, the reply is validated
                     with ``model_validate_json``, and one repair round-trip quotes the
                     validation error back to the model.

A rung is skipped only when the call itself is unsupported (``AttributeError`` /
``TypeError`` from an older SDK, or a 400 from the platform) or its reply fails to
validate. If the prompt rung still fails after its repair, ``ValidationError`` is
raised: callers decide what a failure means (the proposer falls back and counts it).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return

        def g(name: str) -> int:
            return int(getattr(usage, name, 0) or 0)

        self.input_tokens += g("input_tokens")
        self.output_tokens += g("output_tokens")
        self.cache_read_tokens += g("cache_read_input_tokens")
        self.cache_write_tokens += g("cache_creation_input_tokens")


def _text_of(resp: Any) -> str:
    return "".join(
        getattr(b, "text", "") for b in getattr(resp, "content", []) or []
        if getattr(b, "type", "text") == "text"
    ).strip()


def _strict_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema in the strict form structured outputs accept (closed objects).

    Uses the SDK's public ``anthropic.transform_schema`` when present — the same
    transform ``messages.parse`` applies — so rungs 1 and 2 constrain identically.
    """
    raw = schema.model_json_schema()
    try:
        from anthropic import transform_schema
    except ImportError:   # older SDK: send pydantic's schema as-is
        return raw
    return transform_schema(raw)


def _is_unsupported(err: Exception) -> bool:
    """True when a structured rung is not available here (so the next rung should run)."""
    if isinstance(err, AttributeError | TypeError):
        return True
    return getattr(err, "status_code", None) == 400   # anthropic.APIStatusError 400


class ClaudeMessagesProvider:
    """The Messages-API ladder. Subclasses only choose the client and the default model."""

    name = "claude"
    cost_label = pricing.PRICE_LABEL

    def __init__(self, model: str, client: Any = None) -> None:
        self.model = model
        self._client = client

    # -- client -----------------------------------------------------------------
    def _make_client(self) -> Any:   # pragma: no cover - overridden
        raise NotImplementedError

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._make_client()
        return self._client

    # -- the call -----------------------------------------------------------------
    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_tokens: int,
        schema: type[BaseModel] | None = None,
        cache_system: bool = True,
    ) -> LLMResponse:
        client = self.client
        usage = _Usage()

        def sys_param(text: str) -> Any:
            if cache_system:
                return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
            return text

        base = {"model": self.model, "max_tokens": max_tokens, "messages": messages}

        if schema is None:
            resp = client.messages.create(**base, system=sys_param(system))
            usage.add(getattr(resp, "usage", None))
            return self._response(_text_of(resp), None, usage, "none")

        # 1. native: messages.parse(output_format=Schema)
        try:
            resp = client.messages.parse(**base, system=sys_param(system), output_format=schema)
            usage.add(getattr(resp, "usage", None))
            parsed = getattr(resp, "parsed_output", None)
            if isinstance(parsed, schema):
                return self._response(_text_of(resp), parsed, usage, "native")
        except ValidationError:
            pass
        except Exception as e:
            if not _is_unsupported(e):
                raise

        # 2. json_schema: messages.create(output_config=...)
        try:
            resp = client.messages.create(
                **base,
                system=sys_param(system),
                output_config={"format": {"type": "json_schema",
                                          "schema": _strict_schema(schema)}},
            )
            usage.add(getattr(resp, "usage", None))
            text = _text_of(resp)
            try:
                return self._response(text, validate_text(schema, text), usage, "json_schema")
            except ValidationError:
                pass
        except Exception as e:
            if not _is_unsupported(e):
                raise

        # 3. prompt: schema in the system prompt, validate, one repair round-trip
        prompt_system = sys_param(system + schema_instruction(schema))
        resp = client.messages.create(**base, system=prompt_system)
        usage.add(getattr(resp, "usage", None))
        text = _text_of(resp)
        try:
            return self._response(text, validate_text(schema, text), usage, "prompt")
        except ValidationError as err:
            repair = [
                *messages,
                {"role": "assistant", "content": text or "(empty)"},
                {"role": "user", "content": REPAIR_TEMPLATE.format(error=short_error(err))},
            ]
            resp = client.messages.create(**{**base, "messages": repair}, system=prompt_system)
            usage.add(getattr(resp, "usage", None))
            text = _text_of(resp)
            # Raises ValidationError if the repair also fails — the caller's call.
            return self._response(text, validate_text(schema, text), usage, "prompt")

    def _response(
        self, text: str, parsed: Any, usage: _Usage, mode: StructuredMode
    ) -> LLMResponse:
        return LLMResponse(
            text=text,
            parsed=parsed,
            provider=self.name,
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=pricing.estimate_cost(
                self.model, usage.input_tokens, usage.output_tokens,
                usage.cache_read_tokens, usage.cache_write_tokens,
            ),
            structured_mode=mode,
        )


class AnthropicProvider(ClaudeMessagesProvider):
    """Claude on the Anthropic API. Needs ``ANTHROPIC_API_KEY`` (checked on first call)."""

    name = "anthropic"

    def __init__(self, model: str | None = None, client: Any = None) -> None:
        super().__init__(model or DEFAULT_ANTHROPIC_MODEL, client)

    def _make_client(self) -> Any:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderUnavailable(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set "
                "(or set LLM_PROVIDER=bedrock|ollama)."
            )
        try:
            import anthropic
        except ImportError as e:   # pragma: no cover - depends on extras install
            raise ProviderUnavailable(
                "the anthropic SDK is not installed: pip install -e '.[llm]'"
            ) from e
        return anthropic.Anthropic()
