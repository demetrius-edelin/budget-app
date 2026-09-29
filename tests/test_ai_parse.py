"""The provider-neutral part of the AI parse: prompt, mapping to core values, provider plumbing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from spendtrack.core import ai_parse
from spendtrack.core.ai_claude import ClaudeParser
from spendtrack.core.ai_openai import OpenAIParser, OpenRouterParser
from spendtrack.core.ai_parse import ParsedEntry, ParsedItem, draft_from_entry, make_parser
from spendtrack.core.categories import list_categories
from spendtrack.core.errors import ValidationError
from spendtrack.core.expenses import UNSET
from tests.conftest import TODAY


def test_user_message_holds_the_date_and_the_categories() -> None:
    text = ai_parse.build_user_message("coffee 18,50", TODAY, ["Alimente", "Mâncare în oraș"])
    assert "Message date: 2026-09-29 (Tuesday)." in text
    assert "Categories: Alimente, Mâncare în oraș." in text
    assert text.endswith("Message:\ncoffee 18,50")


def test_draft_for_an_expense_with_items(session: Session) -> None:
    entry = ParsedEntry(
        kind="expense",
        occurred_on="2026-09-28",
        amount="210",
        category="alimente",
        description="Weekly market",
        cheaper_alt=True,
        cheaper_alt_note="discount store",
        items=[ParsedItem(description="Wine", amount="50", necessity=3, category="Alimente")],
    )
    draft = draft_from_entry(entry, list_categories(session), TODAY)
    categories = {c.id: c.name for c in list_categories(session)}
    assert draft.kind == "expense"
    assert draft.occurred_on == date(2026, 9, 28)
    assert draft.amount_minor == 21000
    assert categories[draft.category_id] == "Alimente"
    assert draft.necessity is UNSET and draft.recurring is UNSET
    assert (draft.cheaper_alt, draft.cheaper_alt_minor, draft.cheaper_alt_note) == (
        True,
        None,
        "discount store",
    )
    assert len(draft.items) == 1
    assert (draft.items[0].description, draft.items[0].amount_minor, draft.items[0].necessity) == (
        "Wine",
        5000,
        3,
    )
    assert draft.items[0].category_id is None  # same category as the expense


def test_draft_falls_back_to_uncategorized_and_the_message_date(session: Session) -> None:
    entry = ParsedEntry(kind="expense", amount="12.5", category="Spaceships", necessity=9)
    draft = draft_from_entry(entry, list_categories(session), TODAY)
    names = {c.id: c.name for c in list_categories(session)}
    assert names[draft.category_id] == "Necategorisit"
    assert draft.occurred_on == TODAY
    assert draft.amount_minor == 1250
    assert draft.necessity is UNSET


def test_draft_for_a_drive(session: Session) -> None:
    entry = ParsedEntry(
        kind="drive",
        quantity_km="42",
        fuel_price_override="7,99",
        description="Cluj",
        recurring=True,
        necessity=2,
    )
    draft = draft_from_entry(entry, list_categories(session), TODAY)
    assert draft.kind == "drive"
    assert draft.quantity == Decimal("42")
    assert draft.overrides == {"fuel_price_per_l": Decimal("7.99")}
    assert draft.description == "Cluj"
    assert (draft.necessity, draft.recurring) == (2, True)


def test_unclear_raises_the_question(session: Session) -> None:
    entry = ParsedEntry(kind="unclear", question="How much was the coffee?")
    with pytest.raises(ValidationError, match="How much was the coffee"):
        draft_from_entry(entry, list_categories(session), TODAY)


def test_bad_amount_from_the_model_is_rejected(session: Session) -> None:
    entry = ParsedEntry(kind="expense", amount="1.234,50", category="Alimente")
    with pytest.raises(ValidationError):
        draft_from_entry(entry, list_categories(session), TODAY)


def test_make_parser_needs_a_model_for_openai_and_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The SDK clients read their keys at construction. The test never calls the network.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert isinstance(make_parser("anthropic", None), ClaudeParser)
    assert make_parser("anthropic", None).model == "claude-opus-5-5"
    assert isinstance(make_parser("openai", "some-model"), OpenAIParser)
    assert isinstance(make_parser("openrouter", "vendor/some-model"), OpenRouterParser)
    with pytest.raises(ValidationError):
        make_parser("openai", None)
    with pytest.raises(ValidationError):
        make_parser("nope", "x")


ENTRY = ParsedEntry(kind="expense", amount="18.5", category="Mâncare în oraș", description="Coffee")


def test_claude_parser_plumbing() -> None:
    calls: list[dict] = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            parsed_output=ENTRY,
            usage=SimpleNamespace(input_tokens=300, output_tokens=60),
        )

    client = SimpleNamespace(messages=SimpleNamespace(parse=fake_parse))
    parser = ClaudeParser(model="claude-opus-5-5", client=client)
    result = parser.parse("coffee 18,50", message_date=TODAY, categories=["Mâncare în oraș"])
    assert result == ENTRY
    call = calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is ParsedEntry
    assert call["output_config"] == {"effort": "low"}
    ClaudeParser(client=client, effort="minimal").parse("x", message_date=TODAY, categories=[])
    assert calls[1]["output_config"] == {"effort": "low"}
    ClaudeParser(client=client, effort="off").parse("x", message_date=TODAY, categories=[])
    assert "output_config" not in calls[2]
    assert call["system"] == ai_parse.SYSTEM_PROMPT
    assert "coffee 18,50" in call["messages"][0]["content"]


def test_claude_parser_turns_a_refusal_into_a_question() -> None:
    client = SimpleNamespace(
        messages=SimpleNamespace(
            parse=lambda **kw: SimpleNamespace(
                stop_reason="refusal", parsed_output=None, usage=None
            )
        )
    )
    result = ClaudeParser(client=client).parse("x", message_date=TODAY, categories=[])
    assert result.kind == "unclear" and result.question


def test_openai_parser_plumbing() -> None:
    calls: list[dict] = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=ENTRY)

    client = SimpleNamespace(responses=SimpleNamespace(parse=fake_parse))
    result = OpenAIParser("some-model", client=client).parse(
        "coffee 18,50", message_date=TODAY, categories=["Mâncare în oraș"]
    )
    assert result == ENTRY
    assert calls[0]["text_format"] is ParsedEntry
    assert calls[0]["instructions"] == ai_parse.SYSTEM_PROMPT
    assert calls[0]["reasoning"] == {"effort": "low"}
    OpenAIParser("m", client=client, effort="off").parse("x", message_date=TODAY, categories=[])
    assert "reasoning" not in calls[1]


def test_openrouter_parser_plumbing() -> None:
    calls: list[dict] = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(parsed=ENTRY, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=fake_parse)))
    result = OpenRouterParser("vendor/model", client=client).parse(
        "coffee 18,50", message_date=TODAY, categories=["Mâncare în oraș"]
    )
    assert result == ENTRY
    assert calls[0]["response_format"] is ParsedEntry
    assert calls[0]["messages"][0] == {"role": "system", "content": ai_parse.SYSTEM_PROMPT}
    assert calls[0]["extra_body"] == {"reasoning": {"effort": "low"}}
    OpenRouterParser("v/m", client=client, effort="high").parse(
        "x", message_date=TODAY, categories=[]
    )
    assert calls[1]["extra_body"] == {"reasoning": {"effort": "high"}}
