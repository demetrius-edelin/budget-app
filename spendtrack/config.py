"""Load and validate the machine settings from the .env file."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

AI_PROVIDERS = ("anthropic", "openai", "openrouter")
AI_EFFORTS = ("off", "none", "minimal", "low", "medium", "high", "xhigh", "max")


class ConfigError(Exception):
    """The .env file holds an invalid value."""


@dataclass(frozen=True)
class Config:
    """The machine settings of one installation."""

    data_dir: Path
    web_host: str
    web_port: int
    timezone: str
    allow_remote: bool
    basic_auth_user: str | None
    basic_auth_password: str | None
    telegram_bot_token: str | None = None
    allowed_telegram_user_ids: frozenset[int] = frozenset()
    ai_provider: str = "anthropic"
    ai_model: str | None = None
    ai_effort: str = "low"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "spendtrack.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def fx_dir(self) -> Path:
        return self.data_dir / "fx"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def load_config(env_file: str | os.PathLike[str] | None = ".env") -> Config:
    """Read the .env file and the environment, then validate the values.

    Raise ConfigError if a value is invalid or if the host is not loopback
    without remote access and basic-auth credentials.
    """
    if env_file is not None:
        load_dotenv(env_file, override=False)

    data_dir = Path(os.environ.get("DATA_DIR", "~/spendtrack-data")).expanduser()
    web_host = os.environ.get("WEB_HOST", "127.0.0.1").strip()
    port_text = os.environ.get("WEB_PORT", "27431").strip()
    timezone = os.environ.get("TIMEZONE", "Europe/Bucharest").strip()
    allow_remote = _as_bool(os.environ.get("ALLOW_REMOTE"))
    user = os.environ.get("BASIC_AUTH_USER") or None
    password = os.environ.get("BASIC_AUTH_PASSWORD") or None

    try:
        web_port = int(port_text)
    except ValueError as exc:
        raise ConfigError(f"WEB_PORT must be a number, got {port_text!r}") from exc
    if not 1 <= web_port <= 65535:
        raise ConfigError(f"WEB_PORT must be between 1 and 65535, got {web_port}")

    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"TIMEZONE is not a known time zone: {timezone!r}") from exc

    if not _is_loopback(web_host) and not (allow_remote and user and password):
        raise ConfigError(
            f"WEB_HOST={web_host!r} is not a loopback address. "
            "Set ALLOW_REMOTE=true, BASIC_AUTH_USER and BASIC_AUTH_PASSWORD to permit it."
        )

    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() or None
    ids_text = os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "")
    allowed: set[int] = set()
    for part in ids_text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            allowed.add(int(part))
        except ValueError as exc:
            raise ConfigError(
                f"ALLOWED_TELEGRAM_USER_IDS must hold numbers separated by commas, got {part!r}"
            ) from exc
    provider = (os.environ.get("AI_PROVIDER") or "anthropic").strip().lower()
    if provider not in AI_PROVIDERS:
        raise ConfigError(f"AI_PROVIDER must be one of {', '.join(AI_PROVIDERS)}, got {provider!r}")
    ai_model = (os.environ.get("AI_MODEL") or "").strip() or None
    if token and provider != "anthropic" and not ai_model:
        raise ConfigError(f"AI_MODEL is required when AI_PROVIDER is {provider}")
    key_names = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
    if token and provider in key_names and not os.environ.get(key_names[provider]):
        raise ConfigError(f"{key_names[provider]} is required when AI_PROVIDER is {provider}")
    effort = (os.environ.get("AI_EFFORT") or "low").strip().lower()
    if effort not in AI_EFFORTS:
        raise ConfigError(f"AI_EFFORT must be one of {', '.join(AI_EFFORTS)}, got {effort!r}")

    return Config(
        data_dir=data_dir,
        web_host=web_host,
        web_port=web_port,
        timezone=timezone,
        allow_remote=allow_remote,
        basic_auth_user=user,
        basic_auth_password=password,
        telegram_bot_token=token,
        allowed_telegram_user_ids=frozenset(allowed),
        ai_provider=provider,
        ai_model=ai_model,
        ai_effort=effort,
    )
