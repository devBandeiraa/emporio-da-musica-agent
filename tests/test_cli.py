import io
from types import SimpleNamespace

import pytest

from emporio_agent import __version__, cli
from emporio_agent.config import ConfigError
from emporio_agent.llm import LLMAuthError
from emporio_agent.store import DataError
from emporio_agent.tools import ToolResult


class EchoAgent:
    def __init__(self, error=None):
        self.error = error
        self.messages = []

    def reply(self, message):
        if self.error:
            raise self.error
        self.messages.append(message)
        return f"recebi: {message}"


@pytest.fixture
def chat(monkeypatch):
    """Run the CLI with scripted input; a real console stream is not needed."""

    def run(*lines, agent=None, args=()):
        agent = agent or EchoAgent()
        script = iter(lines)

        def fake_input(_prompt):
            line = next(script, EOFError)
            if isinstance(line, type) and issubclass(line, BaseException):
                raise line
            return line

        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(cli, "load_settings", lambda: SimpleNamespace())
        monkeypatch.setattr(cli, "build_agent", lambda settings, trace: (agent, None))
        monkeypatch.setattr(cli.sys, "stdin", io.TextIOWrapper(io.BytesIO()))
        return agent, cli.main(list(args))

    return run


def test_chats_until_the_exit_word(chat, capsys):
    agent, code = chat("oi", "tudo bem?", "SAIR", "nunca lido")

    output = capsys.readouterr().out
    assert code == 0
    assert agent.messages == ["oi", "tudo bem?"]
    assert "Sol: recebi: oi" in output
    assert cli.GREETING in output
    assert cli.GOODBYE in output


def test_skips_blank_lines(chat):
    agent, _ = chat("", "   ", "oi", "sair")
    assert agent.messages == ["oi"]


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_ends_cleanly_when_input_stops(chat, capsys, interruption):
    _, code = chat("oi", interruption)
    assert code == 0
    assert cli.GOODBYE in capsys.readouterr().out


def test_rejected_key_exits_with_a_message(chat, capsys):
    _, code = chat("oi", agent=EchoAgent(LLMAuthError("invalid x-api-key")))
    assert code == 1
    assert "chave da API" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error", [ConfigError("GEMINI_API_KEY is not set"), DataError("Missing data file")]
)
def test_setup_errors_exit_with_a_message(monkeypatch, capsys, error):
    def fail():
        raise error

    monkeypatch.setattr(cli, "load_settings", fail)
    monkeypatch.setattr(cli.sys, "stdin", io.TextIOWrapper(io.BytesIO()))

    assert cli.main([]) == 2
    assert str(error) in capsys.readouterr().err


def test_version_runs_without_any_configuration(capsys):
    with pytest.raises(SystemExit) as finished:
        cli.main(["--version"])

    assert finished.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_verbose_trace_goes_to_stderr(capsys):
    call = SimpleNamespace(
        name="get_order", arguments={"order_id": 8}, result=ToolResult('{"verified": true}')
    )

    cli._trace(call)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert 'get_order({"order_id": 8})' in captured.err
    assert '"verified": true' in captured.err
