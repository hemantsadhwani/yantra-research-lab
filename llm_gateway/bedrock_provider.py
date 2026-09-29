"""Claude on AWS Bedrock — the same Messages-API ladder, a different client.

Credentials come from the standard AWS chain (``AWS_PROFILE``, env keys, SSO, an
instance role); nothing Bedrock-specific is stored in this repo. ``LLM_BEDROCK_CLIENT``
picks the SDK client:

* ``legacy`` (default) — ``anthropic.AnthropicBedrock``, the InvokeModel-based client;
  model ids are inference-profile ids such as
  ``us.anthropic.claude-haiku-4-5-20251001-v1:0``.
* ``mantle`` — ``anthropic.AnthropicBedrockMantle``, the Messages-API-compatible
  endpoint; model ids look like ``anthropic.claude-haiku-4-5``.

Cost is estimated at Anthropic list price (``pricing.PRICE_LABEL``), not read from AWS
billing.
"""

from __future__ import annotations

import os
from typing import Any

from llm_gateway.anthropic_provider import ClaudeMessagesProvider
from llm_gateway.base import ProviderUnavailable

DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_MANTLE_MODEL = "anthropic.claude-haiku-4-5"
BEDROCK_CLIENTS = ("legacy", "mantle")


class BedrockProvider(ClaudeMessagesProvider):
    name = "bedrock"

    def __init__(
        self,
        model: str | None = None,
        region: str | None = None,
        client: Any = None,
        client_kind: str | None = None,
    ) -> None:
        kind = (client_kind or os.environ.get("LLM_BEDROCK_CLIENT") or "legacy").lower()
        if kind not in BEDROCK_CLIENTS:
            raise ValueError(
                f"LLM_BEDROCK_CLIENT={kind!r}; valid values: {', '.join(BEDROCK_CLIENTS)}"
            )
        self.client_kind = kind
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        default = DEFAULT_MANTLE_MODEL if kind == "mantle" else DEFAULT_BEDROCK_MODEL
        super().__init__(model or os.environ.get("LLM_MODEL") or default, client)

    def _make_client(self) -> Any:
        try:
            import anthropic
        except ImportError as e:   # pragma: no cover - depends on extras install
            raise ProviderUnavailable(
                "the anthropic SDK is not installed: pip install -e '.[llm]' "
                "(the extra pulls anthropic[bedrock])"
            ) from e
        if self.client_kind == "mantle":
            return anthropic.AnthropicBedrockMantle(aws_region=self.region)
        return anthropic.AnthropicBedrock(aws_region=self.region)
