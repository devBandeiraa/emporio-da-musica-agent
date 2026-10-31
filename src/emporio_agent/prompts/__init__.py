"""Versioned prompt files and the code that assembles them."""

from datetime import datetime
from importlib import resources

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


def build_system(now: datetime) -> str:
    """Stable text first and the clock last, so repeated requests share a cacheable prefix."""
    moment = f"{WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y}, {now:%H:%M}"
    return (
        f"{_read('system_prompt.md')}\n{_read('manual.md')}\nAgora é {moment} em Campo Grande/MS."
    )
