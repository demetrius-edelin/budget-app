"""Read and write the key-value settings that the owner edits on the Settings page."""

from __future__ import annotations

from sqlalchemy.orm import Session

from spendtrack.core.errors import ValidationError
from spendtrack.core.money import NUMBER_FORMATS
from spendtrack.db.models import Setting

FUEL_COST_MODES = ("km", "receipts")


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(Setting, key)
    if row is None:
        return default
    return row.value


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def number_format(session: Session) -> str:
    value = get_setting(session, "number_format", "ro-RO") or "ro-RO"
    return value if value in NUMBER_FORMATS else "ro-RO"


def currency(session: Session) -> str:
    return get_setting(session, "currency", "RON") or "RON"


def fuel_cost_mode(session: Session) -> str:
    value = get_setting(session, "fuel_cost_mode", "km") or "km"
    return value if value in FUEL_COST_MODES else "km"


def monthly_target_minor(session: Session) -> int | None:
    value = get_setting(session, "monthly_target_minor", "")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def backup_keep_days(session: Session) -> int:
    value = get_setting(session, "backup_keep_days", "30") or "30"
    try:
        return max(1, int(value))
    except ValueError:
        return 30


def set_fuel_cost_mode(session: Session, mode: str) -> None:
    if mode not in FUEL_COST_MODES:
        raise ValidationError("Modul de cost al combustibilului trebuie să fie km sau receipts.")
    set_setting(session, "fuel_cost_mode", mode)


def set_number_format(session: Session, value: str) -> None:
    if value not in NUMBER_FORMATS:
        raise ValidationError("Formatul numerelor trebuie să fie ro-RO sau en-US.")
    set_setting(session, "number_format", value)


def set_monthly_target(session: Session, minor: int | None) -> None:
    set_setting(session, "monthly_target_minor", "" if minor is None else str(minor))


def set_backup_keep_days(session: Session, days: int) -> None:
    if days < 1:
        raise ValidationError("Păstrează cel puțin o copie de rezervă.")
    set_setting(session, "backup_keep_days", str(days))
