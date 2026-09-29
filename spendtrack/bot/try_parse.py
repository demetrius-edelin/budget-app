"""Try the model parse from the terminal, without Telegram.

Usage: uv run python -m spendtrack.bot.try_parse "coffee 18,50" "drove 42 km to Cluj"
The command reads .env for the provider and the key, prints the model output and
the values the core would save. It saves nothing.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime

from spendtrack.config import ConfigError, load_config
from spendtrack.core.ai_parse import draft_from_entry, make_parser
from spendtrack.core.categories import list_categories
from spendtrack.core.errors import SpendtrackError
from spendtrack.db.migrate import upgrade_to_head
from spendtrack.db.seed import seed
from spendtrack.db.session import make_engine, make_session_factory, session_scope


def main(argv: list[str] | None = None) -> int:
    texts = argv if argv is not None else sys.argv[1:]
    if not texts:
        print(__doc__)
        return 2
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    config.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_to_head(config.db_url)
    engine = make_engine(config.db_url)
    factory = make_session_factory(engine)
    parser = make_parser(config.ai_provider, config.ai_model, config.ai_effort)
    today = datetime.now(config.tz).date()
    with session_scope(factory) as db:
        seed(db)
        categories = list_categories(db)
        names = [c.name for c in categories]
        for text in texts:
            print(f"\n> {text}")
            try:
                entry = parser.parse(text, message_date=today, categories=names)
            except SpendtrackError as exc:
                print(f"  parse failed: {exc}")
                continue
            print("  model output:", json.dumps(entry.model_dump(exclude_none=True)))
            try:
                draft = draft_from_entry(entry, categories, today)
            except SpendtrackError as exc:
                print(f"  reply would be: {exc}")
                continue
            values = {k: str(v) for k, v in asdict(draft).items() if v not in (None, [], {})}
            print("  core values:", json.dumps(values, ensure_ascii=False))
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
