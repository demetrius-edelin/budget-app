"""Web layer tests with the FastAPI test client. They cover every page and the main flows."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from spendtrack.config import Config
from spendtrack.core import expenses as expenses_core
from spendtrack.core import metrics
from spendtrack.db.models import Base
from spendtrack.db.seed import seed
from spendtrack.db.session import make_engine, make_session_factory
from spendtrack.web.app import create_app
from tests.conftest import PARAMS_FROM
from tests.test_fx import SAMPLE_XML


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        seed(db)
        metrics.set_param(db, "drive", "consumption_l_per_100km", Decimal("7.2"), PARAMS_FROM)
        metrics.set_param(db, "drive", "fuel_price_per_l", Decimal("8.28"), PARAMS_FROM)
        db.commit()
    config = Config(
        data_dir=tmp_path,
        web_host="127.0.0.1",
        web_port=8000,
        timezone="Europe/Bucharest",
        allow_remote=False,
        basic_auth_user=None,
        basic_auth_password=None,
    )
    app = create_app(config, factory, background_backup=False)
    app.state.session_factory = factory
    app.state.fx_fetch = lambda year: SAMPLE_XML  # no network in tests
    with TestClient(app) as test_client:
        test_client.factory = factory  # type: ignore[attr-defined]
        yield test_client
    engine.dispose()


def _db(client: TestClient) -> Session:
    return client.factory()  # type: ignore[attr-defined]


def _groceries_id(client: TestClient) -> int:
    with _db(client) as db:
        from spendtrack.core.categories import get_category_by_name

        return get_category_by_name(db, "Alimente").id


def test_pages_render(client: TestClient) -> None:
    for path in ("/", "/add", "/expenses", "/review", "/reports", "/settings"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Spendtrack" in response.text


def test_add_expense_then_it_shows_in_the_list(client: TestClient) -> None:
    response = client.post(
        "/add/expense",
        data={
            "occurred_on": "2026-09-29",
            "amount": "18,50",
            "category_id": str(_groceries_id(client)),
            "description": "Bread",
            "necessity": "4",
            "cheaper_alt": "1",
            "cheaper_alt_amount": "8",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/add?saved=1"
    page = client.get("/add?saved=1")
    assert "Salvat" in page.text and "18,50" in page.text
    listing = client.get("/expenses")
    assert "Bread" in listing.text and "18,50" in listing.text
    assert "mai ieftin 8,00" in listing.text


def test_add_expense_rejects_thousands_separators(client: TestClient) -> None:
    response = client.post(
        "/add/expense",
        data={"amount": "1.234,50", "category_id": str(_groceries_id(client))},
    )
    assert response.status_code == 400
    assert "separatori de mii" in response.text
    with _db(client) as db:
        assert expenses_core.list_expenses(db) == []


def test_metric_preview_and_save(client: TestClient) -> None:
    preview = client.post(
        "/add/metric/preview", data={"quantity": "42", "occurred_on": "2026-09-29"}
    )
    assert preview.status_code == 200
    assert "25,04" in preview.text and "42 km × 7.2 L/100 km × 8.28 RON/L" in preview.text

    missing = client.post(
        "/add/metric/preview", data={"quantity": "42", "occurred_on": "2026-08-15"}
    )
    assert "Setează mai întâi consumul în Setări." in missing.text

    saved = client.post(
        "/add/metric",
        data={
            "quantity": "42",
            "occurred_on": "2026-09-29",
            "consumption": "6.5",
            "fuel_price": "7,99",
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert "21,81" in saved.text and "6.5 L/100 km" in saved.text


def test_items_inline_and_totals(client: TestClient) -> None:
    category_id = _groceries_id(client)
    with _db(client) as db:
        expense = expenses_core.create_expense(
            db, occurred_on=date(2026, 9, 29), amount_minor=10000, category_id=category_id
        )
        db.commit()
        expense_id = expense.id

    added = client.post(
        f"/expenses/{expense_id}/items",
        data={"item_description": "Wine", "item_amount": "50", "item_necessity": "3"},
    )
    assert added.status_code == 200
    assert "Wine" in added.text and "Nespecificat" in added.text
    assert 'id="view-total" hx-swap-oob="true"' in added.text
    assert "100,00" in added.text

    rejected = client.post(
        f"/expenses/{expense_id}/items",
        data={"item_description": "Cheese", "item_amount": "60"},
    )
    assert rejected.status_code == 400
    assert "depășesc" in rejected.text

    below = client.post(
        f"/expenses/{expense_id}/edit",
        data={"occurred_on": "2026-09-29", "amount": "40", "category_id": str(category_id)},
    )
    assert below.status_code == 400
    assert "sub totalul articolelor de 50.00" in below.text

    deleted = client.post(f"/expenses/{expense_id}/delete")
    assert "Șters #" in deleted.text and "Restaurează" in deleted.text
    assert "0,00" in deleted.text
    restored = client.post(f"/expenses/{expense_id}/restore")
    assert "Șters #" not in restored.text


def test_review_rates_and_moves_on(client: TestClient) -> None:
    category_id = _groceries_id(client)
    with _db(client) as db:
        first = expenses_core.create_expense(
            db, occurred_on=date(2026, 9, 27), amount_minor=1000, category_id=category_id
        )
        expenses_core.create_expense(
            db, occurred_on=date(2026, 9, 28), amount_minor=2000, category_id=category_id
        )
        db.commit()
        first_id = first.id
    page = client.get("/review")
    assert "1 din 2 neevaluate" in page.text and f"#{first_id}" in page.text
    card = client.post(f"/review/{first_id}/rate", data={"level": "3", "index": "0"})
    assert "1 din 1 neevaluate" in card.text
    with _db(client) as db:
        assert expenses_core.get_expense(db, first_id).necessity == 3
    toggled = client.post(f"/review/{first_id + 1}/toggle", data={"flag": "cheaper", "index": "0"})
    assert "Alternativă mai ieftină: da" in toggled.text
    done = client.post(f"/review/{first_id + 1}/rate", data={"level": "1", "index": "0"})
    assert "Nimic de evaluat" in done.text


def test_csv_export(client: TestClient) -> None:
    category_id = _groceries_id(client)
    with _db(client) as db:
        expense = expenses_core.create_expense(
            db,
            occurred_on=date(2026, 9, 29),
            amount_minor=10000,
            category_id=category_id,
            description="Market",
        )
        expenses_core.add_items(db, expense.id, [expenses_core.ItemInput("Wine", 5000)])
        db.commit()
    response = client.get("/expenses/export.csv?mode=lines")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = response.text.strip().splitlines()
    assert rows[0].startswith("expense_id,item_id,date")
    assert any("Wine,50.00" in row for row in rows)
    assert any("Nespecificat,50.00" in row for row in rows)
    plain = client.get("/expenses/export.csv?mode=expenses&start=2026-09-01")
    assert "Market,100.00,RON" in plain.text


def test_settings_forms(client: TestClient) -> None:
    response = client.post(
        "/settings/general",
        data={
            "fuel_cost_mode": "receipts",
            "number_format": "en-US",
            "monthly_target": "3000",
            "backup_keep_days": "10",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200 and "Salvat." in response.text
    assert "3000.00" in response.text
    added = client.post(
        "/settings/categories",
        data={"name": "Pets", "default_necessity": "2"},
        follow_redirects=True,
    )
    assert "Pets" in added.text
    duplicate = client.post("/settings/categories", data={"name": "pets"})
    assert duplicate.status_code == 400 and "Există deja" in duplicate.text
    param = client.post(
        "/settings/metrics/drive/params",
        data={"name": "fuel_price_per_l", "value": "8,50", "effective_from": "2026-09-29"},
        follow_redirects=True,
    )
    assert "8.5" in param.text


def test_reports_page_with_data(client: TestClient) -> None:
    category_id = _groceries_id(client)
    with _db(client) as db:
        expenses_core.create_expense(
            db,
            occurred_on=date(2026, 9, 28),
            amount_minor=3500,
            category_id=category_id,
            necessity=3,
            cheaper_alt_minor=1000,
            recurring=True,
        )
        db.commit()
    response = client.get("/reports?kind=week&date=2026-09-29")
    assert response.status_code == 200
    assert "35,00" in response.text and "Economie posibilă" in response.text
    assert 'id="trend-data"' in response.text
    month = client.get("/reports?kind=month&date=not-a-date")
    assert month.status_code == 200


def test_add_page_marks_the_fuel_category(client: TestClient) -> None:
    page = client.get("/add")
    assert 'data-fuel="1">Combustibil și mașină' in page.text
    assert 'id="fuel-hint" class="hint hidden" data-mode="km"' in page.text


def test_settings_category_row_update(client: TestClient) -> None:
    category_id = _groceries_id(client)
    response = client.post(
        f"/settings/categories/{category_id}",
        data={"name": "Food", "default_necessity": "1", "sort_order": "3", "archived": "1"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert f'id="cat-{category_id}"' in response.text
    with _db(client) as db:
        from spendtrack.core.categories import get_category

        category = get_category(db, category_id)
        assert (category.name, category.default_necessity, category.archived) == ("Food", 1, True)
    add_page = client.get("/add")
    assert "Food" not in add_page.text


def test_overview_calendar_links_to_the_day(client: TestClient) -> None:
    with _db(client) as db:
        expenses_core.create_expense(
            db,
            occurred_on=date(2026, 9, 12),
            amount_minor=12345,
            category_id=_groceries_id(client),
        )
        db.commit()
    page = client.get("/?month=2026-09")
    assert 'href="/expenses?start=2026-09-12&end=2026-09-12"' in page.text
    assert "123,45" in page.text
    assert 'href="/?month=2026-08"' in page.text
    day_view = client.get("/expenses?start=2026-09-12&end=2026-09-12")
    assert "123,45" in day_view.text
    assert client.get("/?month=garbage").status_code == 200


def test_overview_shows_eur_from_the_latest_bnr_rate(client: TestClient) -> None:
    with _db(client) as db:
        expenses_core.create_expense(
            db,
            occurred_on=date(2026, 9, 29),
            amount_minor=52786,
            category_id=_groceries_id(client),
        )
        db.commit()
    page = client.get("/")
    assert "100,00 EUR" in page.text
    assert "la 5,2786 RON, BNR lun 28 sep" in page.text
    assert (client.app.state.config.fx_dir / "nbrfxrates2026.xml").exists()


def test_overview_without_rates_says_so(client: TestClient) -> None:
    def broken(year: int) -> bytes:
        raise OSError("offline")

    client.app.state.fx_fetch = broken
    page = client.get("/")
    assert page.status_code == 200
    assert "încă fără curs BNR" in page.text


def test_rating_refreshes_the_tab_badge(client: TestClient) -> None:
    category_id = _groceries_id(client)
    with _db(client) as db:
        first = expenses_core.create_expense(
            db, occurred_on=date(2026, 9, 29), amount_minor=1000, category_id=category_id
        )
        expenses_core.create_expense(
            db, occurred_on=date(2026, 9, 29), amount_minor=2000, category_id=category_id
        )
        db.commit()
        first_id = first.id
    import re

    page = client.get("/review")
    assert re.search(r'id="review-badge"\s*>\s*<span class="badge">2</span>', page.text)
    card = client.post(
        f"/review/{first_id}/rate",
        data={"level": "2", "index": "0"},
        headers={"HX-Request": "true"},
    )
    assert re.search(
        r'id="review-badge" hx-swap-oob="true"\s*>\s*<span class="badge">1<', card.text
    )
    block = client.post(
        f"/expenses/{first_id + 1}/edit",
        data={
            "occurred_on": "2026-09-29",
            "amount": "20",
            "category_id": str(category_id),
            "necessity": "1",
        },
        headers={"HX-Request": "true"},
    )
    assert re.search(r'id="review-badge" hx-swap-oob="true"\s*>\s*</span>', block.text)


def test_deleted_row_vanishes_after_a_delay_unless_restored(client: TestClient) -> None:
    with _db(client) as db:
        expense = expenses_core.create_expense(
            db, occurred_on=date(2026, 9, 29), amount_minor=2300, category_id=_groceries_id(client)
        )
        db.commit()
        expense_id = expense.id
    deleted = client.post(f"/expenses/{expense_id}/delete")
    assert 'hx-trigger="load delay:10s"' in deleted.text
    assert f'hx-get="/expenses/{expense_id}/gone"' in deleted.text
    gone = client.get(f"/expenses/{expense_id}/gone")
    assert gone.status_code == 200 and gone.text == ""
    client.post(f"/expenses/{expense_id}/restore")
    back = client.get(f"/expenses/{expense_id}/gone")
    assert f'id="exp-{expense_id}"' in back.text and "Șters #" not in back.text
