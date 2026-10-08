# Account dimension and transaction fact

## Database evidence before implementation

The working tree was clean on `feat/account-transaction-models` before this
slice. The existing `dbt/target/run_results.json` was generated on October 8,
2026 at 10:22:34 BST (09:22:34 UTC), for `dbt build --target snowflake_dev
--select stg_accounts stg_transactions`. Its invocation ID matches the saved
manifest: `4705d629-2c1f-42c7-8768-3a76bf3eaaa0`.

Both staging views succeeded; all 32 executed database tests passed with zero
failures. The 13 accounts-related tests were six staging required-field tests,
account-key uniqueness, two category tests, accounts_staging_rules,
accounts_staging_reconciliation, the transaction-to-staging-account relationship,
and transactions_account_opening_date. Seven raw-account source tests were
not selected in that build. This evidence comes from saved database execution
results, not offline parsing or the existence of a view; it does not guarantee
that warehouse contents have remained unchanged afterward.

## Account dimension SQL

`dim_accounts` explicitly selects account_id, customer_id, account_type,
spend_profile, opened_at and opened_date from `ref('stg_accounts')`.
No joins, filters or deduplication occur, so accounts with no transactions
remain present. The staging types pass through unchanged, including
TIMESTAMP_TZ opening instants and UTC DATE opening dates. Synthetic balance
remains excluded.

Grain is one frozen account per account_id, with account_id as the natural
dimension key. Customer IDs may repeat. These attributes describe a frozen
snapshot, not account history or the account type effective at transaction
time. Spend profile is a synthetic generation label.

## Transaction fact SQL

`fct_transactions` explicitly selects all ten staging fields, in staging order:
transaction_id, account_id, transaction_type, merchant_category, amount,
direction, transaction_date, status, currency and original_transaction_id.
Its only input is `ref('stg_transactions')`; there are no joins, filters,
derived fields or aggregates. Amount retains NUMBER(18,2) and parent links
retain SQL NULL for payments. This first implementation follows the requested
ten-field projection; the design's proposed transaction_month is deferred.

Grain is one payment or refund attempt per transaction_id. Completed, pending
and failed attempts all remain. Financial summaries must select completed
rows; refunds use their own attempt dates and remain separate rows.

Reports join `fct_transactions.account_id = dim_accounts.account_id` as a
many-to-one relationship. Account uniqueness and the fact relationship test
protect that join. Account descriptive attributes are not copied into the
fact. A customer join/history model is outside this slice.

## Tests and configuration

Both models inherit the existing view materialization and marts schema suffix
from dbt_project.yml; no configuration change is needed. With the documented
DBT_AOIFE target they resolve to BANKING_ANALYTICS.DBT_AOIFE_MARTS.DIM_ACCOUNTS
and BANKING_ANALYTICS.DBT_AOIFE_MARTS.FCT_TRANSACTIONS.

Generic tests require unique, non-NULL account/transaction primary keys, a
non-NULL fact account_id, and fact account references in dim_accounts.
Each reconciliation test projects every model column, groups complete rows
with their occurrence counts, and compares staging and mart in both
directions using EXCEPT. This detects missing, extra, changed and duplicated
rows, even if a duplicate replaces another row without changing total count.
Set comparisons treat NULL parent links consistently.

Staging already checks descriptive required fields, category vocabularies,
dates, amounts, direction/status rules and refund integrity. The build below
reruns those upstream tests; exact row reconciliation carries their validated
values into the marts without duplicating all business-rule tests. The
existing monthly summary and its SQL remain unchanged.

## Offline verification and limitations

Offline dbt parsing uses a disposable dummy profile and output directory,
preserving the saved live run artifacts. Snowflake-dialect syntax checks cover
both model projections and reconciliation tests. Local SQLite execution of
the reconciliation SQL checks identical records (including NULL parent links)
and deliberate dropped, duplicated and changed records, including duplication
with unchanged total count. These checks validate local SQL structure and
reconciliation logic, not live Snowflake results for the new marts.

No warehouse connection, database build, commit or push was performed in
this slice. The new views and their database tests remain unexecuted.

## Build command

From the project root, use the existing uv and hidden-passphrase workflow:

```zsh
(
  read -rs 'DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE?Private key passphrase: '
  printf '\n'
  export DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE
  uv run dbt build --project-dir dbt --profiles-dir "$HOME/.dbt" \
    --target snowflake_dev --select +dim_accounts +fct_transactions
)
```

The leading plus signs include upstream staging dependencies and associated
tests. Raw sources must already exist; dbt does not run the loaders. This
selection does not rebuild the monthly summary. Check run_results.json after
execution to confirm actual model/test outcomes.
