# Spending Tracker: Multilingual Interface Plan

Status: plan only. Nothing is built yet. Date of the plan: 2026-10-06.

## Goal

Add a language selector on the right side of the top navigation bar. The selector has two options: English and Română. The selector changes the whole app to the selected language at once. The app gets a full English translation.

## Current state

The whole user-facing side is Romanian. This includes the web pages, the Telegram bot replies, the core validation messages, the seed category names, the necessity levels and the date words.

About 380 lines of user-facing Romanian text exist in about 30 files. These files hold the most text:

| File | Lines with Romanian text |
| --- | --- |
| `spendtrack/bot/service.py` | 40 |
| `spendtrack/web/templates/partials/expense_block.html` | 36 |
| `spendtrack/core/expenses.py` | 32 |
| `spendtrack/web/templates/settings.html` | 29 |
| `spendtrack/web/templates/overview.html` | 23 |
| `spendtrack/web/templates/reports.html` | 22 |
| `spendtrack/web/templates/add.html` | 19 |
| `spendtrack/db/seed.py` | 18 |
| `spendtrack/core/ai_parse.py` | 17 |
| `spendtrack/web/templates/expenses.html` | 16 |
| `spendtrack/core/ai_openai.py` | 15 |

These facts affect the plan:

- Two lookups find a category by its name: `UNCATEGORIZED` ("Necategorisit") and `FUEL_CATEGORY` ("Combustibil și mașină") in `spendtrack/db/seed.py`. The AI parse and the drive entry use them.
- The settings table already stores the number format. The language setting can use the same table.
- The Expenses filters keep their state in the URL with `hx-replace-url`. A page reload keeps the filters.
- `app.js` holds almost no text. The chart labels come from the server.
- The AI parse prompt tells the model to write the descriptions in Romanian.

## Approach

Translate the text on the server. When the owner selects a language, the app saves the choice and reloads the current page. On a local server, the reload takes less than one second.

Do not change the language in the browser without a reload. That approach needs a second copy of every text in JavaScript, also for the error messages and the HTMX partials. The two copies then drift apart.

### Library

Use Babel with the `i18n` extension of Jinja2. This is the standard gettext method (the GNU translation system).

- `pybabel extract` finds the marked text in the templates and in the Python code.
- Each language has one PO file (Portable Object, a text file that holds the translations).
- Babel also formats the dates and the month names for each language.
- The app reads the catalogs once at start. Each translation is a dictionary lookup, so the speed of the app does not change.

The source text in the code is English. The file `ro.po` holds the Romanian text that the code holds today. This agrees with the project rule that the code stays in English.

The app can read the PO files at start with `babel.messages.pofile.read_po`. Then the project needs no compile step and no binary MO files in git.

## Steps

1. Add the base.
   - Add `babel` to the dependencies.
   - Add the module `spendtrack/i18n.py`. It keeps the current language in a context variable (a value that each request holds separately).
   - Add a middleware that reads the language setting and sets the context variable for each request.
   - Install `_()` and `ngettext()` in the Jinja environment.
   - Set `<html lang>` in `base.html` from the current language.
2. Add the selector.
   - Put an "EN | RO" control on the right side of the top navigation bar in `base.html`.
   - When the owner clicks an option, send `POST /language`.
   - Save the choice in the route. Return the header `HX-Refresh: true`, so that HTMX reloads the same page.
3. Mark the text in the templates.
   - Wrap each text in `_()` or in `{% trans %}`.
   - Do this in all 15 templates and partials.
4. Mark the text in the Python code.
   - Wrap the validation messages, the route messages, the report labels and the bot replies.
   - Translate a message at the time that the app shows it. Do not translate it at the time that Python loads the module.
   - Use a lazy string (a string that the app translates later) for a constant at module level.
5. Translate the fixed words.
   - Translate the necessity levels and their names where the app shows them: Essential, Important, Useful, Impulse and Unrated.
   - Translate Unspecified in the same way. The database stores numbers for the levels, so the data does not change.
   - Replace the Romanian tables in `short_date` and `month_short` with Babel date formats.
   - Keep the number format (1.234,50 or 1,234.50) as a separate setting.
6. Check the charts and `app.js`. The chart labels come from the server, so step 3 covers them.
7. Keep fixed English column names in the CSV (comma-separated values) export. Then a file has the same columns in both languages.
8. Build the catalogs.
   - Run `pybabel extract` to collect the marked text.
   - Create `ro.po` and put the current Romanian text into it.
   - Create `en.po`. English is the source language, so this file stays almost empty.
9. Update the tests.
   - Run the current tests with Romanian set, because they check Romanian text.
   - Add tests that load some pages in English.
   - Add one test for missing translations. The test fails for a marked text that has no Romanian translation.
10. Update the documents.
    - Update the README and the MVP specification.
    - Update the memory note that says the interface is Romanian only.

## Open decisions

| Decision | Options | Recommendation |
| --- | --- | --- |
| Category names | (a) Add a key to the 13 seed categories and translate them. Keep the categories of the owner as typed. (b) Do not translate the categories. | (a). The key also removes the two lookups by name. |
| Language of the Telegram bot | Follow the app language, or keep Romanian. | Follow the app language. The parser already reads Romanian and English messages. |
| Storage of the choice | The settings table, or a cookie for each browser. | The settings table. Then the laptop, the phone and the bot use the same language. |

If the bot follows the app language, give the language to the AI parse prompt as a value. Then the model writes the descriptions in the selected language.

## Risks

- A text without a marker stays in English in both languages. The test in step 9 finds a marked text without a translation, but it does not find a text without a marker. Examine each page in both languages.
- The bot thread has no web request. Set the language for the bot thread separately.
- A category name that the owner changed is data. The app must not translate it.

## Order of work

1. Do steps 1 and 2 first, with the navigation bar text translated. Then the owner can try the selector early.
2. Translate the pages one at a time: Panou, Cheltuieli, Evaluare, Rapoarte, Setări and Adaugă.
3. Translate the core messages and the bot replies last.
