"""Start Spendtrack: migrate the database, seed it, write the daily backup, serve the web app."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler

import uvicorn

from spendtrack.config import Config, ConfigError, load_config
from spendtrack.core import backup as backup_core
from spendtrack.core import settings as settings_core
from spendtrack.db.migrate import upgrade_to_head
from spendtrack.db.seed import seed
from spendtrack.db.session import make_engine, make_session_factory, session_scope
from spendtrack.web.app import create_app

log = logging.getLogger("spendtrack")


def setup_logging(config: Config) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        config.log_dir / "spendtrack.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler, console])


def open_browser_later(url: str, delay: float = 1.2) -> None:
    timer = threading.Timer(delay, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spendtrack", description="Run the Spendtrack web app.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    parser.add_argument("--env", default=".env", help="Path of the .env file (default: .env).")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.env)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    config.data_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(config)
    log.info("Data folder: %s", config.data_dir)

    upgrade_to_head(config.db_url)
    engine = make_engine(config.db_url)
    factory = make_session_factory(engine)
    with session_scope(factory) as db:
        seed(db)
        keep = settings_core.backup_keep_days(db)
    today = datetime.now(config.tz).date()
    written = backup_core.backup_if_needed(config.db_path, config.backup_dir, keep, today)
    if written is not None:
        log.info("Backup written: %s", written)

    app = create_app(config, factory)
    url = f"http://{config.web_host}:{config.web_port}"
    log.info("Spendtrack runs at %s", url)
    if not args.no_browser:
        open_browser_later(url)
    uvicorn.run(app, host=config.web_host, port=config.web_port, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
