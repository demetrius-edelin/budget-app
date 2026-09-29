from pathlib import Path

from sqlalchemy import inspect

from spendtrack.db.migrate import upgrade_to_head
from spendtrack.db.models import Base
from spendtrack.db.seed import seed
from spendtrack.db.session import make_engine, make_session_factory


def test_migration_matches_the_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    engine = make_engine(url)
    migrated = inspect(engine)
    expected = set(Base.metadata.tables)
    assert expected <= set(migrated.get_table_names())
    for table in expected:
        model_columns = {c.name for c in Base.metadata.tables[table].columns}
        db_columns = {c["name"] for c in migrated.get_columns(table)}
        assert model_columns == db_columns, table
    with make_session_factory(engine)() as db:
        seed(db)
        seed(db)  # idempotent
        db.commit()
        from datetime import date

        from spendtrack.core.expenses import create_expense

        expense = create_expense(
            db, occurred_on=date(2026, 9, 29), amount_minor=100, category_id=1, source="telegram"
        )
        db.commit()
        assert expense.source == "telegram"
        from datetime import UTC, datetime

        from spendtrack.db.models import InboundMessage

        for update_id in (1, 2):  # an edit shares the chat and message ids of the original
            db.add(
                InboundMessage(
                    tg_update_id=update_id,
                    tg_chat_id=5,
                    tg_message_id=7,
                    sender_id=5,
                    sent_at=datetime.now(UTC),
                    text="x",
                    status="rejected",
                    reply="r",
                )
            )
        db.commit()
    engine.dispose()


def test_upgrade_keeps_the_app_logging_configuration(tmp_path: Path) -> None:
    import logging

    root = logging.getLogger()
    handler = logging.NullHandler()
    root.addHandler(handler)
    level_before = root.level
    try:
        upgrade_to_head(f"sqlite:///{tmp_path / 'log.db'}")
        assert handler in root.handlers
        assert root.level == level_before
    finally:
        root.removeHandler(handler)
