"""The provider contract and the helpers every provider shares."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

StructuredMode = Literal["native", "json_schema", "prompt", "none"]

REPAIR_TEMPLATE = (
    "Your previous reply was not valid JSON for this schema: {error}. "
    "Reply with only the JSON."
)


class LLMResponse(BaseModel):
    """What every provider returns. ``parsed`` is set iff a schema was requested."""

    text: str
    parsed: Any | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float
    structured_mode: StructuredMode


@runtime_checkable
class Provider(Protocol):
    name: str
    model: str

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_tokens: int,
        schema: type[BaseModel] | None = None,
        cache_system: bool = True,
    ) -> LLMResponse: ...


class ProviderUnavailable(RuntimeError):
    """The provider cannot run here (no credentials, SDK missing, server unreachable)."""


def extract_json(text: str) -> str:
    """Best-effort: strip a code fence / preamble and return the outermost ``{...}``.

    Only used on the prompt-mode path, where the model was *asked* for JSON but not
    constrained to it. Returns the input unchanged if no object is found, so the
    schema validator produces the error message the repair round-trip quotes.
    """
    candidate = text.strip()
    if "```" in candidate:
        for part in candidate.split("```"):
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                candidate = cleaned
                break
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return candidate
    return candidate[start:end + 1]


def validate_text(schema: type[BaseModel], text: str) -> BaseModel:
    """Validate a model reply against ``schema``; raises ``ValidationError``."""
    return schema.model_validate_json(extract_json(text))


def schema_instruction(schema: type[BaseModel]) -> str:
    """The suffix appended to the system prompt when the provider can't constrain output."""
    return (
        "\n\nRespond with ONLY a JSON object (no prose, no code fences) that validates "
        "against this JSON schema:\n" + json.dumps(schema.model_json_schema())
    )


def short_error(err: ValidationError) -> str:
    """A compact error string for the repair prompt (the full one can be very long)."""
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
        for e in err.errors()[:5]
    )
