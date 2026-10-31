"""A scripted stand-in for the LLM, so no test ever calls the real API."""

from copy import copy
from types import SimpleNamespace

from emporio_agent.llm import LLMResponse, ToolRequest


def tool_request(name, request_id="call_1", **arguments):
    return ToolRequest(request_id, name, arguments)


def says(text):
    return LLMResponse("end_turn", text, (), content=f"model: {text}")


def calls(*requests):
    return LLMResponse("tool_use", "", requests, content=f"model called {len(requests)} tools")


def incomplete(text=""):
    return LLMResponse("incomplete", text, (), content=None)


class FakeLLM:
    """Plays back scripted responses (or raises scripted errors) and records every request."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def create_message(self, system, contents, tools):
        self.requests.append(SimpleNamespace(system=system, contents=copy(contents), tools=tools))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
