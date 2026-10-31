"""Text helpers shared by the data layer and the tools."""

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def normalize(text: str) -> str:
    """Lowercase, drop accents and turn punctuation into single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", without_accents.casefold()).strip()


def compact(text: str) -> str:
    """Normalize and remove spaces, so "GD-20", "gd 20" and "GD20" compare equal."""
    return normalize(text).replace(" ", "")


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_brl(value: Decimal) -> str:
    """Format money the Brazilian way, e.g. R$ 5.519,08."""
    us_style = f"{round_money(value):,.2f}"
    return "R$ " + us_style.replace(",", "_").replace(".", ",").replace("_", ".")
