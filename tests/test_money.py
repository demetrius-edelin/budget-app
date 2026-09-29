from decimal import Decimal

import pytest

from spendtrack.core.errors import ValidationError
from spendtrack.core.money import format_minor, parse_amount, to_minor


@pytest.mark.parametrize(
    ("text", "minor"),
    [("100", 10000), ("18,50", 1850), ("18.5", 1850), ("2500", 250000), (" 7 ", 700)],
)
def test_parse_amount_accepts_both_separators(text: str, minor: int) -> None:
    assert parse_amount(text) == minor


@pytest.mark.parametrize("text", ["1.234,50", "2.500", "1,234.50"])
def test_parse_amount_rejects_thousands_separators(text: str) -> None:
    with pytest.raises(ValidationError, match="thousands"):
        parse_amount(text)


@pytest.mark.parametrize("text", ["0", "0,00", "", "   ", None, "abc", "-5", "1.2.3"])
def test_parse_amount_rejects_invalid(text: str | None) -> None:
    with pytest.raises(ValidationError):
        parse_amount(text)


def test_format_minor() -> None:
    assert format_minor(123450) == "1.234,50"
    assert format_minor(123450, "en-US") == "1,234.50"
    assert format_minor(5) == "0,05"
    assert format_minor(-1850) == "-18,50"


def test_to_minor_rounds_half_up() -> None:
    assert to_minor(Decimal("25.0387")) == 2504
    assert to_minor(Decimal("21.8127")) == 2181
    assert to_minor(Decimal("0.005")) == 1
