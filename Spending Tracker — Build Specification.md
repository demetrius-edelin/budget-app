# Spending Tracker — Build Specification

Sep 29, 2026 · @Demi

## Overview and goals

Spendtrack is a single-user expense tracker that runs on the owner's laptop, takes input from the phone through a Telegram bot, and exists to help cut spending after a drop in income. All data lives in one SQLite file on the laptop; the currency is RON.

The owner records spending from the phone and reviews it in a local web dashboard. What sets it apart from a generic tracker is that every expense can be rated for necessity and flagged as replaceable, so reports show where money can be cut, not just where it went.

Goals, in priority order:

1. Capture an expense from the phone in under 10 seconds.
2. See totals per day, week and month.
3. Turn measured quantities (km driven) into money automatically.
4. Add detail to an existing expense later, even partially (Groceries 100 RON, of which Wine 50 RON).
5. Rate each expense by necessity and flag cheaper alternatives, so reports show discretionary spending and potential savings.

Success means that after a month of use, one screen answers: how much went to non-essential spending, and what could have been saved?

## Scope

Version 1 covers entry by Telegram, review in a local dashboard, and the rating and reporting that support cutting spending. It assumes one user, one currency, one vehicle, and a laptop that stays on.

In version 1:

- Telegram bot for entering expenses, adding detail, rating, quick reports, and weekly and monthly digests.
- Local web dashboard, bound to 127.0.0.1, for review, editing, reports and settings.
- Expenses with partial itemization and an automatic "Unspecified" remainder.
- Metric entries (driving) converted to money, using parameters that keep a dated history.
- Necessity rating on four levels, a cheaper-alternative flag with an optional alternative price, and a recurring flag.
- CSV export and automatic daily backups.

Not in version 1:

- Income, accounts, balances, and per-category budgets (one optional monthly target only).
- Multiple currencies, users or vehicles. The currency field exists but only RON is used.
- Bank imports, receipt photos, and email input.
- Recovering Telegram messages older than 24 hours. The laptop is assumed to stay on (see Build order and later work).
- Hosting anywhere other than the laptop, and a native mobile app.

## Architecture and tech stack

One Python process on the laptop runs the Telegram bot, the web dashboard and a scheduler; all three share one core library and one SQLite file.

&#91;embedded content: architecture · one process, one core, one database file\]

The bot pulls messages from Telegram, so the laptop needs no public address, open port or server. The bot and the dashboard never touch the database directly; both call the core, so an expense entered either way follows the same rules.

| Layer | Choice | Reason |
| --- | --- | --- |
| Language | Python 3.12 | Simple to run locally; strong Telegram and web libraries |
| Database | SQLite in WAL mode, via SQLAlchemy 2 with Alembic migrations | One file, easy to back up, safe schema changes |
| Telegram | python-telegram-bot 21 or later, long polling | No webhook or public IP needed |
| Web | FastAPI, Jinja2 templates, HTMX for inline edits, Chart.js bundled locally | Server-rendered, no build step, works offline |
| Scheduler | The bot library's job queue, or APScheduler | Digests and backups inside the same process |
| Money | `decimal.Decimal`, stored as integer bani | No floating-point rounding errors |
| Quality | pytest and ruff | Tests for every rule in this spec |

Suggested layout:

```
spendtrack/
  __main__.py      starts bot, web server and scheduler in one asyncio loop
  config.py        .env loading and validation
  db/              models, migrations, seed data
  core/
    parser.py      message text to parsed entry or error, no I/O
    expenses.py    create, edit, items, delete, restore
    metrics.py     calculators and dated parameter lookup
    reports.py     totals, breakdown lines, digest content
  bot/             handlers, keyboards, reply routing
  web/             routes, templates, static files
  scheduler.py     digests, missed-digest catch-up, backups
tests/
```

## Data model

The expense total is always authoritative; items only explain part of it, and whatever they don't cover is an "Unspecified" remainder.

Conventions:

- Money is stored as integer minor units (bani): 18.50 RON = 1850. Arithmetic uses `Decimal`, rounded half-up to 2 decimals only when a value is stored.
- Dates are local calendar dates in Europe/Bucharest; timestamps are stored as UTC ISO-8601.
- Deletes are soft (`deleted_at`), and every report excludes deleted rows.
- Weeks start on Monday.

### expense

| Field | Type | Notes |
| --- | --- | --- |
| id | integer PK | Shown to the user as #id |
| occurred\_on | date | From an `@date` token, else the Telegram message's own date |
| amount\_minor | integer > 0 | Authoritative total |
| currency | text | Default RON |
| category\_id | FK category | "Uncategorized" when nothing matches |
| description | text | Message words minus the parsed tokens |
| necessity | integer 1–4, nullable | Null means unrated |
| cheaper\_alt | boolean | Default false |
| cheaper\_alt\_minor | integer, nullable | What the cheaper option would cost |
| cheaper\_alt\_note | text, nullable | For example "store brand" |
| recurring | boolean | Default taken from the category |
| source | text | telegram, web or metric |
| tg\_chat\_id, tg\_message\_id | integer, nullable | The original message; unique as a pair |
| tg\_reply\_message\_id | integer, nullable | The bot's confirmation, used for reply-to-add-detail |
| raw\_text | text, nullable | The message as sent |
| created\_at, updated\_at, deleted\_at | timestamp |  |

### expense\_item

| Field | Type | Notes |
| --- | --- | --- |
| id | integer PK |  |
| expense\_id | FK expense |  |
| description | text |  |
| amount\_minor | integer > 0 | Sum of an expense's items must not exceed its amount |
| category\_id | FK category, nullable | Null inherits the expense's category |
| necessity | integer 1–4, nullable | Null inherits the expense's rating |
| cheaper\_alt, cheaper\_alt\_minor, cheaper\_alt\_note | as on expense |  |
| created\_at, updated\_at, deleted\_at | timestamp |  |

### category

| Field | Type | Notes |
| --- | --- | --- |
| id | integer PK |  |
| name | text, unique |  |
| aliases | JSON list of text | Words matched in descriptions |
| default\_necessity | integer 1–4, nullable | Pre-fills the rating |
| default\_recurring | boolean | Pre-fills the recurring flag |
| archived | boolean | Hidden from pickers, kept in history |

Seed categories (the owner edits aliases in Settings, including Romanian words):

| Category | Starter aliases | Default necessity |
| --- | --- | --- |
| Groceries | groceries, grocery, supermarket, market, food | none |
| Eating out | restaurant, lunch, dinner, coffee, delivery, bar | none |
| Fuel & car | drive, fuel, parking, carwash, service, toll | none |
| Housing | rent, mortgage, maintenance, repairs | Essential |
| Utilities | electricity, heating, water, internet, phone | Essential |
| Health | pharmacy, doctor, medicine, dentist | Essential |
| Transport | taxi, bus, metro, train, bolt, uber | none |
| Subscriptions | subscription, netflix, spotify, gym (recurring by default) | none |
| Shopping | clothes, shoes, electronics, home | none |
| Entertainment | cinema, games, books, hobby, concert | none |
| Personal care | haircut, cosmetics | none |
| Gifts & other | gift, other | none |
| Uncategorized | none | none |

### metric\_type

| Field | Type | Notes |
| --- | --- | --- |
| id | integer PK |  |
| key | text, unique | For example `drive` |
| name | text | "Driving" |
| unit | text | km |
| aliases | JSON list of text | drive, drove, car |
| category\_id | FK category | Category for the generated expense (Fuel & car) |
| calculator | text | Name of a registered Python function, for example `fuel_cost` |

### metric\_param

| Field | Type | Notes |
| --- | --- | --- |
| id | integer PK |  |
| metric\_type\_id | FK metric\_type |  |
| name | text | `consumption_l_per_100km` or `fuel_price_per_l` |
| value | decimal stored as text |  |
| effective\_from | date | The value in force is the latest row with effective\_from ≤ the entry's date |

### metric\_entry

| Field | Type | Notes |
| --- | --- | --- |
| id | integer PK |  |
| metric\_type\_id | FK metric\_type |  |
| expense\_id | FK expense, unique | The generated expense, one to one |
| quantity | decimal | For example 42 (km) |
| params\_used | JSON | Snapshot of every parameter value and whether it was an override |
| created\_at | timestamp |  |

### inbound\_message

An audit log of every Telegram update, also used to prevent duplicates.

| Field | Type | Notes |
| --- | --- | --- |
| id | integer PK |  |
| tg\_update\_id | integer, unique |  |
| tg\_chat\_id, tg\_message\_id, sender\_id | integer |  |
| sent\_at | timestamp | The message date from Telegram |
| text | text |  |
| status | text | saved, detail\_added, command, rejected, unauthorized, error |
| error | text, nullable |  |
| expense\_id | FK expense, nullable |  |

### setting

Key-value pairs: `timezone`, `week_start`, `currency`, `number_format`, `monthly_target_minor`, `weekly_digest_at`, `monthly_digest_at`, `last_weekly_digest`, `last_monthly_digest`, `backup_keep_days`, pump\_fuel\_aliases.

### Totals and breakdown rules

1. A period total is the sum of `expense.amount_minor` over non-deleted expenses whose `occurred_on` falls in the period. Items never add to totals, and neither do drive entries dated while the costing mode is receipts.
2. For breakdowns, each expense becomes its items plus one remainder line (amount minus the sum of its items), labelled "Unspecified". A remainder of zero is dropped.
3. Each line's category, necessity and cheaper-alternative values are the item's own, falling back to the expense's.
4. A line's potential saving is its amount minus `cheaper_alt_minor`, when that price is set and lower than the amount. Lines flagged without a price count toward the flagged amount but add nothing to savings.
5. Adding items whose sum would exceed the expense amount is rejected; the user changes the total first.
6. Lowering an expense amount below the sum of its items is rejected.

Example: Groceries 100 RON rated Essential, with the item Wine 50 RON rated Nice-to-have. The day's total is 100 RON; the breakdown shows Essential 50 (Unspecified) and Nice-to-have 50 (Wine).

## Telegram bot

The bot is the main input channel: one message is one expense, the bot always answers, and every answer offers one-tap rating.

### Connection rules

- Uses python-telegram-bot with long polling, in the owner's private chat with the bot.
- Must not drop pending updates on start (`drop_pending_updates=False`), so messages sent while the laptop slept are processed on wake.
- Answers only the Telegram user IDs listed in `ALLOWED_TELEGRAM_USER_IDS`. Anyone else gets no reply and is logged as unauthorized, with their sender ID, so the owner can find their own ID on first setup.
- `occurred_on` defaults to the message's own date in local time, not the time it was processed.
- Duplicates are prevented by `tg_update_id` and by the (chat, message) pair.
- Edited messages are not re-parsed in version 1. The bot replies that edits are not applied and points to `/amount` or the dashboard.

### Expense message grammar

Tokens may appear in any order. An expense message needs exactly one amount.

| Token | Meaning | Example |
| --- | --- | --- |
| number | The amount. Comma or dot as decimal separator; a separator followed by exactly 3 digits is a thousands separator | `100`, `18,50`, `18.5`, `2.500` = 2500 |
| words | Description; the category is matched from aliases | `groceries`, `coffee at mall` |
| `RON`, `lei` | Optional currency word, ignored | `100 lei` |
| `!1` to `!4`, or `!essential`, `!important`, `!nice`, `!impulse` | Necessity level | `!4` |
| `~` | A cheaper alternative exists | `~` |
| `~number` | A cheaper alternative exists and would cost this | `~8` |
| `!rec` | Recurring | `!rec` |
| `@date` | Date: `@today`, `@yesterday`, `@mon` to `@sun` (most recent past day), `@27.09`, `@27.09.2026`, `@2026-09-27` | `@yesterday` |

Parsing rules:

- Category matching is whole-word, case-insensitive and diacritic-insensitive. When several aliases match, the longest wins; when none match, the category is Uncategorized.
- Necessity comes from an explicit token first, then the category default, else stays unrated.
- Two bare numbers, or none, is a rejection with a hint. Nothing is saved.
- The parser is a pure function (text in, parsed entry or error out) shared with the dashboard's quick-entry box.

### Metric messages

A message is a metric entry when it contains a number with a metric unit (`42km` or `42 km`) or starts with a metric alias followed by a number. Two optional override tokens apply to that entry only: `6.5l` sets consumption in L/100 km, and `7.99/l` sets the fuel price per litre. Date and flag tokens work as for expenses. The calculation is in the Metrics section.

### Confirmation reply

Every saved expense gets a reply to the owner's message:

```
Saved #57 · Groceries · 100.00 RON · Tue 29 Sep
Unrated
[Essential] [Important] [Nice] [Impulse]
[Cheaper exists] [Recurring] [Undo]
```

- Tapping a level stores it and edits the reply in place ("Rated: Nice-to-have"). Tapping again changes it.
- "Cheaper exists" and "Recurring" toggle and show their state in the reply text.
- After "Cheaper exists", the bot sends a separate prompt: "What would the cheaper option cost? Reply with a number, or ignore." A numeric reply to that prompt sets `cheaper_alt_minor`.
- "Undo" soft-deletes the expense and edits the reply to "Deleted #57" with a Restore button.
- A category default rating is shown in the reply ("Rated: Essential, from category") so one tap can change it.

### Adding detail to an expense

- Reply to the bot's confirmation, or to the original message, with one or more items: `wine 50`, or `wine 50, cheese 30`, or one item per line.
- Each item accepts the same `!1`–`!4`, `~` and `~number` tokens. If an item's words match a category alias other than the expense's, the item takes that category.
- The bot answers with the updated breakdown: "#57 Groceries 100.00 RON: Wine 50.00 (Nice-to-have) · Unspecified 50.00". A single added item gets rating buttons; several items are rated later through `/review` or the dashboard.
- Replying to that detail answer adds more items to the same expense.
- Without replying: `/detail 57 wine 50`.
- What a reply means depends only on the message it replies to: a confirmation or detail answer means items, and the cheaper-price prompt means a price.

### Commands

| Command | What it does |
| --- | --- |
| `/help` | Grammar summary with examples |
| `/today`, `/week`, `/month` | Period-to-date total, change against the previous period, split by necessity, potential savings |
| `/last [n]` | Last n expenses with their IDs (default 5) |
| `/review` | Unrated expenses and items one at a time with rating buttons, oldest first |
| `/undo` | Deletes the most recent expense, after a confirm button |
| `/del <id>` | Deletes expense #id, after a confirm button |
| `/amount <id> <value>` | Changes an expense total; rejected if below its items |
| `/detail <id> <items>` | Adds items without replying |
| `/fuel <price>` | Sets the fuel price per litre, effective today |
| `/consumption <value>` | Sets default consumption in L/100 km, effective today |
| `/cats` | Lists categories and their aliases |
| `/alias <category> <word>` | Adds an alias to a category |

### Errors

- An unparseable message saves nothing. The reply says what was understood and gives the closest valid form, for example: "No amount found in 'groceries'. Try: groceries 100".
- Any internal exception is logged, the message's status is set to error, and the reply says "Not saved (internal error), please resend". The owner must never be left guessing whether something was recorded.

## Metrics

A metric entry turns a measured quantity into an ordinary expense: "drive 42km" becomes a Fuel & car expense priced from consumption and fuel price.

```latex
\text{cost (RON)} = \text{km} \times \frac{\text{consumption (L/100 km)}}{100} \times \text{fuel price (RON/L)}
```

Rules:

- Parameter values come from `metric_param`: the latest value whose `effective_from` is on or before the entry's date. Setting a new fuel price today never changes earlier entries.
- Overrides in a message (`6.5l`, `7.99/l`) apply to that entry only. They are recorded in `params_used` with an override flag and never change the defaults.
- If a parameter has no value yet (first run), the bot saves nothing and asks for it: "Set the fuel price first: /fuel 7.99".
- The generated expense takes the metric type's category, the description "Drive 42 km", source `metric`, and the amount rounded half-up to bani. It behaves like any other expense: rating, items, deletion. Deleting it also deletes the metric entry.
- The confirmation shows the calculation: "Saved #58 · Fuel & car · Drive 42 km · 25.04 RON (42 km × 7.2 L/100 km × 8.28 RON/L)".
- New metric types are added by registering a calculator function and seeding a `metric_type` row with its parameters. There is no formula language in version 1.

Fuel costing mode: km-based costing and pump receipts measure the same fuel, so logging both counts it twice. The owner picks one of two modes in Settings. The mode is stored as the dated drive parameter costing\_mode, so switching never changes past periods.

- `km` (default): driving is costed from km as above. A pump purchase can still be logged as a regular expense (`fuel 250`), but when its words match a pump-fuel alias (`fuel` by default; the owner adds others in the `pump_fuel_aliases` setting), the confirmation warns that it may double-count driving.
- `receipts`: pump purchases are regular Fuel & car expenses. Drive entries are still saved with their computed cost, but are excluded from totals and reports and shown for information only.

## Necessity and savings flags

Every expense and item can carry a necessity level, a cheaper-alternative flag and a recurring flag; reports use all three to show where spending can be cut.

| Level | Name | Meaning | Examples |
| --- | --- | --- | --- |
| 1 | Essential | Needed, and not reducible in the short term | Rent, utilities, medicine, basic groceries |
| 2 | Important | Needed, but the amount or frequency could shrink | Commuting, phone plan, work lunches |
| 3 | Nice-to-have | Adds comfort; could be skipped without real harm | Eating out, wine, streaming |
| 4 | Impulse | Unplanned; would not be bought again on reflection | Checkout snacks, sale purchases |

Unrated (null) is its own bucket in every report and feeds the review queue.

The cheaper-alternative flag is independent of the level: an essential purchase can still have a cheaper option (a store brand instead of a name brand). It has an optional alternative price, which drives the potential-savings figure, and an optional note, editable in the dashboard.

The recurring flag marks repeating costs such as subscriptions and memberships. Reports list them separately because they are usually the easiest to cancel.

Rules that keep rating low-effort:

- Rating is never required to save an expense.
- Category defaults pre-fill the level (Housing is Essential), shown in the confirmation so one tap can change it.
- `/review` and the dashboard's review queue clear unrated entries quickly, with keyboard shortcuts in the dashboard.

## Web dashboard

The dashboard at http://127.0.0.1:8000 is where the owner reviews, edits and analyses spending. It is built for a laptop screen, works offline, and binds to localhost only.

| Page | Contents |
| --- | --- |
| Overview | Today, this week and this month to date, each with change against the previous period; the month against the optional monthly target; the month's necessity split as a stacked bar; potential savings this month; recurring total; top 5 categories; count of unrated entries linking to Review |
| Expenses | Table filtered by date range, category, necessity (including unrated), cheaper flag, recurring flag and text search, newest first. Every field is editable inline. Expanding a row shows its items and the Unspecified remainder, with add, edit and delete for items. Deletion is soft, with undo. CSV export of the filtered view, one row per expense, or one row per breakdown line |
| Add | A quick-entry box using the Telegram grammar (the same parser), plus a structured form |
| Review | Unrated expenses and items, one at a time. Keys 1–4 rate, c toggles cheaper, r toggles recurring, s skips, arrow keys move |
| Reports | Day, week or month view; a 12-month trend by necessity as stacked bars; a category-by-month table; flagged items with potential savings, largest first; the recurring list |
| Settings | Categories (name, aliases, defaults, archive); metric parameters with their dated history (add a value with an effective date); monthly target; digest schedule; number format; backup retention |

Display rules:

- Amounts use the `number_format` setting, default ro-RO (1.234,50 RON). Input accepts both formats.
- Changing an item updates the remainder and totals on the page immediately.
- Chart and script libraries are bundled locally, not loaded from a CDN.

## Reports and digests

Every report answers two questions for its period: how much went out, and how much of it was discretionary or replaceable.

Periods: a day is a calendar day, a week runs Monday to Sunday, and a month is a calendar month. The current period is always to date.

| Figure | Definition |
| --- | --- |
| Total | Sum of expense amounts in the period |
| Change | Against the previous period of the same kind; for weeks, also against the average of the previous 4 weeks |
| By necessity | Breakdown lines grouped by level, including Unrated |
| Discretionary | Nice-to-have plus Impulse, as an amount and as a share of the total |
| Flagged | Amount of lines with a cheaper alternative, and the sum of their potential savings |
| Recurring | Sum of recurring lines |
| By category | Breakdown lines grouped by category |
| Daily average | Total divided by the days elapsed in the period |

### Weekly digest

Sent by the bot on Sunday at 20:00 local time (configurable). Format, with example values:

```
Week 21–27 Sep: 1.240,00 RON (−8% vs last week, −3% vs 4-week avg)
Discretionary: 310,00 (25%) · of which Impulse 95,00
Could save: 140,00 on 6 flagged items
Top discretionary: Restaurant 120,00 · Wine 50,00 · Snacks 35,00
Recurring this week: 60,00
Unrated: 4 → /review
```

### Monthly digest

Sent on the 1st of the month at 09:00 for the previous month. Same content as the weekly digest, plus the top 5 categories and the full recurring list.

### Missed digests

If the app was not running at the scheduled time, the digest is sent on the next start. `last_weekly_digest` and `last_monthly_digest` prevent duplicates.

## Configuration, security and operations

Secrets and machine settings live in a `.env` file; everything else lives in the `setting` table and is edited in the dashboard.

```
TELEGRAM_BOT_TOKEN=123456:ABC...
ALLOWED_TELEGRAM_USER_IDS=111111111
DATA_DIR=~/spendtrack-data
WEB_HOST=127.0.0.1
WEB_PORT=8000
TIMEZONE=Europe/Bucharest
```

### Security

- The bot token is only in `.env`, which is git-ignored, and never appears in logs.
- The bot ignores every sender not in `ALLOWED_TELEGRAM_USER_IDS`.
- The dashboard refuses to start on a non-loopback `WEB_HOST` unless `ALLOW_REMOTE=true` and basic-auth credentials are set.

### Data and backups

- The database is `DATA_DIR/spendtrack.db` in WAL mode.
- A daily backup is written to `DATA_DIR/backups/spendtrack-YYYY-MM-DD.db` using SQLite's online backup API, on the first run of each day. The newest 30 are kept.
- Restoring means stopping the app and copying a backup over the database file; the README documents this.
- Logs rotate in `DATA_DIR/logs`.

### Running

- One command, `python -m spendtrack`, runs the bot, the web server and the scheduler in one asyncio process.
- The coding agent provides autostart at login for the owner's operating system: Task Scheduler on Windows, launchd on macOS, or a systemd user service on Linux.
- While the laptop sleeps, Telegram queues messages for up to 24 hours; on wake they are processed with their original dates.

### First-time setup (README)

1. Create a bot with @BotFather and copy its token into `.env`.
2. Start the app and send the bot any message. The log shows the unauthorized sender ID; copy it into `ALLOWED_TELEGRAM_USER_IDS` and restart.
3. Send `/fuel <price>` and `/consumption <value>` to set the driving defaults.
4. Open http://127.0.0.1:8000 and review the seed categories and aliases.

## Acceptance criteria and test cases

Version 1 is done when every case below passes as an automated test and the owner can run the full loop from the phone: send, rate, add detail, read the week.

Test fixture: today is Tuesday 29 Sep 2026; seed categories are loaded; consumption 7.2 L/100 km and fuel price 8.28 RON/L are effective from 1 Sep 2026. Each case starts from this state unless it says otherwise.

| # | Input | Expected result |
| --- | --- | --- |
| 1 | `groceries 100` | #1 Groceries, 100.00 RON, 29 Sep, unrated; reply with rating buttons |
| 2 | `100 lei groceries` | Same as case 1 |
| 3 | `coffee 18,50 !4 ~8` | Eating out, 18.50, Impulse, cheaper alternative 8.00, potential saving 10.50 |
| 4 | `taxi 35 @yesterday` | Transport, 35.00, 28 Sep |
| 5 | `rent 2.500` | Housing, 2,500.00, Essential from the category default |
| 6 | `drive 42km` | Fuel & car, 25.04 (42 × 7.2 / 100 × 8.28 = 25.0387) |
| 7 | `drive 42 km 6.5l 7.99/l` | 21.81; both values marked as overrides in `params_used`; defaults unchanged |
| 8 | After case 1, reply `wine 50 !3` to its confirmation | Item Wine 50.00, Nice-to-have; #1 total stays 100.00; breakdown: Unspecified 50.00 unrated, Wine 50.00 Nice-to-have |
| 9 | After case 1, reply `wine 50, cheese 60` | Rejected, nothing added: items 110.00 exceed 100.00 |
| 10 | After case 8, `/amount 1 40` | Rejected: below the items' total of 50.00 |
| 11 | `groceries` | Rejected, nothing saved; reply suggests "groceries 100" |
| 12 | `coffee 5 10` | Rejected, nothing saved: two amounts |
| 13 | Any message from a user not in the allowed list | No reply; logged as unauthorized with the sender ID |
| 14 | Message sent 23:50 on 28 Sep, processed 07:00 on 29 Sep | `occurred_on` is 28 Sep |
| 15 | The same Telegram update delivered twice | One expense |
| 16 | `/fuel 8.50` on 29 Sep, then `drive 42km @27.09` | 25.04, using 8.28, the price in force on 27 Sep |
| 17 | Expenses of 100 on 29 Sep, 35 on 28 Sep and 50 on 27 Sep, then `/week` | Total 135.00: the week starts Monday 28 Sep |
| 18 | Undo button on #1, then Restore | #1 leaves all totals, then returns |
| 19 | fuel 250 in km mode | Fuel & car, 250.00, saved; the confirmation warns it may double-count driving |
| 20 | Costing mode set to receipts from 29 Sep, then drive 42km and fuel 250 | Drive entry saved at 25.04 for information only; /today total is 250.00 |

Dashboard checks:

- Overview totals equal the `/today`, `/week` and `/month` answers for the same data.
- Editing an item in the Expenses page updates the remainder and totals without a reload.
- The Review page rates an entry with keys 1–4 and moves to the next one.
- CSV export of a filtered view opens in a spreadsheet with correct amounts and dates.

## Build order and later work

Build from the core outward, so every rule is tested before a bot or a page depends on it.

1. Project skeleton, `.env` loading, models, first migration, and seed data (categories, the drive metric).
2. The parser as a pure function, with unit tests for every grammar case above.
3. Core services: create and edit expenses, items with remainder rules, metric calculation with dated parameters, and report queries. Tests for each.
4. The Telegram bot: entry, confirmations with buttons, reply-to-add-detail, commands, errors, allowed-user check.
5. The dashboard: Overview, Expenses, Add, Review, Reports, Settings.
6. Scheduler: weekly and monthly digests, missed-digest catch-up, daily backups.
7. Autostart script for the owner's operating system, and the README with first-time setup.

Later, outside version 1:

- Catch-up for messages older than 24 hours, by reading the chat history through the owner's own Telegram account (Telethon). This needs a private group rather than the direct chat, because message IDs are only shared between members in groups.
- Email as a second input channel.
- Moving the bot to an always-on device such as a Raspberry Pi.
- Receipt photos, bank CSV import, per-category budgets, and more metric types.
