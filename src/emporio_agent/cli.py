"""Terminal chat with the agent."""

import argparse
import json
import sys

from emporio_agent import __version__
from emporio_agent.agent import Agent, ToolCall, build_agent
from emporio_agent.config import ConfigError, load_settings
from emporio_agent.llm import LLMAuthError
from emporio_agent.store import DataError

EXIT_WORDS = frozenset({"sair", "exit", "quit"})
GREETING = (
    "Oi! Aqui é a Sol, da Empório da Música. Como posso te ajudar? (digite 'sair' para encerrar)"
)
GOODBYE = "Valeu pela visita! Até a próxima."
MAX_TRACE_LENGTH = 400


def _trace(call: ToolCall) -> None:
    """Show tool activity on stderr, so it never mixes with the conversation."""
    arguments = json.dumps(call.arguments, ensure_ascii=False)
    print(f"[tool] {call.name}({arguments})", file=sys.stderr)
    print(f"[tool] -> {call.result.content[:MAX_TRACE_LENGTH]}", file=sys.stderr)


def _chat(agent: Agent) -> None:
    print(f"Sol: {GREETING}\n")
    while True:
        try:
            message = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if message.casefold() in EXIT_WORDS:
            break
        if message:
            print(f"\nSol: {agent.reply(message)}\n")
    print(f"Sol: {GOODBYE}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atendimento da Empório da Música no terminal.")
    parser.add_argument("--version", action="version", version=f"emporio-agent {__version__}")
    parser.add_argument("--verbose", action="store_true", help="mostra as chamadas de ferramentas")
    args = parser.parse_args(argv)

    # Windows consoles may default to a legacy encoding that cannot print "ç" or "õ".
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    try:
        agent, _ = build_agent(load_settings(), _trace if args.verbose else None)
        _chat(agent)
    except (ConfigError, DataError) as error:
        print(f"Erro de configuração: {error}", file=sys.stderr)
        return 2
    except LLMAuthError as error:
        print(f"A chave da API foi recusada: {error}", file=sys.stderr)
        return 1
    return 0
