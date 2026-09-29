import pytest

from spendtrack.config import ConfigError, load_config

KEYS = (
    "DATA_DIR",
    "WEB_HOST",
    "WEB_PORT",
    "TIMEZONE",
    "ALLOW_REMOTE",
    "BASIC_AUTH_USER",
    "BASIC_AUTH_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "ALLOWED_TELEGRAM_USER_IDS",
    "AI_PROVIDER",
    "AI_MODEL",
    "AI_EFFORT",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_are_loopback() -> None:
    config = load_config(env_file=None)
    assert config.web_host == "127.0.0.1"
    assert config.web_port == 27431
    assert config.timezone == "Europe/Bucharest"
    assert config.db_path.name == "spendtrack.db"


def test_non_loopback_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    with pytest.raises(ConfigError, match="not a loopback"):
        load_config(env_file=None)


def test_non_loopback_needs_remote_flag_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("ALLOW_REMOTE", "true")
    with pytest.raises(ConfigError):
        load_config(env_file=None)
    monkeypatch.setenv("BASIC_AUTH_USER", "demi")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "secret")
    assert load_config(env_file=None).allow_remote is True


def test_bad_timezone_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIMEZONE", "Mars/Olympus")
    with pytest.raises(ConfigError, match="TIMEZONE"):
        load_config(env_file=None)


def test_ai_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config(env_file=None)
    assert (config.ai_provider, config.ai_model, config.ai_effort) == ("anthropic", None, "low")
    monkeypatch.setenv("AI_EFFORT", "High")
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_MODEL", "vendor/model")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "1, 2")
    config = load_config(env_file=None)
    assert (config.ai_provider, config.ai_model, config.ai_effort) == (
        "openrouter",
        "vendor/model",
        "high",
    )
    assert config.allowed_telegram_user_ids == frozenset({1, 2})
    monkeypatch.setenv("AI_EFFORT", "turbo")
    with pytest.raises(ConfigError, match="AI_EFFORT"):
        load_config(env_file=None)
    monkeypatch.setenv("AI_EFFORT", "low")
    monkeypatch.setenv("AI_MODEL", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    with pytest.raises(ConfigError, match="AI_MODEL is required"):
        load_config(env_file=None)
    monkeypatch.setenv("AI_MODEL", "vendor/model")
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY is required"):
        load_config(env_file=None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert load_config(env_file=None).ai_provider == "openrouter"
