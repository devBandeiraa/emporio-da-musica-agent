from decimal import Decimal

import pytest

from emporio_agent.text import compact, digits_only, format_brl, normalize


def test_normalize_drops_accents_case_and_punctuation():
    assert normalize("  Violão  ELÉTRICO-Aço ") == "violao eletrico aco"


@pytest.mark.parametrize("text", ["GD20", "gd 20", "GD-20", "gd.20"])
def test_compact_treats_model_spellings_as_equal(text):
    assert compact(text) == "gd20"


def test_digits_only():
    assert digits_only("+55 (67) 99654-7821") == "5567996547821"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("5519.08"), "R$ 5.519,08"),
        (Decimal("599.9"), "R$ 599,90"),
        (Decimal("11499"), "R$ 11.499,00"),
        (Decimal("0.005"), "R$ 0,01"),
    ],
)
def test_format_brl(value, expected):
    assert format_brl(value) == expected
