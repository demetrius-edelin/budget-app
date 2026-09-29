"""Money helpers. Money is an integer count of minor units (bani)."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from spendtrack.core.errors import ValidationError

_AMOUNT_RE = re.compile(r"^\s*(\d+)(?:[.,](\d{1,2}))?\s*$")
_THOUSANDS_RE = re.compile(r"\d[.,]\d{3}(?:[.,]|\s*$)")

NUMBER_FORMATS = ("ro-RO", "en-US")


def parse_amount(text: str | None) -> int:
    """Parse an amount into minor units.

    Accept digits with an optional decimal part of up to 2 digits. The decimal
    separator is a comma or a dot. Reject thousands separators and zero.
    """
    if text is None or not text.strip():
        raise ValidationError("Enter an amount.")
    match = _AMOUNT_RE.match(text)
    if match is None:
        stripped = text.strip()
        if _THOUSANDS_RE.search(stripped) or (stripped.count(".") + stripped.count(",")) > 1:
            raise ValidationError("Use no thousands separators. Write 1234,50 or 1234.50.")
        raise ValidationError("Enter a number with up to 2 decimals, for example 18,50.")
    whole, fraction = match.group(1), match.group(2) or ""
    minor = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if minor <= 0:
        raise ValidationError("The amount must be greater than zero.")
    return minor


def parse_optional_amount(text: str | None) -> int | None:
    """Parse an amount, or return None for an empty field."""
    if text is None or not text.strip():
        return None
    return parse_amount(text)


def parse_decimal(text: str | None, label: str = "value") -> Decimal:
    """Parse a positive decimal number with a comma or a dot as the separator."""
    if text is None or not text.strip():
        raise ValidationError(f"Enter the {label}.")
    cleaned = text.strip().replace(",", ".")
    try:
        value = Decimal(cleaned)
    except ArithmeticError as exc:
        raise ValidationError(f"The {label} must be a number, for example 7,2.") from exc
    if not value.is_finite() or value <= 0:
        raise ValidationError(f"The {label} must be greater than zero.")
    return value


def parse_optional_decimal(text: str | None, label: str = "value") -> Decimal | None:
    if text is None or not text.strip():
        return None
    return parse_decimal(text, label)


def to_minor(value: Decimal) -> int:
    """Round a decimal amount half-up to minor units."""
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(minor: int) -> Decimal:
    return Decimal(minor) / Decimal(100)


def format_minor(minor: int, number_format: str = "ro-RO") -> str:
    """Format minor units for display, for example 1.234,50 in ro-RO."""
    sign = "-" if minor < 0 else ""
    whole, fraction = divmod(abs(minor), 100)
    if number_format == "en-US":
        return f"{sign}{whole:,}.{fraction:02d}"
    grouped = f"{whole:,}".replace(",", ".")
    return f"{sign}{grouped},{fraction:02d}"


def format_decimal(value: Decimal) -> str:
    """Format a decimal without trailing zeros, for example 7.2 or 42."""
    text = format(Decimal(value).normalize(), "f")
    return text
