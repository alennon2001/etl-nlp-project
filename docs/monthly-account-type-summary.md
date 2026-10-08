# Monthly transactions by account type

## Saved database results inspected

Before this change, the latest saved run_results.json was generated on
October 8, 2026 at 10:42:55 BST (09:42:55 UTC) by the snowflake_dev build
selecting `+dim_accounts +fct_transactions`. Its invocation matches the saved
manifest. Four models succeeded and all 47 selected tests passed with zero
failures, including all eight dimension/fact tests: their key checks, complete
row reconciliations and the fact-account relationship. This is evidence from
a saved database build, not inference from offline checks. Existing uncommitted
mart changes were preserved on feat/account-transaction-models.

## Join and aggregation

`monthly_transaction_summary_by_account_type.sql` reads fct_transactions as
`t`, joins dim_accounts as `a` using `t.account_id = a.account_id`, and filters
`t.status = 'completed'`. The dimension supplies only account_type. A unique
account key gives each fact attempt exactly one account match; a separate
cardinality test checks all attempts with a left join, returning IDs with zero
or multiple matches. Testing each ID catches loss and multiplication even
when they cancel in the overall row count.

The completed CTE derives transaction_month with
`cast(date_trunc('month', t.transaction_date) as date)`. The monthly CTE groups
by transaction_month, currency and account_type. `count(*)` counts completed
attempts; conditional sums put positive debit amounts in debit_total and
positive credit amounts in credit_total. Both totals are cast to NUMBER(38,2),
and the final projection casts debit_total minus credit_total to NUMBER(38,2)
as net_outflow. These match the existing monthly summary's definitions and
types; transaction_count remains the integer count returned by COUNT.

Grain is one row per calendar month/currency/account_type with completed
activity. Refunds use their own transaction month. Pending/failed attempts
remain in the fact but contribute nothing here. No zero-activity rows are
fabricated and currencies are kept separate. The model inherits the existing
view materialization and marts schema suffix.

Account types represent the frozen account snapshot. They are not the
historically effective account type on the transaction date. Balance is not
selected or used. The existing monthly_transaction_summary remains unchanged
as the independent comparison baseline sourced from staging.

## Tests and offline evidence

Generic tests require all grain and measure columns and validate the account
type vocabulary. Singular tests check unique month/currency/account_type
combinations and exactly one account match per transaction ID.

The reconciliation rolls up typed rows by month/currency, summing all four
measures. It full-outer-joins the baseline on both keys, rejects missing keys
on either side, and uses IS DISTINCT FROM for exact, NULL-safe comparisons.
Missing/unexpected months or currencies cannot vanish through an inner join.
Snowflake decimal comparisons use no floating tolerance.

Offline parsing with a disposable dummy profile passed: six active models,
66 tests and view materialization for the new model. Snowflake-dialect syntax
checks passed for the model and three singular tests. All 18 local unit tests
passed. The new tests execute guardrail SQL in SQLite against valid fixtures,
duplicate grains, missing/duplicate account matches whose counts cancel,
missing/unexpected groups, and changed or NULL measures. These exercise
failure detection, not Snowflake numeric execution or live data correctness.
The saved live artifacts and existing monthly-summary SQL were preserved.

No warehouse connection, database build, commit or push occurred. New model
execution, exact warehouse reconciliation and full-project source-test
results remain unverified until the following build runs.

## Full-project build

From the project root:

```zsh
(
  read -rs 'DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE?Private key passphrase: '
  printf '\n'
  export DBT_ENV_SECRET_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE
  uv run dbt build --project-dir dbt --profiles-dir "$HOME/.dbt" \
    --target snowflake_dev
)
```

There is no selection restriction: this builds all six active models and runs
all 66 active tests, including raw-source tests, staging tests, mart tests and
both summary reconciliations. Archived models remain outside active paths.
Raw tables must already be loaded; dbt does not run loaders. Check the new
run_results.json for actual successes, passes, errors, failures or skipped
nodes; a build stops dependent work when upstream checks fail.
