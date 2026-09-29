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
    engine.dispose()
