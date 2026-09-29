"""Turn one free-text message into a structured entry with one model call.

This module holds the schema, the prompt and the mapping to core values. The
provider modules (ai_claude, ai_openai) hold the SDK calls. The model only
produces the values of the form. The core saves them with the same functions
the web forms use, so every rule still applies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from spendtrack.core.errors import SpendtrackError, ValidationError
from spendtrack.core.expenses import UNSET, ItemInput
from spendtrack.core.money import (
    parse_amount,
    parse_decimal,
    parse_optional_amount,
    parse_optional_decimal,
)
from spendtrack.db.models import Category
from spendtrack.db.seed import FUEL_CATEGORY, UNCATEGORIZED

DEFAULT_MODEL = "claude-opus-5-5"


class ParseError(SpendtrackError):
    """The model call failed. The owner must send the message again."""


class ParsedItem(BaseModel):
    description: str = Field(description="Short label of the item, first letter uppercase")
    amount: str = Field(
        description="Amount in RON as a plain decimal string, for example 50 or 12.5"
    )
    category: str | None = Field(default=None, description="A category name from the list, or null")
    necessity: int | None = Field(default=None, description="1 to 4 only when the owner states it")


class ParsedEntry(BaseModel):
    """The structured output schema. Every amount is a decimal string to keep precision."""

    kind: Literal["expense", "drive", "unclear"]
    occurred_on: str | None = Field(
        default=None, description="ISO date YYYY-MM-DD, or null for the message date"
    )
    amount: str | None = Field(
        default=None, description="Total in RON as a plain decimal string with a dot, no separators"
    )
    category: str | None = Field(default=None, description="Exactly one name from the list")
    description: str | None = Field(default=None, description="Short label, no amount, no date")
    necessity: int | None = Field(default=None, description="1 to 4 only when the owner states it")
    cheaper_alt: bool = Field(default=False, description="True when a cheaper option exists")
    cheaper_alt_amount: str | None = Field(default=None, description="Price of the cheaper option")
    cheaper_alt_note: str | None = Field(default=None, description="Short reason, or null")
    recurring: bool = Field(default=False, description="True only when the owner says it repeats")
    quantity_km: str | None = Field(default=None, description="For a drive: the distance in km")
    consumption_override: str | None = Field(default=None, description="L/100 km, only if given")
    fuel_price_override: str | None = Field(
        default=None, description="RON per litre, only if given"
    )
    items: list[ParsedItem] = Field(default_factory=list, description="Partial detail lines")
    question: str | None = Field(
        default=None, description="When kind is unclear: one short question for the owner"
    )


SYSTEM_PROMPT = """You turn one short message from the owner of a personal expense tracker into one structured entry. The owner writes in Romanian, sometimes in English, often with typos and no punctuation. Write every text you produce (description, item descriptions, question) in Romanian.

Rules:
- kind: "expense" for money spent. "drive" when the message gives a distance driven in km; the app converts km into money, so a drive has no amount. "unclear" when the amount is missing, when two amounts compete for the total, or when the currency is not RON.
- Amounts are in RON. Write them as plain decimal strings with a dot and no thousands separators. In Romanian style a comma is the decimal separator and a dot groups thousands; in English style it is the reverse. Decide from context. If two readings are both plausible and differ a lot, use kind "unclear" and ask.
- occurred_on: resolve relative dates against the message date given in the user turn: today, yesterday, "ieri", "alaltaieri", weekday names (the most recent such day), "27.09" (day.month of the current year). Null means the message date.
- category: exactly one name from the list. Use "Uncategorized" when none fits.
- description: a short label in Romanian, without the amount or the date, first letter uppercase. For a drive, null or the place, for example "Cluj".
- items: partial detail such as "groceries 210, of which wine 50" or "din care vin 50" gives items [Wine 50]. Never add items that are not in the message. The items never exceed the total.
- necessity: only when the owner states it: essential/necessary/"necesar" = 1, important = 2, nice/"placere" = 3, impulse/regret/"impuls" = 4, or "!1" to "!4". Otherwise null.
- cheaper_alt: true when the owner says a cheaper option exists. cheaper_alt_amount when a price is given. cheaper_alt_note: the short reason.
- recurring: true only when the owner says it repeats: subscription, "abonament", monthly, "lunar".
- drive: quantity_km as a decimal string. consumption_override (L/100 km) and fuel_price_override (RON per litre) only when the owner gives them.
- Never invent an amount, a date or an item. When in doubt, ask one short question in Romanian."""


def build_user_message(text: str, message_date: date, categories: list[str]) -> str:
    """Build the user turn: the message date, the category list and the message."""
    return (
        f"Message date: {message_date.isoformat()} ({message_date.strftime('%A')}).\n"
        f"Categories: {', '.join(categories)}.\n\n"
        f"Message:\n{text.strip()}"
    )


class Parser(Protocol):
    def parse(self, text: str, *, message_date: date, categories: list[str]) -> ParsedEntry: ...


DEFAULT_EFFORT = "low"


def make_parser(provider: str, model: str | None, effort: str = DEFAULT_EFFORT) -> Parser:
    """Return the parser for the configured provider. The SDK is imported on demand.

    The effort is one of none, minimal, low, medium, high, xhigh, max, or "off" to
    send no reasoning parameter and take the default of the provider.
    """
    if provider == "anthropic":
        from spendtrack.core.ai_claude import ClaudeParser

        return ClaudeParser(model=model or DEFAULT_MODEL, effort=effort)
    if provider == "openai":
        from spendtrack.core.ai_openai import OpenAIParser

        if not model:
            raise ValidationError("Set AI_MODEL to an OpenAI model id when AI_PROVIDER is openai.")
        return OpenAIParser(model=model, effort=effort)
    if provider == "openrouter":
        from spendtrack.core.ai_openai import OpenRouterParser

        if not model:
            raise ValidationError(
                "Set AI_MODEL to an OpenRouter model id when AI_PROVIDER is openrouter."
            )
        return OpenRouterParser(model=model, effort=effort)
    raise ValidationError(f"Unknown AI_PROVIDER {provider!r}. Use anthropic, openai or openrouter.")


@dataclass
class Draft:
    """The values of one entry, ready for the core functions."""

    kind: Literal["expense", "drive"]
    occurred_on: date
    category_id: int
    description: str | None
    necessity: int | None | Any
    cheaper_alt: bool
    cheaper_alt_minor: int | None
    cheaper_alt_note: str | None
    recurring: bool | Any
    amount_minor: int | None = None
    quantity: Decimal | None = None
    overrides: dict[str, Decimal] = field(default_factory=dict)
    items: list[ItemInput] = field(default_factory=list)


def _resolve_category(name: str | None, categories: list[Category]) -> Category:
    """Match a category name without regard to case. Fall back to the Uncategorized one."""
    wanted = (name or "").strip().lower()
    by_name = {c.name.lower(): c for c in categories}
    if wanted in by_name:
        return by_name[wanted]
    if UNCATEGORIZED.lower() in by_name:
        return by_name[UNCATEGORIZED.lower()]
    return categories[0]


def _resolve_date(text: str | None, message_date: date) -> date:
    if not text:
        return message_date
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return message_date


def _normalize(text: str | None) -> str | None:
    """Normalize a decimal string from the model: strip spaces, accept a comma."""
    if text is None:
        return None
    cleaned = text.strip().replace(" ", "")
    return cleaned or None


def draft_from_entry(entry: ParsedEntry, categories: list[Category], message_date: date) -> Draft:
    """Convert the model output into a Draft. Raise ValidationError for unusable values."""
    if entry.kind == "unclear":
        raise ValidationError(entry.question or "Trimite suma și câteva cuvinte.")
    active = [c for c in categories if not c.archived] or categories
    occurred_on = _resolve_date(entry.occurred_on, message_date)
    necessity = entry.necessity if entry.necessity in (1, 2, 3, 4) else UNSET
    cheaper_minor = parse_optional_amount(_normalize(entry.cheaper_alt_amount))
    common = {
        "occurred_on": occurred_on,
        "description": (entry.description or "").strip() or None,
        "necessity": necessity,
        "cheaper_alt": bool(entry.cheaper_alt) or cheaper_minor is not None,
        "cheaper_alt_minor": cheaper_minor,
        "cheaper_alt_note": (entry.cheaper_alt_note or "").strip() or None,
        "recurring": True if entry.recurring else UNSET,
    }
    if entry.kind == "drive":
        quantity = parse_decimal(_normalize(entry.quantity_km), "distanța în km")
        overrides: dict[str, Decimal] = {}
        consumption = parse_optional_decimal(_normalize(entry.consumption_override), "consumul")
        price = parse_optional_decimal(
            _normalize(entry.fuel_price_override), "prețul combustibilului"
        )
        if consumption is not None:
            overrides["consumption_l_per_100km"] = consumption
        if price is not None:
            overrides["fuel_price_per_l"] = price
        drive_category = _resolve_category(FUEL_CATEGORY, active)
        return Draft(
            kind="drive",
            category_id=drive_category.id,
            quantity=quantity,
            overrides=overrides,
            **common,
        )
    amount_minor = parse_amount(_normalize(entry.amount))
    category = _resolve_category(entry.category, active)
    items: list[ItemInput] = []
    for item in entry.items:
        item_category = None
        if item.category and item.category.strip().lower() != category.name.lower():
            item_category = _resolve_category(item.category, active).id
        items.append(
            ItemInput(
                description=item.description.strip() or "Articol",
                amount_minor=parse_amount(_normalize(item.amount)),
                category_id=item_category,
                necessity=item.necessity if item.necessity in (1, 2, 3, 4) else None,
            )
        )
    return Draft(
        kind="expense", category_id=category.id, amount_minor=amount_minor, items=items, **common
    )
