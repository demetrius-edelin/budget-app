"""A minimal Telegram Bot API client with long polling. No public address is needed."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Protocol

log = logging.getLogger(__name__)


class TelegramError(Exception):
    """A Bot API call failed. The message never holds the token.

    retry_after holds the seconds Telegram asked us to wait after a rate limit.
    """

    def __init__(
        self, message: str, *, retry_after: float | None = None, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.status = status


class TelegramApi(Protocol):
    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]: ...

    def send_message(
        self, chat_id: int, text: str, reply_to_message_id: int | None = None
    ) -> None: ...


class TelegramClient:
    """Call the Bot API over HTTPS with the standard library."""

    def __init__(self, token: str) -> None:
        self._base = f"https://api.telegram.org/bot{token}/"

    def _call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        body = json.dumps(params).encode("utf-8")
        request = urllib.request.Request(
            self._base + method, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            retry_after: float | None = None
            try:
                error = json.loads(exc.read().decode("utf-8"))
                detail = error.get("description", "")
                wait = (error.get("parameters") or {}).get("retry_after")
                if wait is not None:
                    retry_after = float(wait)
            except (ValueError, OSError, TypeError):
                pass
            raise TelegramError(
                f"{method} failed with HTTP {exc.code}: {detail}",
                retry_after=retry_after,
                status=exc.code,
            ) from None
        except urllib.error.URLError as exc:
            raise TelegramError(f"{method} failed: {exc.reason}") from None
        if not payload.get("ok"):
            raise TelegramError(f"{method} failed: {payload.get('description', 'unknown error')}")
        return payload.get("result")

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "edited_message"],
        }
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", params, timeout=timeout + 15) or []

    def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_message_id is not None:
            params["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        self._call("sendMessage", params, timeout=20)
