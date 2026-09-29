# Spendtrack

Spendtrack is a single-user expense tracker that runs on your laptop. You enter each expense in a local web app. Reports show totals per day, week and month, and where you can cut spending.

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
