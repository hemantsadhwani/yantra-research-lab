"""Pick a provider from the environment: ``LLM_PROVIDER`` and ``LLM_MODEL``."""

from __future__ import annotations

import os

from llm_gateway.base import Provider

PROVIDERS = ("anthropic", "bedrock", "ollama")


def get_provider(name: str | None = None, model: str | None = None) -> Provider:
    """Build the provider named by ``name`` or ``$LLM_PROVIDER`` (default ``anthropic``).

    ``model`` (or ``$LLM_MODEL``) overrides the provider's default model. No network
    call happens here; credentials are checked on the first ``complete``.
    """
    chosen = (name or os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    model = model or os.environ.get("LLM_MODEL") or None
    if chosen == "anthropic":
        from llm_gateway.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if chosen == "bedrock":
        from llm_gateway.bedrock_provider import BedrockProvider
        return BedrockProvider(model=model)
    if chosen == "ollama":
        from llm_gateway.ollama_provider import OllamaProvider
        return OllamaProvider(model=model)
    raise ValueError(f"unknown LLM provider {chosen!r}; valid: {', '.join(PROVIDERS)}")
