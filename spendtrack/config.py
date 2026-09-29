"""Load and validate the machine settings from the .env file."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


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
    port_text = os.environ.get("WEB_PORT", "8000").strip()
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

    return Config(
        data_dir=data_dir,
        web_host=web_host,
        web_port=web_port,
        timezone=timezone,
        allow_remote=allow_remote,
        basic_auth_user=user,
        basic_auth_password=password,
    )
