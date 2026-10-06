"""The Telegram bot service with a fake Telegram API and a fake parser. No network."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from spendtrack.bot.service import Attachment, BotService, parse_update, split_message
from spendtrack.bot.telegram_api import TelegramError
from spendtrack.config import Config
from spendtrack.core import expenses as expenses_core
from spendtrack.core import metrics
from spendtrack.core.ai_parse import ImageInput, ParsedEntry, ParsedItem, ParseError
from spendtrack.db.models import Base, InboundMessage
from spendtrack.db.seed import seed
from spendtrack.db.session import make_engine, make_session_factory
from tests.conftest import PARAMS_FROM

OWNER = 111
SENT_AT = int(datetime(2026, 9, 29, 10, 0, tzinfo=UTC).timestamp())


NOW = datetime(2026, 9, 29, 12, 0, tzinfo=ZoneInfo("Europe/Bucharest"))


class FakeApi:
    def __init__(self) -> None:
        self.pending: list[dict[str, Any]] = []
        self.sent: list[tuple[int, str, int | None]] = []
        self.fail_sends = 0  # the next n sends raise
        self.rate_limit_once = False
        self.files: dict[str, bytes | Exception] = {}
        self.downloads: list[str] = []

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        updates = [u for u in self.pending if offset is None or u["update_id"] >= offset]
        return updates

    def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
        if self.fail_sends > 0:
            self.fail_sends -= 1
            raise TelegramError("sendMessage failed: network down")
        if self.rate_limit_once:
            self.rate_limit_once = False
            raise TelegramError("sendMessage failed with HTTP 429", retry_after=30, status=429)
        if len(text) > 4096:
            raise TelegramError("sendMessage failed with HTTP 400: message is too long", status=400)
        self.sent.append((chat_id, text, reply_to_message_id))

    def download_file(self, file_id: str) -> bytes:
        self.downloads.append(file_id)
        data = self.files[file_id]
        if isinstance(data, Exception):
            raise data
        return data


class FakeParser:
    def __init__(self) -> None:
        self.answers: dict[str, ParsedEntry | Exception] = {}
        self.calls: list[tuple[str, date, list[str]]] = []
        self.images: list[ImageInput | None] = []

    def parse(
        self,
        text: str,
        *,
        message_date: date,
        categories: list[str],
        image: ImageInput | None = None,
    ) -> ParsedEntry:
        self.calls.append((text, message_date, categories))
        self.images.append(image)
        answer = self.answers[text]
        if isinstance(answer, Exception):
            raise answer
        return answer


def update(text: str, update_id: int = 1, sender: int = OWNER, edited: bool = False) -> dict:
    key = "edited_message" if edited else "message"
    return {
        "update_id": update_id,
        key: {
            "message_id": 100 + update_id,
            "from": {"id": sender},
            "chat": {"id": sender},
            "date": SENT_AT,
            "text": text,
        },
    }


def photo_update(caption: str | None = None, update_id: int = 1, **message: Any) -> dict:
    """A photo message. Telegram lists the sizes from small to large."""
    raw = update("", update_id)
    del raw["message"]["text"]
    if caption is not None:
        raw["message"]["caption"] = caption
    raw["message"].update(
        message
        or {
            "photo": [
                {"file_id": "small", "file_size": 2_000},
                {"file_id": "large", "file_size": 300_000},
            ]
        }
    )
    return raw


def _make_bot(db_url: str, tmp_path: Path) -> tuple[BotService, FakeApi, FakeParser, Any]:
    engine = make_engine(db_url)
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
        telegram_bot_token="token",
        allowed_telegram_user_ids=frozenset({OWNER}),
    )
    api, parser = FakeApi(), FakeParser()
    service = BotService(config, factory, api, parser, poll_timeout=0, now=lambda: NOW)
    service.factory = factory  # type: ignore[attr-defined]
    return service, api, parser, engine


@pytest.fixture
def bot(tmp_path: Path) -> Iterator[tuple[BotService, FakeApi, FakeParser]]:
    service, api, parser, engine = _make_bot("sqlite://", tmp_path)
    yield service, api, parser
    engine.dispose()


def _db(service: BotService) -> Session:
    return service.factory()  # type: ignore[attr-defined]


def test_parse_update_reads_message_and_edited_message() -> None:
    incoming = parse_update(update("hi", update_id=7))
    assert incoming is not None
    assert (incoming.update_id, incoming.message_id, incoming.sender_id) == (7, 107, OWNER)
    assert incoming.sent_at == datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    assert parse_update(update("hi", edited=True)).edited is True
    assert parse_update({"update_id": 1, "callback_query": {}}) is None


def test_expense_with_items_is_saved_and_confirmed(bot) -> None:
    service, api, parser = bot
    parser.answers["groceries 210, of which wine 50"] = ParsedEntry(
        kind="expense",
        amount="210",
        category="Alimente",
        description="Alimente",
        items=[ParsedItem(description="Wine", amount="50", necessity=3)],
    )
    reply = service.process_update(update("groceries 210, of which wine 50"))
    assert reply is not None
    assert reply.startswith("Salvat #1 · Alimente · Alimente · 210,00 RON · mar 29 sep")
    assert "Wine 50,00 · Nespecificat 160,00" in reply
    assert "Neevaluat" in reply
    assert api.sent == [(OWNER, reply, 101)]
    assert parser.calls[0][1] == date(2026, 9, 29)
    assert "Alimente" in parser.calls[0][2]
    with _db(service) as db:
        expense = expenses_core.get_expense(db, 1)
        assert expense.source == "telegram"
        assert expense.amount_minor == 21000
        assert [i.description for i in expense.live_items] == ["Wine"]
        row = db.scalar(select(InboundMessage))
        assert (row.status, row.expense_id, row.parsed["amount"]) == ("saved", 1, "210")
        assert row.reply == reply and row.replied_at is not None


def test_drive_is_saved_with_its_calculation(bot) -> None:
    service, api, parser = bot
    parser.answers["drove 42 km to Cluj"] = ParsedEntry(
        kind="drive", quantity_km="42", description="Cluj"
    )
    reply = service.process_update(update("drove 42 km to Cluj"))
    assert "Salvat #1 · Combustibil și mașină · Condus 42 km · Cluj · 25,04 RON" in reply
    assert "(42 km × 7.2 L/100 km × 8.28 RON/L)" in reply


def test_message_date_wins_over_processing_time(bot) -> None:
    service, api, parser = bot
    late = update("taxi 35")
    late["message"]["date"] = int(
        datetime(2026, 9, 28, 20, 50, tzinfo=UTC).timestamp()
    )  # 23:50 local
    parser.answers["taxi 35"] = ParsedEntry(kind="expense", amount="35", category="Transport")
    service.process_update(late)
    assert parser.calls[0][1] == date(2026, 9, 28)
    with _db(service) as db:
        assert expenses_core.get_expense(db, 1).occurred_on == date(2026, 9, 28)


def test_duplicate_update_is_ignored(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense", amount="18.5", category="Mâncare în oraș"
    )
    service.process_update(update("coffee 18,50"))
    assert service.process_update(update("coffee 18,50")) is None
    with _db(service) as db:
        assert len(expenses_core.list_expenses(db)) == 1
    assert len(api.sent) == 1


def test_unknown_sender_gets_no_reply(bot) -> None:
    service, api, parser = bot
    assert service.process_update(update("coffee 18,50", sender=999)) is None
    assert api.sent == []
    assert parser.calls == []
    with _db(service) as db:
        row = db.scalar(select(InboundMessage))
        assert (row.status, row.sender_id) == ("unauthorized", 999)


def test_unclear_message_asks_a_question(bot) -> None:
    service, api, parser = bot
    parser.answers["alimente"] = ParsedEntry(
        kind="unclear", question="How much were the groceries?"
    )
    reply = service.process_update(update("alimente"))
    assert reply == "How much were the groceries?"
    with _db(service) as db:
        assert expenses_core.list_expenses(db) == []
        assert db.scalar(select(InboundMessage)).status == "question"


def test_parser_failure_is_reported_and_nothing_is_saved(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParseError(
        "The parser is not reachable. Send the message again later."
    )
    reply = service.process_update(update("coffee 18,50"))
    assert reply == "Nesalvat: The parser is not reachable. Send the message again later."
    with _db(service) as db:
        row = db.scalar(select(InboundMessage))
        assert (row.status, row.error) == (
            "error",
            "The parser is not reachable. Send the message again later.",
        )


def test_core_rule_violation_is_reported(bot) -> None:
    service, api, parser = bot
    parser.answers["groceries 100 wine 150"] = ParsedEntry(
        kind="expense",
        amount="100",
        category="Alimente",
        items=[ParsedItem(description="Wine", amount="150")],
    )
    reply = service.process_update(update("groceries 100 wine 150"))
    assert reply.startswith("Nesalvat: Articolele 150.00 depășesc suma cheltuielii 100.00")
    with _db(service) as db:
        assert expenses_core.list_expenses(db) == []


def test_edited_messages_are_not_applied(bot) -> None:
    service, api, parser = bot
    reply = service.process_update(update("coffee 20", edited=True))
    assert reply.startswith("Editările nu se aplică")
    assert parser.calls == []


def test_commands(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense",
        amount="18.5",
        category="Mâncare în oraș",
        description="Coffee",
        necessity=4,
        cheaper_alt_amount="8",
    )
    service.process_update(update("coffee 18,50", update_id=1))
    assert service.process_update(update("/help", update_id=2)).startswith("Trimite o cheltuială")
    today = service.process_update(update("/today", update_id=3))
    assert today.startswith("Azi: 18,50 RON")
    assert "Economie posibilă: 18,50 (Impuls 18,50 + alternative mai ieftine 0,00)" in today
    assert "Economie radicală: 18,50 (Important + Util + Impuls)" in today
    assert "#1 mar 29 sep · Mâncare în oraș · Coffee · 18,50" in service.process_update(
        update("/last 3", update_id=4)
    )
    undo = service.process_update(update("/undo", update_id=5))
    assert undo.startswith("Șters #1")
    with _db(service) as db:
        assert expenses_core.list_expenses(db) == []
    assert service.process_update(update("/undo", update_id=6)) == "Nimic de anulat."
    assert service.process_update(update("/restore 1", update_id=7)).startswith("Restaurat #1")
    assert service.process_update(update("/bogus", update_id=8)).startswith("Comandă necunoscută")


def test_poll_once_advances_the_offset_and_survives_a_bad_update(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense", amount="18.5", category="Mâncare în oraș"
    )
    api.pending = [update("coffee 18,50", update_id=10), {"update_id": 11, "message": "broken"}]
    assert service.poll_once() == 2
    assert service.offset == 12
    assert len(api.sent) == 1
    assert service.poll_once() == 0


def test_failed_send_is_retried_without_a_duplicate(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense", amount="18.5", category="Mâncare în oraș"
    )
    api.fail_sends = 1
    with pytest.raises(TelegramError):
        service.process_update(update("coffee 18,50"))
    with _db(service) as db:
        assert len(expenses_core.list_expenses(db)) == 1
        row = db.scalar(select(InboundMessage))
        assert (
            row.status == "saved" and row.reply.startswith("Salvat #1") and row.replied_at is None
        )
    reply = service.process_update(update("coffee 18,50"))  # the same update, delivered again
    assert reply.startswith("Salvat #1")
    assert len(api.sent) == 1 and len(parser.calls) == 1
    with _db(service) as db:
        assert len(expenses_core.list_expenses(db)) == 1
        assert db.scalar(select(InboundMessage)).replied_at is not None
    assert service.process_update(update("coffee 18,50")) is None  # nothing left to send


def test_edit_of_a_processed_message_gets_the_rejection_reply(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 10"] = ParsedEntry(
        kind="expense", amount="10", category="Mâncare în oraș"
    )
    service.process_update(update("coffee 10", update_id=1))
    edit = update("coffee 12", update_id=2, edited=True)
    edit["edited_message"]["message_id"] = 101  # the same message as update 1
    reply = service.process_update(edit)
    assert reply.startswith("Editările nu se aplică")
    with _db(service) as db:
        assert expenses_core.get_expense(db, 1).amount_minor == 1000
        assert db.query(InboundMessage).count() == 2
    assert service.process_update(edit) is None  # the same edit again is a duplicate


def test_poll_once_retries_a_failed_update_then_gives_up(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense", amount="18.5", category="Mâncare în oraș"
    )
    parser.answers["tea 5"] = ParsedEntry(kind="expense", amount="5", category="Mâncare în oraș")
    api.pending = [update("coffee 18,50", update_id=10), update("tea 5", update_id=11)]
    api.fail_sends = 2
    assert service.poll_once() == 0
    assert service.offset is None and service.retry_delay == 3.0
    assert service.poll_once() == 0
    assert service.poll_once() == 2  # the third attempt sends the stored reply, then update 11
    assert service.offset == 12 and service.retry_delay is None
    assert [text[:9] for _, text, _ in api.sent] == ["Salvat #1", "Salvat #2"]

    api.pending = [update("coffee 18,50", update_id=12)]
    api.fail_sends = 99
    for _ in range(service.max_attempts):
        service.poll_once()
    assert service.offset == 13  # given up after max_attempts, the offset moves on


def test_commands_use_the_injected_clock(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense", amount="18.5", category="Mâncare în oraș"
    )
    service.process_update(update("coffee 18,50", update_id=1))
    service._now = lambda: NOW.replace(day=30)
    assert service.process_update(update("/today", update_id=2)).startswith("Azi: 0,00 RON")
    assert service.process_update(update("/week", update_id=3)).startswith(
        "Săptămâna aceasta: 18,50 RON"
    )


def test_model_call_holds_no_write_lock(tmp_path: Path) -> None:
    """The web app must be able to write while the bot waits for the model."""
    import sqlite3

    db_path = tmp_path / "bot.db"
    service, api, parser, engine = _make_bot(f"sqlite:///{db_path}", tmp_path)

    class WritingParser(FakeParser):
        def parse(self, text, *, message_date, categories, image=None):
            other = sqlite3.connect(db_path, timeout=0.5)
            try:
                other.execute("INSERT INTO setting (key, value) VALUES ('probe', '1')")
                other.commit()
            finally:
                other.close()
            return ParsedEntry(kind="expense", amount="10", category="Alimente")

    service.parser = WritingParser()
    reply = service.process_update(update("coffee 10"))
    assert reply.startswith("Salvat #1")
    engine.dispose()


def test_rate_limit_waits_and_does_not_count_as_an_attempt(bot) -> None:
    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense", amount="18.5", category="Mâncare în oraș"
    )
    api.pending = [update("coffee 18,50", update_id=1)]
    api.rate_limit_once = True
    assert service.poll_once() == 0
    assert service.retry_delay == 30 and service._attempts == {}
    assert service.poll_once() == 1
    assert service.offset == 2 and len(api.sent) == 1
    with _db(service) as db:
        assert len(expenses_core.list_expenses(db)) == 1


def test_split_message_keeps_lines_and_respects_the_limit() -> None:
    assert split_message("short") == ["short"]
    lines = [f"line {i} " + "x" * 90 for i in range(60)]
    parts = split_message("\n".join(lines), limit=1000)
    assert all(len(part) <= 1000 for part in parts)
    assert "\n".join(parts).split("\n") == lines
    assert split_message("y" * 2500, limit=1000) == ["y" * 1000, "y" * 1000, "y" * 500]


def test_long_replies_are_sent_in_parts(bot) -> None:
    service, api, parser = bot
    with _db(service) as db:
        from spendtrack.core.categories import get_category_by_name

        category_id = get_category_by_name(db, "Alimente").id
        for i in range(20):
            expenses_core.create_expense(
                db,
                occurred_on=date(2026, 9, 29),
                amount_minor=1000 + i,
                category_id=category_id,
                description="d" * 250,
            )
        db.commit()
    reply = service.process_update(update("/last 20"))
    assert len(reply) > 4096
    assert len(api.sent) >= 2
    assert all(len(text) <= 4096 for _, text, _ in api.sent)
    assert api.sent[0][2] == 101 and api.sent[1][2] is None
    assert "\n".join(text for _, text, _ in api.sent) == reply


def test_pending_reply_is_not_sent_to_a_removed_sender(bot) -> None:
    from dataclasses import replace

    service, api, parser = bot
    parser.answers["coffee 18,50"] = ParsedEntry(
        kind="expense", amount="18.5", category="Mâncare în oraș"
    )
    api.fail_sends = 1
    with pytest.raises(TelegramError):
        service.process_update(update("coffee 18,50"))
    service.config = replace(service.config, allowed_telegram_user_ids=frozenset())
    assert service.process_update(update("coffee 18,50")) is None
    assert api.sent == []


# ---- receipt photos ----

LIDL = ParsedEntry(
    kind="expense",
    occurred_on="2026-09-28",
    amount="28.43",
    category="Alimente",
    description="Lidl",
    items=[
        ParsedItem(description="Branza de vaci cu sm", amount="21.99"),
        ParsedItem(description="Sacosa maiou", amount="0.81"),
        ParsedItem(description="Ecotaxa/Cost DEEE", amount="0.18"),
        ParsedItem(description="Varza alba", amount="5.45"),
    ],
)


def test_parse_update_reads_a_photo_and_its_caption() -> None:
    incoming = parse_update(photo_update("ieri"))
    assert incoming is not None and incoming.text == "ieri"
    assert incoming.attachment == Attachment("large", "image/jpeg", 300_000)
    huge = photo_update(
        photo=[{"file_id": "fits", "file_size": 900_000}, {"file_id": "huge", "file_size": 9**8}]
    )
    assert parse_update(huge).attachment.file_id == "fits"
    heic = photo_update(document={"file_id": "d", "mime_type": "image/heic", "file_size": 10})
    assert parse_update(heic).attachment == Attachment("d", None, 10)
    pdf = photo_update(document={"file_id": "p", "mime_type": "application/pdf"})
    assert parse_update(pdf).attachment is None
    assert parse_update(update("cafea 18")).attachment is None


def test_receipt_photo_is_saved_with_one_item_per_article(bot) -> None:
    service, api, parser = bot
    api.files["large"] = b"jpeg bytes"
    parser.answers[""] = LIDL
    reply = service.process_update(photo_update())
    assert api.downloads == ["large"]
    assert parser.images == [ImageInput(b"jpeg bytes", "image/jpeg")]
    assert reply.startswith("Salvat #1 · Alimente · Lidl · 28,43 RON · lun 28 sep")
    assert "\nBranza de vaci cu sm 21,99\nSacosa maiou 0,81\nEcotaxa/Cost DEEE 0,18\n" in reply
    assert "Varza alba 5,45\nNeevaluat" in reply
    with _db(service) as db:
        expense = expenses_core.get_expense(db, 1)
        assert expense.amount_minor == 2843
        assert len(expense.live_items) == 4
        assert expenses_core.remainder_minor(expense) == 0
        row = db.scalar(select(InboundMessage))
        assert (row.status, row.text) == ("saved", None)


def test_photo_caption_goes_to_the_parser(bot) -> None:
    service, api, parser = bot
    api.files["large"] = b"jpeg bytes"
    parser.answers["esențial"] = LIDL.model_copy(update={"necessity": 1})
    reply = service.process_update(photo_update("esențial"))
    assert parser.calls[0][0] == "esențial"
    assert "Esențial" in reply


def test_receipt_items_above_the_total_save_the_total_only(bot) -> None:
    service, api, parser = bot
    api.files["large"] = b"jpeg bytes"
    parser.answers[""] = LIDL.model_copy(update={"amount": "25"})
    reply = service.process_update(photo_update())
    assert reply.startswith("Salvat #1 · Alimente · Lidl · 25,00 RON")
    assert reply.endswith(
        "nu se potrivesc cu totalul, așa că am salvat doar totalul. Adaugă articolele în aplicație."
    )
    with _db(service) as db:
        assert expenses_core.get_expense(db, 1).live_items == []


def test_unusable_images_are_rejected_before_the_model(bot) -> None:
    service, api, parser = bot
    heic = photo_update(document={"file_id": "d", "mime_type": "image/heic", "file_size": 10})
    assert service.process_update(heic).startswith("Nesalvat: nu pot citi acest tip de imagine")
    big = photo_update(
        update_id=2, document={"file_id": "b", "mime_type": "image/png", "file_size": 9**8}
    )
    assert service.process_update(big).startswith("Nesalvat: imaginea este prea mare")
    api.files["large"] = b"x" * 4_000_000  # the photo grew past the limit after the check
    assert service.process_update(photo_update(update_id=3)).startswith(
        "Nesalvat: imaginea este prea mare"
    )
    assert parser.calls == [] and api.downloads == ["large"]
    sticker = photo_update(update_id=4, sticker={"file_id": "s"})
    assert service.process_update(sticker).startswith("Trimite un mesaj text cu o sumă")


def test_download_failures(bot) -> None:
    service, api, parser = bot
    api.files["large"] = TelegramError("getFile failed with HTTP 400: file is too big", status=400)
    reply = service.process_update(photo_update())
    assert reply == "Nesalvat: nu pot descărca fotografia. Trimite-o din nou."
    with _db(service) as db:
        assert db.scalar(select(InboundMessage)).status == "error"
    # A temporary failure raises, so the next poll delivers the update again.
    api.files["large"] = TelegramError("File download failed: timed out")
    with pytest.raises(TelegramError):
        service.process_update(photo_update(update_id=2))
    api.files["large"] = b"jpeg bytes"
    parser.answers[""] = LIDL
    assert service.process_update(photo_update(update_id=2)).startswith("Salvat #1")
