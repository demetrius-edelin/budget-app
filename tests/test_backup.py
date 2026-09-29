import sqlite3
from datetime import date
from pathlib import Path

from spendtrack.core.backup import backup_if_needed, list_backups


def test_backup_once_per_day_and_prune(tmp_path: Path) -> None:
    db = tmp_path / "spendtrack.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    backups = tmp_path / "backups"

    first = backup_if_needed(db, backups, keep=2, today=date(2026, 9, 27))
    assert first is not None and first.name == "spendtrack-2026-09-27.db"
    assert backup_if_needed(db, backups, keep=2, today=date(2026, 9, 27)) is None
    backup_if_needed(db, backups, keep=2, today=date(2026, 9, 28))
    backup_if_needed(db, backups, keep=2, today=date(2026, 9, 29))
    assert [p.name for p in list_backups(backups)] == [
        "spendtrack-2026-09-29.db",
        "spendtrack-2026-09-28.db",
    ]
    copy = sqlite3.connect(backups / "spendtrack-2026-09-29.db")
    assert copy.execute("SELECT x FROM t").fetchall() == [(1,)]
    copy.close()
