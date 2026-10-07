# Spending Tracker: Extra Income Plan

Status: built on 2026-10-07. Date of the plan: 2026-10-07.

## Goal

Let the owner add an extra income in the web app. An extra income raises the monthly limit for the month of the income. The Telegram bot cannot add an extra income.

## Decisions

The owner made these decisions on 2026-10-07:

1. An extra income counts only in its own month. The unused part does not go to the next month.
2. A monthly target always exists. The app does not need a limit that comes only from extra income.
3. The form to add an extra income is on the Overview page.
4. Only the Overview page shows the extra income. The Reports page, the Expenses page and the CSV (comma-separated values) export do not change.

## Current state

- The monthly target is one value in the `setting` table, with the key `monthly_target_minor`. The functions are in `spendtrack/core/settings.py`.
- `reports.overview` in `spendtrack/core/reports.py` divides the month total by the target. The result is `target_share_pct`.
- The card "Luna față de țintă" in `spendtrack/web/templates/overview.html` shows a bar and the text "total din țintă (procent)".
- The card always shows the current month. The calendar on the same page can show an earlier month, but the card does not follow it.
- The Telegram bot creates only expenses. It has no access to the target.
- The daily backup copies the whole database file. A new table goes into the backup with no change.

## Design

### Data

Add the table `income` with these columns:

- `id`: integer, the primary key.
- `received_on`: date, with an index.
- `amount_minor`: integer in bani (RON minor units). The value is more than zero.
- `description`: optional text, for example "bonus".
- `created_at`: UTC (Coordinated Universal Time) datetime.
- `deleted_at`: UTC datetime. The value is empty for a live row.

A delete sets `deleted_at`. This is the same soft delete as for expenses. It lets the owner undo a delete.

### Calculation

The limit for a month is the monthly target plus the sum of the live extra income in that month.

The card compares the month total with this limit. For example, with a target of 3.000 RON and an extra income of 500 RON, the limit is 3.500 RON.

### Overview card

The card "Luna față de țintă" changes as follows:

- The bar and the percent use the limit, not the target alone.
- The text shows "1.200,00 din 3.500,00 RON (34,3%)".
- A second line shows the parts: "Țintă 3.000,00 + venituri suplimentare 500,00".
- A short list shows the extra income of the month: date, description, amount and a "Șterge" (Delete) link.
- After a delete, a banner shows "Venit șters" with a "Restaurează" (Restore) link.
- A small form adds an extra income: "Sumă" (amount), "Descriere" (description), "Data" (date) and the button "Adaugă venit".

The date field accepts only a date in the current month. The default is today. The server also rejects a date outside the current month.

**Why:** The card shows only the current month. An extra income in an earlier month does not show anywhere, so the owner cannot see or delete it.

## Steps

1. Add the model `Income` in `spendtrack/db/models.py`.
2. Add the migration `spendtrack/db/migrations/versions/0004_income.py`. The migration only adds a table. The existing data does not change.
3. Add the module `spendtrack/core/income.py` with these functions:
   - `add_income` checks the amount and the date, and then adds the row.
   - `list_income` returns the live rows of one period.
   - `income_total_minor` returns the sum of the live rows of one period.
   - `delete_income` and `restore_income` set and clear `deleted_at`.
4. Change `reports.overview`:
   - Add the fields `extra_income_minor`, `month_limit_minor` and `income`.
   - Calculate `target_share_pct` from `month_limit_minor`.
5. Add three routes in `spendtrack/web/routes/overview.py`:
   - `POST /income` adds an extra income.
   - `POST /income/{income_id}/delete` deletes an extra income.
   - `POST /income/{income_id}/restore` restores an extra income.
   - Each route redirects to `/` with the status 303. If the input is not correct, the page shows the error in the card.
6. Change the card in `spendtrack/web/templates/overview.html`. Add the CSS (Cascading Style Sheets) rules for the list and the form in `style.css`.
7. Add the tests. See the next section.
8. Add one paragraph about the extra income to the "Daily use" section of `README.md`.

## Tests

- Core: add an extra income, and reject an amount of zero, a negative amount and a date outside the current month.
- Core: an extra income on 30 September does not change the limit for October.
- Core: a deleted extra income does not count. A restored extra income counts again.
- Reports: `target_share_pct` uses the target plus the extra income. Change the existing `test_overview` or add a new test.
- Web: the form adds an extra income, and the card shows the new limit.
- Web: the delete link and the restore link work.
- Migrations: the head revision is `0004`, and the table `income` exists.

## Size

The estimate is about 300 lines of code and tests. No existing feature changes, other than the target card.

## Risks

- The new card holds more content. On a phone screen, the form can make the card long. Put the form below the list. If the screen is wide, keep the fields on one row.
- A month with a large extra income shows a low percent. This is the expected result, because the limit is higher.
