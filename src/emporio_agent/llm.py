"""Thin wrapper over the Gemini SDK, so the agent loop can run on a fake client in tests."""

import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from google import genai
from google.genai import errors, types

from emporio_agent.tools import ToolResult

MAX_OUTPUT_TOKENS = 8192
REQUEST_TIMEOUT_MS = 60_000
MAX_ATTEMPTS = 5
FIRST_RETRY_DELAY_SECONDS = 2
RETRIABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

StopReason = Literal["end_turn", "tool_use", "incomplete"]


class LLMUnavailableError(Exception):
    """The API could not answer right now."""


class LLMAuthError(Exception):
    """The API key was rejected. Retrying will not help."""


@dataclass(frozen=True)
class ToolRequest:
    id: str | None
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    stop_reason: StopReason
    text: str
    tool_requests: tuple[ToolRequest, ...]
    # The model's turn, replayed unchanged: Gemini ties thought signatures to it.
    content: Any


class LLMClient(Protocol):
    def create_message(
        self, system: str, contents: list[Any], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


def user_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def tool_results_content(results: list[tuple[ToolRequest, ToolResult]]) -> types.Content:
    """All results of a round go back in one turn, in the order they were requested."""
    parts = []
    for request, result in results:
        key = "error" if result.is_error else "output"
        response = types.FunctionResponse(
            id=request.id, name=request.name, response={key: json.loads(result.content)}
        )
        parts.append(types.Part(function_response=response))
    return types.Content(role="user", parts=parts)


def _parse_response(raw: types.GenerateContentResponse) -> LLMResponse:
    candidate = raw.candidates[0] if raw.candidates else None
    content = candidate.content if candidate else None
    parts = (content.parts if content else None) or []

    requests = tuple(
        ToolRequest(part.function_call.id, part.function_call.name, dict(part.function_call.args))
        for part in parts
        if part.function_call and part.function_call.name
    )
    text = "".join(part.text for part in parts if part.text and not part.thought).strip()

    if candidate is None or candidate.finish_reason != types.FinishReason.STOP:
        return LLMResponse("incomplete", text, requests, content)
    return LLMResponse("tool_use" if requests else "end_turn", text, requests, content)


def _is_auth_failure(error: errors.ClientError) -> bool:
    return error.code in (401, 403) or "api key" in str(error.message).casefold()


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        # The SDK's retry_options is avoided on purpose: with it, valid requests intermittently
        # came back as 403 PERMISSION_DENIED, which never happened without it.
        options = types.HttpOptions(timeout=REQUEST_TIMEOUT_MS)
        self._client = genai.Client(api_key=api_key, http_options=options)
        self._model = model
        self.usage: Counter[str] = Counter()

    def _config(self, system: str, tools: list[dict[str, Any]]) -> types.GenerateContentConfig:
        declarations = [
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters_json_schema=tool["input_schema"],
            )
            for tool in tools
        ]
        return types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)],
            # The agent loop runs the tools itself, with its own limits.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )

    def _record_usage(self, raw: types.GenerateContentResponse) -> None:
        usage = raw.usage_metadata
        if usage:
            self.usage["prompt_tokens"] += usage.prompt_token_count or 0
            self.usage["output_tokens"] += usage.candidates_token_count or 0
            self.usage["thinking_tokens"] += usage.thoughts_token_count or 0
            self.usage["cached_tokens"] += usage.cached_content_token_count or 0
        self.usage["requests"] += 1

    def _generate(
        self, contents: list[Any], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        def request() -> types.GenerateContentResponse:
            return self._client.models.generate_content(
                model=self._model, contents=contents, config=config
            )

        for attempt in range(MAX_ATTEMPTS - 1):
            try:
                return request()
            except errors.APIError as error:
                if error.code not in RETRIABLE_STATUS_CODES:
                    raise
                time.sleep(FIRST_RETRY_DELAY_SECONDS * 2**attempt)
        return request()

    def create_message(
        self, system: str, contents: list[Any], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        try:
            raw = self._generate(contents, self._config(system, tools))
        except errors.ClientError as error:
            if _is_auth_failure(error):
                raise LLMAuthError(str(error)) from error
            raise LLMUnavailableError(str(error)) from error
        except (errors.ServerError, httpx.TransportError) as error:
            raise LLMUnavailableError(str(error)) from error

        self._record_usage(raw)
        return _parse_response(raw)
