"""Daily backup with the online backup API of SQLite."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

PREFIX = "spendtrack-"
SUFFIX = ".db"


def list_backups(backup_dir: Path) -> list[Path]:
    """Return the backup files, newest first."""
    if not backup_dir.exists():
        return []
    files = [p for p in backup_dir.iterdir() if p.name.startswith(PREFIX) and p.suffix == SUFFIX]
    return sorted(files, key=lambda p: p.name, reverse=True)


def prune_backups(backup_dir: Path, keep: int) -> list[Path]:
    """Delete every backup beyond the newest `keep` files. Return the deleted paths."""
    removed: list[Path] = []
    for path in list_backups(backup_dir)[keep:]:
        path.unlink()
        removed.append(path)
    return removed


def backup_if_needed(db_path: Path, backup_dir: Path, keep: int, today: date) -> Path | None:
    """Write today's backup if it does not exist yet, then prune. Return the new file or None."""
    target = backup_dir / f"{PREFIX}{today:%Y-%m-%d}{SUFFIX}"
    if target.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    prune_backups(backup_dir, keep)
    return target
