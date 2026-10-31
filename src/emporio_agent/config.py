"""Settings read from the environment and an optional .env file."""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "gemini-3.6-flash"

# Campo Grande has been on UTC-4 all year since Brazil dropped daylight saving time in 2019.
CAMPO_GRANDE = timezone(timedelta(hours=-4))


class ConfigError(Exception):
    """A setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str = DEFAULT_MODEL
    reference_datetime: datetime | None = None
    data_dir: Path = Path("data")
    tickets_path: Path = Path("runtime/tickets.jsonl")

    def now(self) -> datetime:
        return self.reference_datetime or datetime.now(CAMPO_GRANDE).replace(tzinfo=None)


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ConfigError(f"REFERENCE_DATETIME is not an ISO datetime: {value!r}") from error


def load_settings() -> Settings:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in.")

    return Settings(
        api_key=api_key,
        model=os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL,
        reference_datetime=_parse_datetime(os.getenv("REFERENCE_DATETIME", "").strip()),
        data_dir=Path(os.getenv("DATA_DIR", "").strip() or "data"),
    )
