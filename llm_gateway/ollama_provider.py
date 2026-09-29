"""A local model via Ollama's ``/api/chat`` — stdlib only, no SDK, no cost.

With a schema, the JSON schema is sent as Ollama's ``format`` (constrained decoding),
the reply is still validated with ``model_validate_json``, and one repair round-trip
runs if it does not validate. Small local models are the most likely to need it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from pydantic import BaseModel, ValidationError

from llm_gateway.base import (
    REPAIR_TEMPLATE,
    LLMResponse,
    ProviderUnavailable,
    short_error,
    validate_text,
)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
TIMEOUT_S = 300


class OllamaProvider:
    name = "ollama"
    cost_label = "local"

    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self.model = model or os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")

    def _chat(
        self, system: str, messages: list[dict], max_tokens: int,
        schema: type[BaseModel] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if schema is not None:
            payload["format"] = schema.model_json_schema()
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Ollama returned HTTP {e.code} for {self.model!r}: {body}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise ProviderUnavailable(
                f"Ollama server unreachable at {self.host} ({e}). Start it with "
                f"`ollama serve` and `ollama pull {self.model}`, or set OLLAMA_HOST."
            ) from e

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_tokens: int,
        schema: type[BaseModel] | None = None,
        cache_system: bool = True,
    ) -> LLMResponse:
        body = self._chat(system, messages, max_tokens, schema)
        in_tok = int(body.get("prompt_eval_count", 0) or 0)
        out_tok = int(body.get("eval_count", 0) or 0)
        text = str((body.get("message") or {}).get("content", "")).strip()

        parsed = None
        if schema is not None:
            try:
                parsed = validate_text(schema, text)
            except ValidationError as err:
                repair = [
                    *messages,
                    {"role": "assistant", "content": text or "(empty)"},
                    {"role": "user",
                     "content": REPAIR_TEMPLATE.format(error=short_error(err))},
                ]
                body = self._chat(system, repair, max_tokens, schema)
                in_tok += int(body.get("prompt_eval_count", 0) or 0)
                out_tok += int(body.get("eval_count", 0) or 0)
                text = str((body.get("message") or {}).get("content", "")).strip()
                parsed = validate_text(schema, text)   # raises if still invalid

        return LLMResponse(
            text=text, parsed=parsed, provider=self.name, model=self.model,
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=0.0,
            structured_mode="json_schema" if schema is not None else "none",
        )
