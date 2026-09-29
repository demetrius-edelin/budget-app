"""The bot service: poll Telegram, parse each message, save through the core, reply.

The model call runs with no database transaction open, so the web app can write
in the meantime. Every update becomes one inbound_message row that also stores
the reply. A reply that could not be sent is sent again on the next attempt.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from spendtrack.bot.telegram_api import TelegramError
from spendtrack.config import Config
from spendtrack.core import categories as categories_core
from spendtrack.core import expenses as expenses_core
from spendtrack.core import metrics as metrics_core
from spendtrack.core import reports
from spendtrack.core import settings as settings_core
from spendtrack.core.ai_parse import Draft, ParsedEntry, ParseError, Parser, draft_from_entry
from spendtrack.core.errors import SpendtrackError
from spendtrack.core.expenses import UNSPECIFIED_NAME, necessity_name
from spendtrack.core.money import format_minor
from spendtrack.core.periods import short_date
from spendtrack.db.models import Expense, InboundMessage, utcnow
from spendtrack.db.session import session_scope

log = logging.getLogger(__name__)

HELP_TEXT = """Trimite o cheltuială pe mesaj, cu cuvintele tale:
  cafea 18,50
  alimente 210, din care vin 50
  taxi ieri 35, puteam lua autobuzul
  am condus 42 km până la Cluj
  chirie 2500 esențial, lunar

Comenzi: /today /week /month /last [n] /undo /restore <id> /help"""

MAX_ATTEMPTS = 3
RETRY_DELAY = 3.0
MAX_MESSAGE_LENGTH = 4096


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a reply into parts that fit the Telegram limit, on line ends when possible."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


@dataclass(frozen=True)
class Incoming:
    update_id: int
    chat_id: int
    message_id: int
    sender_id: int
    sent_at: datetime
    text: str | None
    edited: bool


@dataclass(frozen=True)
class Prepared:
    """What the model or the message itself decided, before the write transaction."""

    status: str  # question, command, rejected, error, or entry
    reply: str | None = None
    entry: ParsedEntry | None = None
    error: str | None = None


def parse_update(raw: dict[str, Any]) -> Incoming | None:
    """Read the fields the bot needs from a Telegram update. Return None for other kinds."""
    message = raw.get("message")
    edited = False
    if message is None:
        message = raw.get("edited_message")
        edited = message is not None
    if not isinstance(message, dict):
        return None
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    try:
        return Incoming(
            update_id=int(raw["update_id"]),
            chat_id=int(chat["id"]),
            message_id=int(message["message_id"]),
            sender_id=int(sender.get("id", 0)),
            sent_at=datetime.fromtimestamp(int(message.get("date", 0)), tz=UTC),
            text=message.get("text"),
            edited=edited,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


class BotService:
    """Process Telegram updates. The poller is one thread, so the steps need no locks."""

    def __init__(
        self,
        config: Config,
        session_factory: sessionmaker[Session],
        api: Any,
        parser: Parser,
        *,
        poll_timeout: int = 50,
        now: Callable[[], datetime] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.api = api
        self.parser = parser
        self.poll_timeout = poll_timeout
        self.max_attempts = max_attempts
        self.offset: int | None = None
        self.retry_delay: float | None = None
        self._now = now or (lambda: datetime.now(config.tz))
        self._attempts: dict[int, int] = {}

    # ---- polling ----

    def poll_once(self) -> int:
        """Fetch pending updates once and process them in order. Return the number done.

        An update whose processing raises is not acknowledged. The next poll
        delivers it again, up to max_attempts times. Then the bot gives it up.
        """
        updates = self.api.get_updates(self.offset, self.poll_timeout)
        done = 0
        self.retry_delay = None
        for raw in updates:
            update_id = raw.get("update_id")
            try:
                self.process_update(raw)
            except TelegramError as exc:
                if exc.retry_after:
                    # A rate limit is not a failure of the update. Wait, then try again.
                    log.warning("Telegram asks to wait %s s.", exc.retry_after)
                    self.retry_delay = exc.retry_after
                    return done
                if self._count_failure(update_id):
                    return done
            except Exception:  # noqa: BLE001
                if self._count_failure(update_id):
                    return done
            self._attempts.pop(update_id, None)
            done += 1
            if isinstance(update_id, int):
                self.offset = update_id + 1
        return done

    def _count_failure(self, update_id: Any) -> bool:
        """Record a failed attempt. Return True when the update must be retried later."""
        attempts = self._attempts.get(update_id, 0) + 1
        self._attempts[update_id] = attempts
        if attempts < self.max_attempts:
            log.warning(
                "Update %s failed (attempt %s of %s). It is retried.",
                update_id,
                attempts,
                self.max_attempts,
                exc_info=True,
            )
            self.retry_delay = RETRY_DELAY
            return True
        log.exception("Update %s failed %s times. It is skipped.", update_id, attempts)
        return False

    def run_forever(self, stop: threading.Event) -> None:
        log.info("Telegram bot started (provider %s)", self.config.ai_provider)
        while not stop.is_set():
            try:
                self.poll_once()
            except TelegramError as exc:
                log.warning("Telegram polling failed: %s", exc)
                stop.wait(max(5.0, exc.retry_after or 0.0))
                continue
            except Exception as exc:  # noqa: BLE001
                log.warning("Telegram polling failed: %s", exc)
                stop.wait(5)
                continue
            if self.retry_delay:
                stop.wait(self.retry_delay)

    def start_thread(self, stop: threading.Event) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, args=(stop,), daemon=True)
        thread.start()
        return thread

    # ---- one update ----

    def process_update(self, raw: dict[str, Any]) -> str | None:
        """Handle one update in four steps: look up, prepare, store, deliver.

        Return the reply text, or None when nothing was sent.
        """
        incoming = parse_update(raw)
        if incoming is None:
            return None

        # Step 1: a short transaction to look the update up and read what the parse needs.
        allowed = incoming.sender_id in self.config.allowed_telegram_user_ids
        with session_scope(self.session_factory) as db:
            existing = self._find(db, incoming)
            pending: tuple[int, str] | None = None
            if existing is not None and existing.reply and existing.replied_at is None:
                pending = (existing.id, existing.reply)
            names = [c.name for c in categories_core.list_categories(db)] if allowed else []
        if existing is not None:
            # A stored reply is sent only to a sender who is still allowed.
            if pending is None or not allowed:
                return None
            self._deliver(incoming, *pending)
            return pending[1]

        if not allowed:
            with session_scope(self.session_factory) as db:
                db.add(self._row(incoming, status="unauthorized"))
            log.warning(
                "Ignored a Telegram message from user %s. Add the id to "
                "ALLOWED_TELEGRAM_USER_IDS to permit it.",
                incoming.sender_id,
            )
            return None

        # Step 2: the model call, with no transaction open.
        prepared = self._prepare(incoming, names)

        # Step 3: one write transaction for the row and the entry.
        with session_scope(self.session_factory) as db:
            # The store step sets the final status of an entry: saved, rejected or error.
            initial = "error" if prepared.status == "entry" else prepared.status
            row = self._row(incoming, status=initial)
            db.add(row)
            reply = self._store(db, incoming, row, prepared)
            row.reply = reply
            db.flush()
            row_id = row.id

        # Step 4: the reply. A failure here raises, and the next attempt sends the stored reply.
        self._deliver(incoming, row_id, reply)
        return reply

    def _row(self, incoming: Incoming, *, status: str) -> InboundMessage:
        return InboundMessage(
            tg_update_id=incoming.update_id,
            tg_chat_id=incoming.chat_id,
            tg_message_id=incoming.message_id,
            sender_id=incoming.sender_id,
            sent_at=incoming.sent_at,
            text=incoming.text,
            status=status,
        )

    def _find(self, db: Session, incoming: Incoming) -> InboundMessage | None:
        """Return the stored row of this update. An edit is a new update of the same message."""
        condition = InboundMessage.tg_update_id == incoming.update_id
        if not incoming.edited:
            condition = condition | (
                (InboundMessage.tg_chat_id == incoming.chat_id)
                & (InboundMessage.tg_message_id == incoming.message_id)
            )
        return db.scalar(select(InboundMessage).where(condition).order_by(InboundMessage.id))

    def _deliver(self, incoming: Incoming, row_id: int, reply: str) -> None:
        for index, part in enumerate(split_message(reply)):
            reply_to = incoming.message_id if index == 0 else None
            self.api.send_message(incoming.chat_id, part, reply_to_message_id=reply_to)
        with session_scope(self.session_factory) as db:
            row = db.get(InboundMessage, row_id)
            if row is not None:
                row.replied_at = utcnow()

    def _prepare(self, incoming: Incoming, names: list[str]) -> Prepared:
        """Decide what to do with the message. This step runs the model when needed."""
        text = (incoming.text or "").strip()
        if incoming.edited:
            return Prepared(
                "rejected",
                "Editările nu se aplică. Trimite intrarea din nou sau modific-o în aplicație.",
            )
        if not text:
            return Prepared("rejected", "Trimite un mesaj text cu o sumă, de exemplu: cafea 18,50")
        if text.startswith("/"):
            return Prepared("command")
        message_date = incoming.sent_at.astimezone(self.config.tz).date()
        try:
            entry = self.parser.parse(text, message_date=message_date, categories=names)
        except ParseError as exc:
            return Prepared("error", f"Nesalvat: {exc}", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("The parser failed")
            return Prepared(
                "error", "Nesalvat (eroare internă). Trimite mesajul din nou.", error=repr(exc)
            )
        if entry.kind == "unclear":
            question = entry.question or "Trimite suma și câteva cuvinte."
            return Prepared("question", question, entry=entry)
        return Prepared("entry", entry=entry)

    def _store(
        self, db: Session, incoming: Incoming, row: InboundMessage, prepared: Prepared
    ) -> str:
        """Run the command or save the entry inside the write transaction. Return the reply."""
        if prepared.entry is not None:
            row.parsed = prepared.entry.model_dump()
        row.error = prepared.error
        if prepared.status == "command":
            return self._command(db, (incoming.text or "").strip())
        if prepared.status != "entry":
            return prepared.reply or ""
        assert prepared.entry is not None
        message_date = incoming.sent_at.astimezone(self.config.tz).date()
        try:
            draft = draft_from_entry(
                prepared.entry, categories_core.list_categories(db), message_date
            )
            with db.begin_nested():
                expense = self._save(db, draft)
        except SpendtrackError as exc:
            row.status = "rejected"
            row.error = str(exc)
            return f"Nesalvat: {exc}"
        except Exception as exc:  # noqa: BLE001
            log.exception("Saving a Telegram message failed")
            row.status = "error"
            row.error = repr(exc)
            return "Nesalvat (eroare internă). Trimite mesajul din nou."
        row.status = "saved"
        row.expense_id = expense.id
        return self._confirmation(db, expense)

    def _save(self, db: Session, draft: Draft) -> Expense:
        if draft.kind == "drive":
            entry = metrics_core.create_metric_entry(
                db,
                metric_key="drive",
                occurred_on=draft.occurred_on,
                quantity=draft.quantity,
                overrides=draft.overrides,
                description=draft.description,
                necessity=draft.necessity,
                cheaper_alt=draft.cheaper_alt,
                cheaper_alt_minor=draft.cheaper_alt_minor,
                cheaper_alt_note=draft.cheaper_alt_note,
                recurring=draft.recurring,
            )
            return entry.expense
        expense = expenses_core.create_expense(
            db,
            occurred_on=draft.occurred_on,
            amount_minor=draft.amount_minor,
            category_id=draft.category_id,
            description=draft.description,
            necessity=draft.necessity,
            cheaper_alt=draft.cheaper_alt,
            cheaper_alt_minor=draft.cheaper_alt_minor,
            cheaper_alt_note=draft.cheaper_alt_note,
            recurring=draft.recurring,
            source="telegram",
        )
        if draft.items:
            expenses_core.add_items(db, expense.id, draft.items)
        return expenses_core.get_expense(db, expense.id)

    # ---- replies ----

    def _money(self, db: Session, minor: int) -> str:
        return format_minor(minor, settings_core.number_format(db))

    def _confirmation(self, db: Session, expense: Expense) -> str:
        parts = [f"Salvat #{expense.id}", expense.category.name]
        if expense.description:
            parts.append(expense.description)
        parts.append(f"{self._money(db, expense.amount_minor)} RON")
        parts.append(short_date(expense.occurred_on))
        lines = [" · ".join(parts)]
        entry = metrics_core.entry_for_expense(db, expense)
        if entry is not None:
            lines.append(f"({metrics_core.calculation_text(entry)})")
        if expense.informational:
            lines.append("Doar informativ: modul de cost al combustibilului este chitanțe.")
        items = expense.live_items
        if items:
            detail = " · ".join(f"{i.description} {self._money(db, i.amount_minor)}" for i in items)
            rest = expenses_core.remainder_minor(expense)
            if rest > 0:
                detail += f" · {UNSPECIFIED_NAME} {self._money(db, rest)}"
            lines.append(detail)
        flags = []
        if expense.necessity is not None:
            flags.append(necessity_name(expense.necessity))
        else:
            flags.append("Neevaluat, evaluează în aplicație")
        if expense.cheaper_alt:
            flag = "alternativă mai ieftină"
            if expense.cheaper_alt_minor is not None:
                flag += f" {self._money(db, expense.cheaper_alt_minor)}"
            flags.append(flag)
        if expense.recurring:
            flags.append("recurent")
        lines.append(" · ".join(flags))
        return "\n".join(lines)

    def _command(self, db: Session, text: str) -> str:
        parts = text.split()
        name = parts[0].lower().split("@")[0]
        args = parts[1:]
        today = self._now().date()
        if name in ("/start", "/help"):
            return HELP_TEXT
        if name in ("/today", "/week", "/month"):
            kind = {"/today": "day", "/week": "week", "/month": "month"}[name]
            return self._period_summary(db, kind, today)
        if name == "/last":
            return self._last(db, args)
        if name == "/undo":
            return self._undo(db)
        if name == "/restore":
            return self._restore(db, args)
        return "Comandă necunoscută. Trimite /help pentru listă."

    def _period_summary(self, db: Session, kind: str, today: date) -> str:
        report = reports.period_report(db, kind, today, today)
        label = {"day": "Azi", "week": "Săptămâna aceasta", "month": "Luna aceasta"}[kind]
        change = "fără comparație" if report.change_pct is None else f"{report.change_pct:+.1f}%"
        share = (
            f" ({report.discretionary_share_pct}%)"
            if report.discretionary_share_pct is not None
            else ""
        )
        lines = [
            f"{label}: {self._money(db, report.total_minor)} RON"
            f" ({change} față de aceeași perioadă anterioară)",
            f"Discreționar: {self._money(db, report.discretionary_minor)}{share}",
            f"Economie posibilă: {self._money(db, report.potential_saving_minor)}"
            f" pe {report.flagged_count} linii marcate",
            f"Recurent: {self._money(db, report.recurring_minor)}",
        ]
        unrated = expenses_core.unrated_count(db)
        if unrated:
            lines.append(f"Neevaluate: {unrated}, evaluează-le în aplicație")
        return "\n".join(lines)

    def _last(self, db: Session, args: list[str]) -> str:
        count = 5
        if args:
            try:
                count = max(1, min(20, int(args[0])))
            except ValueError:
                pass
        rows = expenses_core.list_expenses(db, limit=count)
        if not rows:
            return "Nicio cheltuială încă."
        return "\n".join(
            f"#{e.id} {short_date(e.occurred_on)} · {e.category.name} · {e.description or ''} ·"
            f" {self._money(db, e.amount_minor)}"
            for e in rows
        )

    def _last_saved_expense(self, db: Session) -> Expense | None:
        query = (
            select(Expense)
            .join(InboundMessage, InboundMessage.expense_id == Expense.id)
            .where(Expense.deleted_at.is_(None))
            .order_by(InboundMessage.id.desc())
            .limit(1)
        )
        return db.scalar(query)

    def _undo(self, db: Session) -> str:
        expense = self._last_saved_expense(db)
        if expense is None:
            return "Nimic de anulat."
        expenses_core.delete_expense(db, expense.id)
        return (
            f"Șters #{expense.id} · {expense.category.name} ·"
            f" {self._money(db, expense.amount_minor)} RON."
            f" Trimite /restore {expense.id} ca să îl aduci înapoi."
        )

    def _restore(self, db: Session, args: list[str]) -> str:
        if not args or not args[0].lstrip("#").isdigit():
            return "Trimite /restore urmat de număr, de exemplu /restore 57"
        expense_id = int(args[0].lstrip("#"))
        try:
            expense = expenses_core.restore_expense(db, expense_id)
        except SpendtrackError as exc:
            return str(exc)
        amount = self._money(db, expense.amount_minor)
        return f"Restaurat #{expense.id} · {expense.category.name} · {amount} RON"
