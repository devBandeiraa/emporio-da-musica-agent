"""The conversation loop: ask the model, run the tools it requests, repeat until it answers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from emporio_agent.config import Settings
from emporio_agent.llm import (
    GeminiClient,
    LLMClient,
    LLMUnavailableError,
    ToolRequest,
    tool_results_content,
    user_content,
)
from emporio_agent.prompts import build_system
from emporio_agent.store import load_store
from emporio_agent.tools import Toolbox, ToolResult

MAX_TOOL_ROUNDS = 8

FALLBACK_REPLY = (
    "Poxa, tive um problema aqui e não consegui concluir sua resposta. "
    "Pode tentar de novo? Se preferir, a equipe atende pelo WhatsApp (67) 3321-4500."
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: ToolResult


class Agent:
    """One conversation. History lives here, in memory, and ends with the session."""

    def __init__(
        self,
        llm: LLMClient,
        toolbox: Toolbox,
        now: datetime,
        on_tool_call: Callable[[ToolCall], None] | None = None,
    ) -> None:
        self._llm = llm
        self._toolbox = toolbox
        self._on_tool_call = on_tool_call
        self._system = build_system(now)
        self._tools = toolbox.definitions()
        self._contents: list[Any] = []

    def reply(self, user_message: str) -> str:
        turn_start = len(self._contents)
        self._contents.append(user_content(user_message))

        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = self._llm.create_message(self._system, self._contents, self._tools)

                if response.stop_reason == "tool_use":
                    self._contents.append(response.content)
                    self._contents.append(self._run_tools(response.tool_requests))
                    continue

                if response.stop_reason == "end_turn" and response.text:
                    self._contents.append(response.content)
                    return response.text
                break
        except LLMUnavailableError:
            pass

        # Blocked or truncated answer, or too many rounds: drop the unfinished turn, so a
        # half-built exchange cannot break the next request.
        del self._contents[turn_start:]
        return FALLBACK_REPLY

    def _run_tools(self, requests: tuple[ToolRequest, ...]) -> Any:
        results = []
        for request in requests:
            result = self._toolbox.execute(request.name, request.arguments)
            if self._on_tool_call:
                self._on_tool_call(ToolCall(request.name, request.arguments, result))
            results.append((request, result))
        return tool_results_content(results)


def build_agent(
    settings: Settings, on_tool_call: Callable[[ToolCall], None] | None = None
) -> tuple[Agent, GeminiClient]:
    llm = GeminiClient(settings.api_key, settings.model)
    toolbox = Toolbox(load_store(settings.data_dir), settings.now, settings.tickets_path)
    return Agent(llm, toolbox, settings.now(), on_tool_call), llm
