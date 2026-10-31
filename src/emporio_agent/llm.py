"""Thin wrapper over the Anthropic SDK, so the agent loop can run on a fake client in tests."""

from collections import Counter
from typing import Any, Protocol

import anthropic

MAX_OUTPUT_TOKENS = 16000

# Declined requests are retried server-side on these models. Others, like Haiku, have no
# fallback, and the agent loop handles the refusal either way.
SERVER_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailableError(Exception):
    """The API could not answer right now."""


class LLMAuthError(Exception):
    """The API key was rejected. Retrying will not help."""


class LLMClient(Protocol):
    def create_message(
        self,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str, effort: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._effort = effort
        self.usage: Counter[str] = Counter()

    def _fallback_options(self) -> dict[str, Any]:
        if self._model in SERVER_FALLBACK_MODELS:
            return {"betas": [SERVER_FALLBACK_BETA], "fallbacks": "default"}
        return {}

    def create_message(
        self,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                output_config={"effort": self._effort},
                cache_control={"type": "ephemeral"},
                system=system,
                messages=messages,
                tools=tools,
                **self._fallback_options(),
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
            raise LLMAuthError(str(error)) from error
        except anthropic.APIError as error:
            raise LLMUnavailableError(str(error)) from error

        self.usage["input_tokens"] += response.usage.input_tokens
        self.usage["output_tokens"] += response.usage.output_tokens
        self.usage["cache_read_input_tokens"] += response.usage.cache_read_input_tokens or 0
        self.usage["cache_creation_input_tokens"] += response.usage.cache_creation_input_tokens or 0
        return response
