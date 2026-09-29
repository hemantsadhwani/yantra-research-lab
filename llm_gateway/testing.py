"""An offline, scriptable provider for tests — no key, no network, no SDK."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from llm_gateway.base import (
    REPAIR_TEMPLATE,
    LLMResponse,
    short_error,
    validate_text,
)


class FakeProvider:
    """Pops one scripted item per model round-trip.

    * a ``BaseModel`` → returned as ``parsed`` (``structured_mode="native"``);
    * a ``str``       → returned as text; with a schema it is validated like the prompt
      rung of the real providers, including ONE repair round-trip that consumes the
      next scripted item (so ``[bad, good]`` exercises the repair);
    * an ``Exception`` → raised.

    Every model round-trip's kwargs are recorded in ``.calls`` (a repair is a second
    entry, as it is a second API call on the real providers). Tokens are ``len(text) // 4``.
    """

    def __init__(
        self,
        scripted: list[str | BaseModel | Exception],
        name: str = "fake",
        model: str = "fake-1",
        cost_per_call: float = 0.0,
    ) -> None:
        self.scripted = list(scripted)
        self.name = name
        self.model = model
        self.cost_per_call = cost_per_call
        self.calls: list[dict[str, Any]] = []
        self.round_trips = 0

    def _next(self) -> str | BaseModel:
        if not self.scripted:
            raise RuntimeError("FakeProvider script exhausted")
        self.round_trips += 1
        item = self.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_tokens: int,
        schema: type[BaseModel] | None = None,
        cache_system: bool = True,
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "max_tokens": max_tokens,
                           "schema": schema, "cache_system": cache_system})
        in_tok = (len(system) + sum(len(str(m.get("content", ""))) for m in messages)) // 4
        item = self._next()

        if isinstance(item, BaseModel):
            text = item.model_dump_json()
            return self._resp(text, item, in_tok, 1, "native")

        text, trips = item, 1
        if schema is None:
            return self._resp(text, None, in_tok, trips, "none")
        try:
            parsed = validate_text(schema, text)
        except ValidationError as err:
            # The repair is a second model round-trip, recorded as a second call.
            self.calls.append({
                "system": system,
                "messages": [
                    *messages,
                    {"role": "assistant", "content": text or "(empty)"},
                    {"role": "user", "content": REPAIR_TEMPLATE.format(error=short_error(err))},
                ],
                "max_tokens": max_tokens, "schema": schema, "cache_system": cache_system,
            })
            nxt = self._next()
            text = nxt.model_dump_json() if isinstance(nxt, BaseModel) else nxt
            trips += 1
            parsed = validate_text(schema, text)   # raises if the repair is bad too
        return self._resp(text, parsed, in_tok, trips, "prompt")

    def _resp(self, text: str, parsed: Any, in_tok: int, trips: int, mode: str) -> LLMResponse:
        return LLMResponse(
            text=text, parsed=parsed, provider=self.name, model=self.model,
            input_tokens=in_tok * trips, output_tokens=len(text) // 4,
            cost_usd=self.cost_per_call, structured_mode=mode,  # type: ignore[arg-type]
        )
