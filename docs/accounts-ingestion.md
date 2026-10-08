# Accounts ingestion and staging

This step implements raw accounts and `stg_accounts` from the
[agreed design](account-transaction-model-design.md). Dimensions and facts
remain deferred. Frozen source files are never rewritten.

## Raw and staging rows

Run [03_raw_accounts.sql](../sql/snowflake/03_raw_accounts.sql) separately in
a Snowflake worksheet. It uses `CREATE ... IF NOT EXISTS`, preserving existing
tables/data. The six required raw fields use explicit VARCHAR lengths:
36 for UUIDs, 32 for category labels, and 64 for balance/timestamp text.
The actual maximum text lengths were 36, 7, 12, 18, and 29 respectively.
Source balance text is preserved exactly, without conversion through float or
rounding to monetary scale. It is independently generated, has no as-of date
or ledger meaning, and is excluded from staging.

One staging row represents one frozen account, including accounts without
transactions. The view explicitly selects account_id, customer_id,
account_type, spend_profile, opened_at (TIMESTAMP_TZ), and opened_date (DATE).
It parses `YYYY-MM-DD HH24:MI:SS TZHTZM "UTC"` strictly and derives opened_date
after conversion to UTC, independently of session timezone. No filtering,
deduplication, or customer enrichment occurs. Spend profile is synthetic.

## Loader safeguards

`scripts/load_accounts_snowflake.py` reads only `fixtures/banking-v2/accounts.csv` and
its manifest, verifies SHA-256 before parsing, and requires 2,000 rows with
unique canonical account UUIDs, canonical customer UUIDs, all six fields,
known categories, a finite numeric balance within the source generation
range, and the exact explicit UTC timestamp format. Raw text remains unchanged.

Authentication reuses the transaction loader's selected
`etl_project/snowflake_dev` profile settings and BANKING_DEVELOPER role,
BANKING_DEV_WH warehouse, BANKING_ANALYTICS database, and encrypted-key
authentication. The key passphrase is prompted privately at runtime; settings
and source records are never printed. `--validate-only` returns before profile
access, prompting or connection.

The loader requires the exact raw column order/types and NOT NULL constraints
and an empty destination. It does not create, replace, clear or append to an
existing populated table. Bound inserts run inside an explicit transaction;
row count, distinct account count, and every field of every loaded row must
match the source before commit. Failure triggers rollback. Run one loader at
a time against this target: the empty-table check is not a concurrency lock.
If commit acknowledgement is lost, inspect the target before retrying.

## Local checks and their limits

Local validation passed for 2,000 accounts. Thirteen offline unit tests passed
across both loaders, covering unchanged text bindings, changed hashes/headers,
bad fields/duplicate IDs, populated/incompatible targets, wrong role, insert
failure, count/record mismatch rollback, and validate-only's no-connection path.
Offline dbt parsing with a disposable dummy profile and Snowflake-dialect SQL
syntax checks passed. No real profile/key contents were read during checks.

dbt tests cover raw required fields/key uniqueness, staging required fields,
key uniqueness, category values, canonical UUID formats, UTC date derivation,
bidirectional raw/staging row and count reconciliation, transaction account
relationships, and transaction dates on/after account opening. Customer IDs
are allowed to repeat. Balance remains raw-only.

These checks prove local input validity and simulated loader control flow;
they do not prove live authentication, privileges, destination compatibility,
Snowflake timestamp evaluation, view creation or database test results.
No Snowflake SQL or database builds/tests were executed by the agent.

## Commands to run from the project root

First validate locally:

```zsh
uv run python scripts/load_accounts_snowflake.py --validate-only
```

Then run `sql/snowflake/03_raw_accounts.sql` in a Snowflake worksheet using
the existing development connection. After that, load interactively:

```zsh
uv run python scripts/load_accounts_snowflake.py
```

Finally build the two staging views and their associated tests, including the
new account relationships and opening-date check:

```zsh
(
  read -rs 'DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE?Private key passphrase: '
  printf '\n'
  export DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE
  uv run dbt build --project-dir dbt --profiles-dir "$HOME/.dbt" \
    --target snowflake_dev --select stg_accounts stg_transactions
)
```

With the documented DBT_AOIFE target, accounts staging is
`BANKING_ANALYTICS.DBT_AOIFE_STAGING.STG_ACCOUNTS`. The profile target schema
controls the prefix. Source declarations do not create or load raw tables.
