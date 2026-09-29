"""One provider interface for every model call in the repo.

    from llm_gateway import get_provider
    provider = get_provider()                       # LLM_PROVIDER=anthropic|bedrock|ollama
    resp = provider.complete(system=..., messages=[...], max_tokens=512, schema=MyModel)
    resp.parsed      # a validated MyModel instance, or the call raised

The LLM proposer and the RAG chatbot both go through this seam, so switching between
Anthropic direct, Claude on AWS Bedrock and a local Ollama model is an env var, and
every structured reply is validated against a Pydantic schema before a caller sees it.

This package imports pydantic, so nothing on the stdlib default path may import it at
module import time (see CLAUDE.md). The SDKs themselves are imported lazily, inside the
provider that needs them.
"""

from llm_gateway.base import LLMResponse, Provider
from llm_gateway.router import PROVIDERS, get_provider
from llm_gateway.testing import FakeProvider

__all__ = ["PROVIDERS", "FakeProvider", "LLMResponse", "Provider", "get_provider"]
