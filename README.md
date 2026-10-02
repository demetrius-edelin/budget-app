# Spendtrack

Spendtrack is an expense tracker for one person. It runs on your own computer and keeps your data in a local SQLite database. You add an expense from your phone with a Telegram message, or in the local web app. The reports show your totals per day, week and month, and the expenses that you can cut.

The interface and the Telegram bot use Romanian. Amounts are in Romanian lei (RON). This README and the code use English.

## Features

- **Add expenses from Telegram.** Send a short message from your phone, for example `cafea 18,50` or `taxi ieri 35`. A language model reads the message, and the bot replies with the saved entry. Anthropic, OpenAI and OpenRouter are the supported model providers.
- **Rate each expense.** Give each expense one of four necessity levels: Esențial (essential), Important, Util (useful) or Impuls (impulse). You can also mark an expense as recurring, or record a cheaper option.
- **See where you can save.** The reports add the Impuls expenses to the difference between each expense and its cheaper option.
- **Log a drive in km.** The app calculates the fuel cost from the fuel consumption of your car and the fuel price.
- **Track a monthly target.** The overview shows your spending for the month against the target.
- **See amounts in EUR.** The app converts the totals at the reference rate of the National Bank of Romania (BNR).
- **Keep your data safe.** The app writes a backup each day. You can export the expenses to CSV (comma-separated values) files.

## Privacy

The web app and the database stay on your computer. The app downloads the BNR exchange rate file once per day.

The Telegram bot is optional. If you use it, the app sends the text and the date of each message to the model provider that you choose. The app also sends the names of your categories. Telegram receives your messages too, because the bot uses the Telegram service.

## Requirements

- macOS, Linux or Windows.
- Python 3.12 or newer.
- [uv](https://docs.astral.sh/uv/) to install the dependencies.

## First-time setup

1. Install the dependencies:

   ```
   uv sync
   ```

2. Copy the example settings file:

   ```
   cp .env.example .env
   ```

3. Set `DATA_DIR` in `.env`. This folder holds the database, the backups and the logs. The default is `~/spendtrack-data`.

4. Start the app:

   ```
   uv run python -m spendtrack
   ```

   The app creates the database, writes the daily backup and opens the browser at http://127.0.0.1:27431. To start the app without the browser, add `--no-browser`.

5. Open **Setări** (Settings). Add the fuel price and the fuel consumption with an effective date. The drive form needs both values.

6. On the same page, examine the default categories and their default values.

## Daily use

The navigation bar shows the Romanian page names. The English names are in parentheses.

- **Panou (Overview)**: today, this week and this month, with a month calendar. Click a day to see its expenses. The page also shows the month against your target, the split by necessity level, where you can cut, and the top categories. The three period cards also show the totals in EUR. If the network is not available, the app uses the last downloaded rate.
- **+ (Add)**: enter an expense, or a drive in km. The drive form shows the calculated cost before you save it.
- **Cheltuieli (Expenses)**: the filters apply while you type. You can edit an expense in the table, add items to an expense, delete with Undo and export to CSV.
- **Evaluare (Review)**: rate the unrated expenses one at a time. Use these keys:
  - `1` to `4` set the necessity level.
  - `c` sets or clears the cheaper option mark.
  - `r` sets or clears the recurring mark.
  - `s` skips the expense.
  - The left and right arrow keys go to the previous and the next expense.
- **Rapoarte (Reports)**: the figures for one period, the split by necessity level and the category table. The page also shows the marked lines with the largest saving first, the recurring lines, the 12-month trend and the categories per month.

## Add expenses with Telegram

Do these steps once:

1. In Telegram, create a bot with @BotFather.
2. Copy the bot token into `TELEGRAM_BOT_TOKEN` in `.env`.
3. Set the model provider in `.env`. Use one of these options:
   - `AI_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`
   - `AI_PROVIDER=openai` with `OPENAI_API_KEY` and `AI_MODEL`
   - `AI_PROVIDER=openrouter` with `OPENROUTER_API_KEY` and `AI_MODEL`
4. Start the app and send any message to the bot. The log shows your Telegram user ID.
5. Put the ID into `ALLOWED_TELEGRAM_USER_IDS` and restart the app.

Send one expense in each message, in Romanian or in English. These are some examples:

- `cafea 18,50`
- `alimente 210, din care vin 50`
- `taxi ieri 35, puteam lua autobuzul`
- `am condus 42 km până la Cluj`
- `chirie 2500 esențial, lunar`

The bot replies with the saved entry. It also accepts these commands:

| Command | Result |
| --- | --- |
| `/today`, `/week`, `/month` | The totals and the possible savings for the period. |
| `/last [n]` | The last `n` expenses. The default is 5, and the maximum is 20. |
| `/undo` | Deletes the last expense that came from Telegram. |
| `/restore <id>` | Restores a deleted expense. |
| `/help` | The examples and the list of commands. |

The computer must be awake to process the messages. Telegram keeps the unread messages for 24 hours.

To test the parser before you set up the bot, run this command:

```
uv run python -m spendtrack.bot.try_parse "coffee 18,50" "groceries 210, of which wine 50"
```

The command prints the model output and the values that the app will save. It does not save anything.

## Start at login on macOS

Run the install script once from the project folder:

```
scripts/install-launchd.sh
```

The script writes `~/Library/LaunchAgents/com.spendtrack.plist` and loads it. The app then starts at login without a browser window. When you need the app, open http://127.0.0.1:27431.

The agent runs the code from the project folder with the `.venv` of the project. It does not load changed files while it runs. After a code update, restart the agent:

```
./restart.sh
```

The script runs `uv sync` and `launchctl kickstart -k gui/$(id -u)/com.spendtrack`.

To remove the agent, run this command:

```
scripts/install-launchd.sh --remove
```

## Backups and restore

The app writes one backup per day to `DATA_DIR/backups/spendtrack-YYYY-MM-DD.db`. It writes the backup at the first start of the day. If the app runs past midnight, it writes the backup for the new day within one hour. The app keeps the newest 30 files. You can change this number in Setări (Settings).

To restore a backup:

1. Stop the app.
2. If they exist, delete `DATA_DIR/spendtrack.db`, `spendtrack.db-wal` and `spendtrack.db-shm`.
3. Copy the backup file to `DATA_DIR/spendtrack.db`.
4. Start the app.

## Configuration

The `.env` file holds the settings for the computer:

| Key | Default | Meaning |
| --- | --- | --- |
| `DATA_DIR` | `~/spendtrack-data` | The folder for the database, the backups and the logs. |
| `WEB_HOST` | `127.0.0.1` | The address that the app listens on. |
| `WEB_PORT` | `27431` | The port. |
| `TIMEZONE` | `Europe/Bucharest` | The time zone for dates and periods. |
| `TELEGRAM_BOT_TOKEN` | empty | The bot token. If it is empty, the app runs without the bot. |
| `ALLOWED_TELEGRAM_USER_IDS` | empty | Your Telegram user ID, or more IDs separated by commas. |
| `AI_PROVIDER` | `anthropic` | `anthropic`, `openai` or `openrouter`. |
| `AI_MODEL` | empty | The model ID. Optional for `anthropic` (default `claude-opus-5-5`), required for the other providers. |
| `AI_EFFORT` | `low` | The reasoning effort for the parser: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or `off` for the provider default. For Anthropic, `none` and `minimal` become `low`. |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` | empty | The API key of the provider that you use. |

The app listens only on the local computer by default. To listen on a different address, set `ALLOW_REMOTE=true`, `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD`. If one of the three is missing, the app does not start.

The database holds all other settings. Change them on the Setări (Settings) page.

## Development

```
uv run pytest
uv run ruff check spendtrack tests
uv run ruff format spendtrack tests
```

Two documents describe the design:

- `Spending Tracker — MVP Specification.md` describes the features.
- `Spending Tracker — Build Specification.md` describes the code structure.

The code has three parts:

- `spendtrack/core` holds all the rules.
- `spendtrack/db` holds the models, the migrations and the seed data.
- `spendtrack/web` holds the routes and the templates. The web layer only calls the core.

To change the schema, edit `spendtrack/db/models.py` and create a migration:

```
SPENDTRACK_DB_URL=sqlite:///./dev.db uv run alembic upgrade head
SPENDTRACK_DB_URL=sqlite:///./dev.db uv run alembic revision --autogenerate -m "describe the change"
```

Examine the generated file before you commit it.
