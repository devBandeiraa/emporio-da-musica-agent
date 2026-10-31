"""The conversation loop: ask the model, run the tools it requests, repeat until it answers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from emporio_agent.config import Settings
from emporio_agent.llm import AnthropicClient, LLMClient, LLMUnavailableError
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
        self._messages: list[dict[str, Any]] = []

    def reply(self, user_message: str) -> str:
        turn_start = len(self._messages)
        self._messages.append({"role": "user", "content": user_message})

        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = self._llm.create_message(self._system, self._messages, self._tools)

                if response.stop_reason == "tool_use":
                    self._messages.append({"role": "assistant", "content": response.content})
                    self._messages.append({"role": "user", "content": self._run_tools(response)})
                    continue

                text = self._text_of(response)
                if response.stop_reason == "end_turn" and text:
                    self._messages.append({"role": "assistant", "content": response.content})
                    return text
                break
        except LLMUnavailableError:
            pass

        # Refusal, truncated answer or too many rounds: drop the unfinished turn, so a
        # half-built exchange cannot break the next request.
        del self._messages[turn_start:]
        return FALLBACK_REPLY

    def _run_tools(self, response: Any) -> list[dict[str, Any]]:
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = self._toolbox.execute(block.name, block.input)
            if self._on_tool_call:
                self._on_tool_call(ToolCall(block.name, block.input, result))
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result.content,
                    "is_error": result.is_error,
                }
            )
        return results

    @staticmethod
    def _text_of(response: Any) -> str:
        return "".join(b.text for b in response.content if b.type == "text").strip()


def build_agent(
    settings: Settings, on_tool_call: Callable[[ToolCall], None] | None = None
) -> tuple[Agent, AnthropicClient]:
    llm = AnthropicClient(settings.api_key, settings.model, settings.effort)
    toolbox = Toolbox(load_store(settings.data_dir), settings.now, settings.tickets_path)
    return Agent(llm, toolbox, settings.now(), on_tool_call), llm
