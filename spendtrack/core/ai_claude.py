"""The Anthropic provider: one Claude call with a structured output schema."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import anthropic

from spendtrack.core.ai_parse import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    ParsedEntry,
    ParseError,
    build_user_message,
)

log = logging.getLogger(__name__)

# The Claude API knows low to max. The lower OpenAI levels map to low, and "off" sends nothing.
_EFFORT_MAP = {"none": "low", "minimal": "low"}


def output_config_for(effort: str) -> dict[str, str] | None:
    if effort == "off":
        return None
    return {"effort": _EFFORT_MAP.get(effort, effort)}


class ClaudeParser:
    """Parse messages with the Claude API. The client reads ANTHROPIC_API_KEY from the env."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        client: anthropic.Anthropic | None = None,
        effort: str = DEFAULT_EFFORT,
    ):
        self.model = model
        self.effort = effort
        self.client = client or anthropic.Anthropic()

    def parse(self, text: str, *, message_date: date, categories: list[str]) -> ParsedEntry:
        extra: dict[str, Any] = {}
        output_config = output_config_for(self.effort)
        if output_config is not None:
            extra["output_config"] = output_config
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                output_format=ParsedEntry,
                **extra,
                messages=[
                    {"role": "user", "content": build_user_message(text, message_date, categories)}
                ],
            )
        except anthropic.RateLimitError as exc:
            raise ParseError(
                "Parserul este ocupat. Trimite mesajul din nou peste un minut."
            ) from exc
        except anthropic.APIStatusError as exc:
            log.error("Claude API error %s: %s", exc.status_code, exc.message)
            raise ParseError(
                "Parserul a returnat o eroare. Trimite mesajul din nou mai târziu."
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ParseError(
                "Parserul nu poate fi contactat. Trimite mesajul din nou mai târziu."
            ) from exc
        if response.stop_reason == "refusal":
            return ParsedEntry(
                kind="unclear", question="Nu am înțeles mesajul. Trimite suma și câteva cuvinte."
            )
        parsed = response.parsed_output
        if parsed is None:
            raise ParseError("Parserul nu a returnat nicio intrare. Trimite mesajul din nou.")
        log.info(
            "Parsed a message with %s: %s input, %s output tokens",
            self.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return parsed
