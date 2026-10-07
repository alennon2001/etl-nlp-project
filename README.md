# ETL + NLP Project

This repository contains a partly implemented local banking analytics pipeline.
Snowflake migration is planned work; the current loader targets Postgres.

## Project Python environment

Use uv from the project root to recreate the shared ingestion/dbt environment:

```sh
uv sync --locked
```

`uv sync` creates or synchronizes `.venv`. The `--locked` option requires the
committed lockfile to agree with the dependency manifest rather than changing
dependency resolution. `.python-version` selects Python 3.12.13;
`pyproject.toml` constrains the project to Python 3.12 and declares
dbt-snowflake, pandas, SQLAlchemy and psycopg2-binary. `uv.lock` records their
resolved versions and transitive dependencies. This is a scripts/dbt project:
uv does not build or install the repository itself as a Python package.

Use `uv run` to execute commands in this environment without activating it:

```sh
uv run python --version
uv run dbt --version
```

For dbt model commands, change into `dbt/` first; uv can locate the parent
project environment. Model execution still requires separate connection
configuration and completion of the missing staging models.

In VS Code, open the project folder, run **Python: Select Interpreter** from
the Command Palette, choose **Enter interpreter path**, and select
`.venv/bin/python` inside this project. Selecting that interpreter does not
automatically export credentials from `.env`; use the explicit environment
setup below for terminal ingestion commands.

No separate Snowflake ingestion library is declared yet. dbt-snowflake brings
its own connector dependencies; a Snowflake loader is still planned work.

## Current pipeline

1. Spoof configurations in `configs/`, grouped by
   `bundles/banking_bundle.json`, describe synthetic customers, accounts, cards
   and transactions. Customers must exist before accounts; accounts must exist
   before cards and transactions.
2. Generated CSVs live in `output/`. They are local generated artifacts and are
   excluded from the migration baseline.
3. `scripts/load_csvs.py` reads those four CSVs with pandas and writes them to
   Postgres using SQLAlchemy. Each load replaces the corresponding table;
   it does not append, validate business rules or define key constraints.
4. `docker-compose.yml` defines Postgres 15 with a persistent `pgdata` volume.
   It does not execute Python or dbt.
5. The dbt project in `dbt/` is ready for new transaction models. Its five
   unfinished banking marts and original starter models are preserved in
   `archive/dbt/models/`, outside the active `dbt/models/` resource path.

## Banking v2 transactions

`scripts/generate_transactions_v2.py` is the current transaction generator.
It uses the verified frozen accounts in `data_snapshots/banking-v1/` and does
not regenerate customers, accounts or cards. The original four CSVs in
`output/` and the snapshot remain unchanged.

The exact generation command used from the project root was:

```sh
.venv/bin/python scripts/generate_transactions_v2.py
```

You can also use `uv run python scripts/generate_transactions_v2.py`.
The script resolves data paths relative to the repository, validates before
publication and refuses to overwrite an existing `output/banking-v2/` directory.
Do not rerun it to inspect the already generated result.

The ignored `output/banking-v2/` directory contains `transactions.csv` and
`generation.json`, recording parameters and hashes. Validation confirmed
10,000 unique transactions: 9,000 payments and 1,000 linked refund attempts,
with exactly 9,000 completed, 700 pending and 300 failed overall. Dates cover
April 21–September 30, 2026. All account/date, GBP, two-decimal positive amount,
direction and refund relationship checks passed. A temporary regeneration
produced the identical CSV hash without touching the versioned output.

See [the dataset specification](docs/banking-v2-dataset.md) for the schema,
training assumptions, status allocations and full verification results.
The legacy Postgres loader still uses the original root-level CSVs; it does
not load the v2 dataset.

`scripts/etl_pipeline.py` is a separate retail-data cleaning example with local
file paths. It is not part of the banking loader. NLP is not implemented.

## Local credentials

Copy `.env.example` to `.env` if you do not already have a local `.env`, then
replace its safe placeholders with your local configuration. Never commit
`.env` or put credentials in source files. It is ignored by Git; `.env.example`
is intended to be committed. Keep `.env` readable only by your account.

Both the loader and Compose use `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`POSTGRES_DB`. `POSTGRES_PORT` is the host port published by Compose and the
port used by the locally launched loader. `POSTGRES_HOST` is the loader's
address for Postgres, normally `localhost` when Python runs on your computer.
Compose does not need that host value: it starts the database itself.

Compose reads `.env` for configuration interpolation. This does **not** export
its variables to a separately launched Python process. The loader reads
`os.environ` and does not automatically parse `.env`.

For the supplied shell-compatible `.env`, launch Python from the project root
with the variables exported in a subshell:

```sh
(
  set -a
  . ./.env
  set +a
  uv run python scripts/load_csvs.py
)
```

Only source a trusted local file: the shell executes its contents. Quote values
using shell syntax, particularly passwords containing spaces, `$`, `#` or
other special characters. SQLAlchemy `URL.create` accepts the resulting raw
credential values without manually URL-encoding them. Alternatively, supply
the five variables through your terminal or execution environment.

Running the command above performs database writes and replaces existing
tables. It requires the CSVs, a reachable Postgres database, and pandas,
SQLAlchemy and psycopg2 in the Python environment. No dependency installation
or pipeline execution is performed by repository configuration alone.

The persistent Postgres volume retains its initialized database. Changing
credentials in `.env` does not automatically change credentials in an already
initialized database.

## Known dbt gaps

There are no active raw source declarations, staging models or banking tests.
The archived banking marts reference missing `stg_customers`, `stg_accounts`
and `stg_transactions` models. The archived starter examples retain their
original tests. dbt connection configuration is
separate from the Python loader and must be configured locally or in the dbt
platform; local `profiles.yml` files are ignored.

The customer activity SQL compares `transaction_type` to `debit` and `credit`,
but generated data stores those values in `direction`. Its spend/income logic
needs correction and agreed status/time-window rules. Other thresholds and
the assumed 2% revenue calculation also need review.

## Planned Snowflake migration

The first proposed flow is a Snowflake raw transactions table, a declared dbt
source, `stg_transactions` with explicit types and data tests, and a monthly
summary of completed transactions with counts and debit/credit totals.
Local dbt Core key-pair connection testing for `snowflake_dev` has passed
(user-run). CSV loading into Snowflake, active dbt models/tests and a connection
in the dbt browser UI still need implementation. The browser UI does not automatically load local
CSVs or execute this Postgres loader.

`full_project.txt` is an ignored historical project dump containing duplicated
local credentials. It must not be included in the baseline commit.
