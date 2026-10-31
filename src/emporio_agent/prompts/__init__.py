"""Versioned prompt files and the code that assembles them."""

from datetime import datetime
from importlib import resources
from typing import Any

WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def _read(name: str) -> str:
    return resources.files(__package__).joinpath(name).read_text(encoding="utf-8")


def build_system(now: datetime) -> list[dict[str, Any]]:
    """Static text first, marked for caching; the clock stays out of the cached prefix."""
    static_text = f"{_read('system_prompt.md')}\n{_read('manual.md')}"
    moment = f"{WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y}, {now:%H:%M}"
    return [
        {"type": "text", "text": static_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Agora é {moment} em Campo Grande/MS."},
    ]
