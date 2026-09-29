"""The OpenAI and OpenRouter providers. OpenRouter speaks the OpenAI API at another base URL."""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import openai

from spendtrack.core.ai_parse import (
    DEFAULT_EFFORT,
    SYSTEM_PROMPT,
    ParsedEntry,
    ParseError,
    build_user_message,
)

log = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _wrap(exc: Exception) -> ParseError:
    if isinstance(exc, openai.RateLimitError):
        return ParseError("Parserul este ocupat. Trimite mesajul din nou peste un minut.")
    if isinstance(exc, openai.APIStatusError):
        log.error("OpenAI-compatible API error %s: %s", exc.status_code, exc.message)
        return ParseError("Parserul a returnat o eroare. Trimite mesajul din nou mai târziu.")
    return ParseError("Parserul nu poate fi contactat. Trimite mesajul din nou mai târziu.")


class OpenAIParser:
    """Parse messages with the OpenAI Responses API. Reads OPENAI_API_KEY from the environment.

    The effort goes into the `reasoning.effort` field: none, minimal, low, medium, high,
    xhigh or max. Not every model accepts every value; "off" sends no reasoning field.
    """

    def __init__(
        self, model: str, client: openai.OpenAI | None = None, effort: str = DEFAULT_EFFORT
    ):
        self.model = model
        self.effort = effort
        self.client = client or openai.OpenAI()

    def parse(self, text: str, *, message_date: date, categories: list[str]) -> ParsedEntry:
        extra: dict[str, Any] = {}
        if self.effort != "off":
            extra["reasoning"] = {"effort": self.effort}
        try:
            response = self.client.responses.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=build_user_message(text, message_date, categories),
                text_format=ParsedEntry,
                max_output_tokens=4096,
                **extra,
            )
        except (openai.APIStatusError, openai.APIConnectionError) as exc:
            raise _wrap(exc) from exc
        parsed = response.output_parsed
        if parsed is None:
            raise ParseError("Parserul nu a returnat nicio intrare. Trimite mesajul din nou.")
        log.info("Parsed a message with %s", self.model)
        return parsed


class OpenRouterParser:
    """Parse messages through OpenRouter with the chat completions API and a JSON schema.

    The model id follows the OpenRouter catalog, for example "anthropic/claude-opus-5-5"
    or "openai/gpt-5.1". Reads OPENROUTER_API_KEY from the environment.
    """

    def __init__(
        self, model: str, client: openai.OpenAI | None = None, effort: str = DEFAULT_EFFORT
    ):
        self.model = model
        self.effort = effort
        self.client = client or openai.OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=os.environ.get("OPENROUTER_API_KEY") or "missing",
            default_headers={"X-Title": "Spendtrack"},
        )

    def parse(self, text: str, *, message_date: date, categories: list[str]) -> ParsedEntry:
        extra: dict[str, Any] = {}
        if self.effort != "off":
            # OpenRouter reads the same reasoning.effort field and maps it per vendor.
            extra["extra_body"] = {"reasoning": {"effort": self.effort}}
        try:
            completion = self.client.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_message(text, message_date, categories)},
                ],
                response_format=ParsedEntry,
                max_completion_tokens=4096,
                **extra,
            )
        except (openai.APIStatusError, openai.APIConnectionError) as exc:
            raise _wrap(exc) from exc
        if not completion.choices:
            raise ParseError("Parserul nu a returnat nicio intrare. Trimite mesajul din nou.")
        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            return ParsedEntry(
                kind="unclear", question="Nu am înțeles mesajul. Trimite suma și câteva cuvinte."
            )
        parsed = message.parsed
        if parsed is None:
            raise ParseError("Parserul nu a returnat nicio intrare. Trimite mesajul din nou.")
        log.info("Parsed a message with %s via OpenRouter", self.model)
        return parsed
