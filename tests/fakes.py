"""A scripted stand-in for the LLM, so no test ever calls the real API."""

from copy import copy
from types import SimpleNamespace


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, block_id="call_1", **arguments):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=arguments)


def response(*content, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=list(content))


def says(text):
    return response(text_block(text))


def calls(*blocks):
    return response(*blocks, stop_reason="tool_use")


class FakeLLM:
    """Plays back scripted responses (or raises scripted errors) and records every request."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def create_message(self, system, messages, tools):
        self.requests.append(SimpleNamespace(system=system, messages=copy(messages), tools=tools))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
