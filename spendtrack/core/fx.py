"""Exchange rates from the BNR (National Bank of Romania), cached once per day.

The BNR publishes one XML file per year with the reference rates of every
business day. The app downloads the file of the current year at most once per
day into DATA_DIR/fx and reads the EUR rate from the cache. When today has no
rate yet, the latest earlier day is used.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

log = logging.getLogger(__name__)

RATES_URL = "https://curs.bnr.ro/files/xml/years/nbrfxrates{year}.xml"
RETRY_AFTER = timedelta(hours=1)
Fetcher = Callable[[int], bytes]


@dataclass(frozen=True)
class FxRate:
    """The rate in use: RON per one unit of the currency, and the day it is from."""

    currency: str
    day: date
    rate: Decimal
    fetched_on: date | None


def fetch_rates_xml(year: int, timeout: float = 8.0) -> bytes:
    """Download the BNR file of one year."""
    with urllib.request.urlopen(RATES_URL.format(year=year), timeout=timeout) as response:
        return response.read()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_rates(xml_bytes: bytes, currency: str = "EUR") -> dict[date, Decimal]:
    """Return {day: rate} for one currency. A multiplier attribute is applied."""
    root = ET.fromstring(xml_bytes)
    rates: dict[date, Decimal] = {}
    for cube in root.iter():
        if _local_name(cube.tag) != "Cube" or not cube.get("date"):
            continue
        day = date.fromisoformat(cube.get("date", ""))
        for rate in cube:
            if _local_name(rate.tag) == "Rate" and rate.get("currency") == currency and rate.text:
                multiplier = Decimal(rate.get("multiplier", "1"))
                rates[day] = Decimal(rate.text.strip()) / multiplier
    return rates


def cache_file(fx_dir: Path, year: int) -> Path:
    return fx_dir / f"nbrfxrates{year}.xml"


def _state_file(fx_dir: Path) -> Path:
    return fx_dir / "state.json"


def _load_state(fx_dir: Path) -> dict[str, str]:
    path = _state_file(fx_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save_state(fx_dir: Path, state: dict[str, str]) -> None:
    fx_dir.mkdir(parents=True, exist_ok=True)
    _state_file(fx_dir).write_text(json.dumps(state), encoding="utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_bytes(data)
    temp.replace(path)


def refresh_if_needed(
    fx_dir: Path, today: date, fetch: Fetcher = fetch_rates_xml, now: datetime | None = None
) -> bool:
    """Download the file of this year once per day. Return True when a download succeeded.

    After a failed attempt, the next attempt waits one hour. In January the
    file of the previous year is downloaded once too, so the first days of the
    year can fall back to the last rate of December.
    """
    state = _load_state(fx_dir)
    if state.get("fetched_on") == today.isoformat():
        return False
    now = now or datetime.now(UTC)
    last_failure = state.get("last_failure")
    if last_failure and now - datetime.fromisoformat(last_failure) < RETRY_AFTER:
        return False
    years = [today.year]
    if today.month == 1 and not cache_file(fx_dir, today.year - 1).exists():
        years.insert(0, today.year - 1)
    try:
        for year in years:
            data = fetch(year)
            parse_rates(data)
            _atomic_write(cache_file(fx_dir, year), data)
    except Exception as exc:  # noqa: BLE001
        log.warning("The BNR rates download failed: %s", exc)
        state["last_failure"] = now.isoformat()
        _save_state(fx_dir, state)
        return False
    state["fetched_on"] = today.isoformat()
    state.pop("last_failure", None)
    _save_state(fx_dir, state)
    return True


def load_rates(fx_dir: Path, today: date, currency: str = "EUR") -> dict[date, Decimal]:
    """Read the cached files of the previous year and of this year."""
    merged: dict[date, Decimal] = {}
    for year in (today.year - 1, today.year):
        path = cache_file(fx_dir, year)
        if not path.exists():
            continue
        try:
            merged.update(parse_rates(path.read_bytes(), currency))
        except (ET.ParseError, ValueError, ArithmeticError) as exc:
            log.warning("The cached BNR file %s is invalid: %s", path, exc)
    return merged


def rate_on(rates: dict[date, Decimal], day: date) -> tuple[date, Decimal] | None:
    """Return the rate of the day, or of the latest earlier day."""
    candidates = [d for d in rates if d <= day]
    if not candidates:
        return None
    best = max(candidates)
    return best, rates[best]


def eur_rate(fx_dir: Path, today: date, fetch: Fetcher = fetch_rates_xml) -> FxRate | None:
    """Refresh the cache when due, then return the EUR rate for today or the latest earlier day."""
    refresh_if_needed(fx_dir, today, fetch)
    found = rate_on(load_rates(fx_dir, today, "EUR"), today)
    if found is None:
        return None
    day, rate = found
    fetched = _load_state(fx_dir).get("fetched_on")
    return FxRate("EUR", day, rate, date.fromisoformat(fetched) if fetched else None)


def convert_minor(minor_ron: int, rate: Decimal) -> int:
    """Convert RON minor units into minor units of the currency, rounded half-up."""
    return int((Decimal(minor_ron) / rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
