# ETL + NLP Project

This repository contains a partly implemented local banking analytics pipeline.
Snowflake migration is planned work; the current loader targets Postgres.

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
5. The dbt project in `dbt/` contains five banking mart models, configured as
   views by default, plus the original starter models.

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
  python3 scripts/load_csvs.py
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

There are no raw source declarations or staging models. The banking marts
reference missing `stg_customers`, `stg_accounts` and `stg_transactions` models,
so their dependency graph is incomplete. No banking tests are defined; the
only model tests cover the starter examples. dbt connection configuration is
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
CSV loading into Snowflake and a Snowflake connection in the dbt browser UI
still need implementation. The browser UI does not automatically load local
CSVs or execute this Postgres loader.

`full_project.txt` is an ignored historical project dump containing duplicated
local credentials. It must not be included in the baseline commit.
