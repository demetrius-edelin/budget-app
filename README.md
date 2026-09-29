# Spendtrack

Spendtrack is a single-user expense tracker that runs on your laptop. You enter each expense in a local web app. Reports show totals per day, week and month, and where you can cut spending. The interface and the Telegram bot speak Romanian.

The specification is in `Spending Tracker — MVP Specification.md`.

## Requirements

- macOS, Linux or Windows.
- Python 3.12 or newer.
- [uv](https://docs.astral.sh/uv/) to install the dependencies.

## First-time setup

1. Install the dependencies:

   ```
   uv sync
   ```

2. Copy the example configuration and set the data folder:

   ```
   cp .env.example .env
   ```

   `DATA_DIR` is the folder that holds the database, the backups and the logs. The default is `~/spendtrack-data`.

3. Start the app:

   ```
   uv run python -m spendtrack
   ```

   The app creates the database, writes the daily backup and opens the browser at http://127.0.0.1:8000.

4. Open **Settings**. Add the fuel price and the consumption with an effective date. The drive form needs both values.

5. Review the seed categories and their defaults on the same page.

## Daily use

- **Add**: enter an expense, or a drive in km. The drive form shows the computed cost before the save.
- **Expenses**: filter, edit inline, add items to an expense, delete with Undo, export CSV.
- **Review**: rate unrated expenses one at a time. Keys `1` to `4` set the level, `c` toggles cheaper, `r` toggles recurring, `s` skips.
- **Reports**: one period with its figures, the 12-month trend, the category table, flagged lines and recurring lines.
- **Overview**: today, this week and this month at a glance, with a month calendar. The three cards also show EUR at the BNR reference rate. The app downloads the BNR rate file once per day into `DATA_DIR/fx`. Without network it uses the last cached rate.

## Entry from the phone with Telegram

The bot is optional. It reads your messages, turns them into entries with a model, and replies with what it saved.

1. Create a bot with @BotFather in Telegram and copy its token into `TELEGRAM_BOT_TOKEN` in `.env`.
2. Pick the model provider in `.env`: `AI_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`, or `openai` with `OPENAI_API_KEY` and `AI_MODEL`, or `openrouter` with `OPENROUTER_API_KEY` and `AI_MODEL`.
3. Start the app and send the bot any message. The log shows your Telegram user id.
4. Put the id into `ALLOWED_TELEGRAM_USER_IDS` and restart.

Then send one expense per message, in English or Romanian: "coffee 18,50", "groceries 210, of which wine 50", "taxi ieri 35", "drove 42 km to Cluj". The bot replies with the saved entry. Send `/help` for the commands.

The laptop must be awake to process messages. Telegram keeps unread messages for 24 hours.

To try the parser before you set up the bot, run:

```
uv run python -m spendtrack.bot.try_parse "coffee 18,50" "groceries 210, of which wine 50"
```

It prints the model output and the values the app would save. It saves nothing.

## Start at login on macOS

Run the install script once from the project folder:

```
scripts/install-launchd.sh
```

The script writes `~/Library/LaunchAgents/com.spendtrack.plist` and loads it. The app then starts at login without a browser window. Open http://127.0.0.1:8000 when you need it.

To remove the agent:

```
scripts/install-launchd.sh --remove
```

## Backups and restore

The app writes a backup to `DATA_DIR/backups/spendtrack-YYYY-MM-DD.db` on its first start each day, and once per hour while it runs. It keeps the newest 30 files. Change the count in Settings.

To restore a backup:

1. Stop the app.
2. Delete `DATA_DIR/spendtrack.db`, `spendtrack.db-wal` and `spendtrack.db-shm` if they exist.
3. Copy the backup file to `DATA_DIR/spendtrack.db`.
4. Start the app.

## Configuration

The `.env` file holds the machine settings:

| Key | Default | Meaning |
| --- | --- | --- |
| `DATA_DIR` | `~/spendtrack-data` | The folder for the database, backups and logs |
| `WEB_HOST` | `127.0.0.1` | The address the app listens on |
| `WEB_PORT` | `8000` | The port |
| `TIMEZONE` | `Europe/Bucharest` | The time zone for dates and periods |
| `TELEGRAM_BOT_TOKEN` | empty | The bot token. Empty runs the app without the bot |
| `ALLOWED_TELEGRAM_USER_IDS` | empty | Your Telegram user id, or several separated by commas |
| `AI_PROVIDER` | `anthropic` | `anthropic`, `openai` or `openrouter` |
| `AI_MODEL` | empty | The model id. Optional for anthropic (default `claude-opus-5-5`), required otherwise |
| `AI_EFFORT` | `low` | Reasoning effort for the parse: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or `off` for the provider default. Anthropic maps `none` and `minimal` to `low` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` | empty | The key of the chosen provider |

The app refuses to start on a non-loopback `WEB_HOST` unless `ALLOW_REMOTE=true`, `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` are set.

Everything else lives in the database, and you change it on the Settings page.

## Development

```
uv run pytest
uv run ruff check spendtrack tests
uv run ruff format spendtrack tests
```

The layout follows the specification: `spendtrack/core` holds every rule, `spendtrack/db` holds the models, migrations and seed data, and `spendtrack/web` holds the routes and templates. The web layer only calls the core.

To change the schema, edit `spendtrack/db/models.py` and create a migration:

```
SPENDTRACK_DB_URL=sqlite:///./dev.db uv run alembic upgrade head
SPENDTRACK_DB_URL=sqlite:///./dev.db uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file before you commit it.
