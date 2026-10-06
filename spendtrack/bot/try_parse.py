"""Try the model parse from the terminal, without Telegram.

Usage:
  uv run python -m spendtrack.bot.try_parse "coffee 18,50" "drove 42 km to Cluj"
  uv run python -m spendtrack.bot.try_parse --image receipt.jpg ["caption"]

The command reads .env for the provider and the key, prints the model output and
the values the core would save. It saves nothing. With --image, the command sends
the photo with the optional caption, as the bot does for a receipt photo.
"""

from __future__ import annotations

import json
import mimetypes
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from spendtrack.config import ConfigError, load_config
from spendtrack.core.ai_parse import (
    IMAGE_MEDIA_TYPES,
    MAX_IMAGE_BYTES,
    ImageInput,
    draft_from_entry,
    make_parser,
)
from spendtrack.core.categories import list_categories
from spendtrack.core.errors import SpendtrackError
from spendtrack.db.migrate import upgrade_to_head
from spendtrack.db.seed import seed
from spendtrack.db.session import make_engine, make_session_factory, session_scope


def load_image(path: Path) -> ImageInput:
    """Read a photo from disk. Raise ValueError for a type or a size the bot rejects."""
    media_type = mimetypes.guess_type(path.name)[0]
    if media_type not in IMAGE_MEDIA_TYPES:
        raise ValueError(f"{path.name}: use a JPEG, PNG or WebP file")
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"{path.name}: the file is larger than {MAX_IMAGE_BYTES} bytes")
    return ImageInput(data=data, media_type=media_type)


def main(argv: list[str] | None = None) -> int:
    texts = argv if argv is not None else sys.argv[1:]
    image: ImageInput | None = None
    if texts[:1] == ["--image"]:
        if len(texts) < 2:
            print(__doc__)
            return 2
        try:
            image = load_image(Path(texts[1]))
        except (OSError, ValueError) as exc:
            print(f"Image error: {exc}", file=sys.stderr)
            return 2
        # The rest of the arguments is the caption of the one photo.
        texts = [" ".join(texts[2:])]
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
            print(f"\n> {text}" if image is None else f"\n> [photo] {text}")
            try:
                entry = parser.parse(text, message_date=today, categories=names, image=image)
            except SpendtrackError as exc:
                print(f"  parse failed: {exc}")
                continue
            print("  model output:", json.dumps(entry.model_dump(exclude_none=True)))
            try:
                draft = draft_from_entry(entry, categories, today, from_image=image is not None)
            except SpendtrackError as exc:
                print(f"  reply would be: {exc}")
                continue
            values = {k: str(v) for k, v in asdict(draft).items() if v not in (None, [], {})}
            values.pop("items", None)
            for number, item in enumerate(draft.items, start=1):
                values[f"item {number}"] = f"{item.description} {item.amount_minor}"
            print("  core values:", json.dumps(values, ensure_ascii=False))
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
