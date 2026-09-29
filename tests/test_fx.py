from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from spendtrack.core import fx

SAMPLE_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="https://www.bnr.ro/xsd">
<Header><PublishingDate>2026-09-28</PublishingDate></Header>
<Body><OrigCurrency>RON</OrigCurrency>
<Cube date="2026-09-25"><Rate currency="EUR">5.2718</Rate>
<Rate currency="HUF" multiplier="100">1.3247</Rate></Cube>
<Cube date="2026-09-28"><Rate currency="EUR">5.2786</Rate><Rate currency="USD">4.5</Rate></Cube>
</Body></DataSet>"""

TODAY = date(2026, 9, 29)


def test_parse_rates_reads_one_currency_and_the_multiplier() -> None:
    eur = fx.parse_rates(SAMPLE_XML)
    assert eur == {date(2026, 9, 25): Decimal("5.2718"), date(2026, 9, 28): Decimal("5.2786")}
    huf = fx.parse_rates(SAMPLE_XML, "HUF")
    assert huf == {date(2026, 9, 25): Decimal("0.013247")}


def test_rate_on_falls_back_to_the_latest_earlier_day() -> None:
    rates = fx.parse_rates(SAMPLE_XML)
    assert fx.rate_on(rates, date(2026, 9, 29)) == (date(2026, 9, 28), Decimal("5.2786"))
    assert fx.rate_on(rates, date(2026, 9, 26)) == (date(2026, 9, 25), Decimal("5.2718"))
    assert fx.rate_on(rates, date(2026, 9, 24)) is None


def test_convert_minor_rounds_half_up() -> None:
    assert fx.convert_minor(52786, Decimal("5.2786")) == 10000
    assert fx.convert_minor(10000, Decimal("5.2786")) == 1894  # 18.9444...
    assert fx.convert_minor(1, Decimal("5.2786")) == 0


def test_download_happens_once_per_day(tmp_path: Path) -> None:
    calls: list[int] = []

    def fetch(year: int) -> bytes:
        calls.append(year)
        return SAMPLE_XML

    first = fx.eur_rate(tmp_path, TODAY, fetch=fetch)
    second = fx.eur_rate(tmp_path, TODAY, fetch=fetch)
    assert calls == [2026]
    assert first == second
    assert first is not None
    assert (first.day, first.rate, first.fetched_on) == (
        date(2026, 9, 28),
        Decimal("5.2786"),
        TODAY,
    )
    assert fx.cache_file(tmp_path, 2026).read_bytes() == SAMPLE_XML

    fx.eur_rate(tmp_path, TODAY + timedelta(days=1), fetch=fetch)
    assert calls == [2026, 2026]


def test_failed_download_keeps_the_cache_and_retries_after_an_hour(tmp_path: Path) -> None:
    fx.eur_rate(tmp_path, TODAY - timedelta(days=1), fetch=lambda year: SAMPLE_XML)
    attempts: list[int] = []

    def broken(year: int) -> bytes:
        attempts.append(year)
        raise OSError("offline")

    start = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    assert fx.refresh_if_needed(tmp_path, TODAY, fetch=broken, now=start) is False
    assert (
        fx.refresh_if_needed(tmp_path, TODAY, fetch=broken, now=start + timedelta(minutes=30))
        is False
    )
    assert attempts == [2026]
    assert (
        fx.refresh_if_needed(tmp_path, TODAY, fetch=broken, now=start + timedelta(hours=2)) is False
    )
    assert attempts == [2026, 2026]
    rate = fx.eur_rate(tmp_path, TODAY, fetch=broken)
    assert rate is not None and rate.rate == Decimal("5.2786")


def test_no_cache_and_no_network_gives_no_rate(tmp_path: Path) -> None:
    def broken(year: int) -> bytes:
        raise OSError("offline")

    assert fx.eur_rate(tmp_path, TODAY, fetch=broken) is None


def test_january_also_downloads_the_previous_year(tmp_path: Path) -> None:
    calls: list[int] = []

    def fetch(year: int) -> bytes:
        calls.append(year)
        return SAMPLE_XML.replace(b"2026-09", b"2025-12") if year == 2025 else b"<DataSet/>"

    rate = fx.eur_rate(tmp_path, date(2026, 1, 2), fetch=fetch)
    assert calls == [2025, 2026]
    assert rate is not None and rate.day == date(2025, 12, 28)
