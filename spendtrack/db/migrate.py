"""Run the Alembic migrations from code, so the app upgrades its database on start."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

ROOT = Path(__file__).resolve().parents[2]


def alembic_config(db_url: str) -> AlembicConfig:
    config = AlembicConfig(str(ROOT / "alembic.ini"))
    # The app configures logging itself. Alembic must not replace the root handlers.
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    config.set_main_option("sqlalchemy.url", db_url)
    os.environ["SPENDTRACK_DB_URL"] = db_url
    return config


def upgrade_to_head(db_url: str) -> None:
    """Create or upgrade the database schema."""
    command.upgrade(alembic_config(db_url), "head")
