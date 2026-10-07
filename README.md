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
configuration. The first transaction flow is implemented; database build
and test results remain pending execution.

In VS Code, open the project folder, run **Python: Select Interpreter** from
the Command Palette, choose **Enter interpreter path**, and select
`.venv/bin/python` inside this project. Selecting that interpreter does not
automatically export credentials from `.env`; use the explicit environment
setup below for terminal ingestion commands.

The Snowflake loader directly imports `snowflake-connector-python` and PyYAML;
both are declared dependencies resolved together with dbt-snowflake.

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
5. The dbt project in `dbt/` implements raw transactions → transaction staging
   → completed monthly summary. Its five
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

## First Snowflake transaction load

The loader is implemented and locally checked. The user reports a successful
Snowflake load of 10,000 rows with 10,000 distinct IDs and April 21–September 30
dates. All six reported grouped counts and exact amount totals match the CSV.
Its only data target is `BANKING_ANALYTICS.RAW.TRANSACTIONS`.

First validate locally, without any connection or passphrase prompt:

```sh
uv run python scripts/load_transactions_snowflake.py --validate-only
```

It verifies all frozen snapshot hashes, the v2 CSV hash and input provenance
in `generation.json`, the exact ten-column header and every dataset rule.
The same validation runs automatically before an actual load.

Next execute `sql/snowflake/02_raw_transactions.sql` yourself in a Snowflake
worksheet. It uses `BANKING_DEVELOPER` and `BANKING_DEV_WH`, creates the RAW
schema/table only if absent, and never replaces or clears an existing table.
It requires the appropriate schema/table creation privileges. Creation is
separate because Snowflake DDL implicitly commits transactions; the Python
insert transaction contains no DDL. An incompatible existing table makes the
loader stop rather than changing its structure.

From the repository root, run the interactive load:

```sh
uv run python scripts/load_transactions_snowflake.py
```

The script reads only `etl_project.outputs.snowflake_dev` from the local
`~/.dbt/profiles.yml`, preserving that file and the Postgres output. It uses
the established account/login/key path and requires `BANKING_DEVELOPER`,
`BANKING_DEV_WH` and `BANKING_ANALYTICS`. It sets the loading schema to RAW
without changing dbt's configured DBT_AOIFE schema. An encrypted-key passphrase
is requested privately using a terminal prompt, never placed in Git, logged,
or read from the dbt passphrase environment variable. Use the replacement
key's passphrase. If hidden input is unavailable, the script stops.

IDs remain strings, amounts use Python `Decimal`, dates are explicitly parsed,
and blank payment `original_transaction_id` values become SQL NULL.
The loader checks target column names/order/types and refuses a nonempty
table. It then inserts 500-row parameterized batches with autocommit disabled.
Before committing, it compares row count, unique transaction count, and exact
amount sums plus counts grouped by currency, transaction type, direction and
status. An insert or reconciliation failure triggers rollback; the connection
is closed afterward. Library error text is withheld to avoid exposing secrets;
Snowflake error codes and the failure phase provide diagnostic context.

Run only one loader at a time and avoid other writers during the load. An
empty-table precheck is not a concurrency lock. A successful rerun stops
because the table contains data: there is no automatic append, truncate or
replacement. If connection loss prevents confirming a commit/rollback,
inspect the target in Snowflake before retrying; do not assume it is empty.

Local checks completed: validation of the actual 10,000-row CSV, eight tests
using fake connections for transaction/reconciliation and hash protections,
and `uv pip check`. These do not establish live permissions or successful
loading. To repeat the tests without contacting Snowflake:

```sh
uv run python -m unittest discover -s tests -v
```

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

## First dbt flow

`banking_raw.transactions` declares the existing external table
`BANKING_ANALYTICS.RAW.TRANSACTIONS`. `source('banking_raw', 'transactions')`
resolves that input and records lineage; it does not create or reload raw data.

`stg_transactions` explicitly selects and types all ten columns. Its grain
is one row per transaction attempt, preserving every status and exact amounts.
Blank payment parent IDs are normalized to NULL. It does not filter or
deduplicate rows. `monthly_transaction_summary` uses `ref('stg_transactions')`
to resolve the dbt-created view and establish build order. It filters completed
rows and groups by calendar month and currency, so its grain is one row per
month/currency with completed activity. Months without activity are absent.

The summary columns are `transaction_month` (DATE), `currency` (VARCHAR(3)),
`transaction_count` (integer count), `debit_total`, `credit_total`, and
`net_outflow` (NUMBER(38,2)). Net outflow is debit total minus credit total.

With the current Snowflake target schema DBT_AOIFE, default dbt schema generation
appends the configured suffixes. The unquoted Snowflake object names are:

- `BANKING_ANALYTICS.DBT_AOIFE_STAGING.STG_TRANSACTIONS`
- `BANKING_ANALYTICS.DBT_AOIFE_MARTS.MONTHLY_TRANSACTION_SUMMARY`

Both are views under the existing project configuration. They do not build
directly in RAW or the unsuffixed DBT_AOIFE schema. BANKING_DEVELOPER needs
SELECT access to the raw table and permission to create the output schemas/views.
Different profile target schemas produce different output names.

There are 27 tests: required fields, unique transaction IDs, accepted category
values, positive amounts, type/direction rules, training date boundaries,
blank payment links, valid refund parent relationships and unique refund
parents, unique month/currency groups, and monthly count/amount reconciliation.
Singular SQL tests pass only when they return zero failing rows.

Local offline dbt parsing and Snowflake-dialect SQL syntax checks passed with
dbt Core 1.12.5 / dbt-snowflake 1.12.1. No database model or test has been run
by the agent. CSV-based expected summary: six GBP months, 9,000 completed rows,
GBP 2,012,092.38 debits, GBP 226,623.07 credits, GBP 1,785,469.31 net outflow.

Run the targeted build yourself from the project root in zsh:

```zsh
(
  read -rs 'DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE?Private key passphrase: '
  printf '\n'
  export DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE
  uv run dbt build --project-dir dbt --profiles-dir "$HOME/.dbt" \
    --target snowflake_dev --select +monthly_transaction_summary
)
```

Enter the replacement key's passphrase; input stays hidden and the subshell
discards the variable afterward. The leading `+` selects upstream dependencies
as well as the summary, and their associated tests. This builds views and runs
database tests; it never invokes the loader or alters raw transaction data.

Archived models remain outside active paths. Their missing customer/account
staging dependencies and historical activity/revenue calculation issues are
still unfinished. The Postgres output is preserved, but these active models
target Snowflake and should be built explicitly with `--target snowflake_dev`.

## Planned Snowflake migration

The first flow now has a loaded raw table (user-reported), source declaration,
transaction staging, monthly summary and tests. Its first targeted dbt build
and database test results remain pending.
Local dbt Core key-pair connection testing for `snowflake_dev` has passed
(user-run). The raw-table definition and Python loader are implemented;
the reported live load reconciles to the CSV. Further banking models and a
connection in the dbt browser UI still need implementation. The browser UI does not automatically load local
CSVs or execute this Postgres loader.

`full_project.txt` is an ignored historical project dump containing duplicated
local credentials. It must not be included in the baseline commit.
