# Account and transaction model design

## What one account represents

One frozen account row represents one synthetic bank account, identified by
`account_id`, belonging to a customer identified by `customer_id`. An account
can have many payment or refund attempts. Each v2 transaction belongs to
exactly one account through `account_id`; a refund is a separate attempt with
its own transaction ID and a link to its original payment.

The account dataset is a fixed snapshot, not an account history or ledger.
Use one dimension row per account, including accounts with no transactions.
Account type describes the frozen account, not a historically effective type
at the time of each transaction. No type changes are modeled in this slice.

## Inspection scope and evidence

Inspected locally on October 8, 2026, on `feat/account-transaction-models`.
The working tree was clean before this documentation change. No branch was
switched, warehouse connection made, dbt command run, or data regenerated.
No credentials, private keys, or customer email values were inspected or shown.

Authoritative inputs and implementation references:

- Frozen accounts: `data_snapshots/banking-v1/accounts.csv` and `SHA256SUMS`.
- Actual v2 output: `output/banking-v2/transactions.csv` and `generation.json`.
- Contract: [banking-v2-dataset.md](banking-v2-dataset.md) and
  [generate_transactions_v2.py](../scripts/generate_transactions_v2.py).
- Account generation configuration: [accounts.json](../configs/accounts.json).
- Current warehouse flow: [raw transaction DDL](../sql/snowflake/02_raw_transactions.sql),
  [transaction loader](../scripts/load_transactions_snowflake.py), and
  [active dbt project](../dbt/dbt_project.yml).

The frozen account hash is
`77978fdca0ff97e336e090f549e96d1e00158f1d266253406df5e414afbdeb12`.
`output/accounts.csv` matches those bytes. All four frozen files passed the
generator's manifest verification; v2 metadata input hashes and transaction
output hash also matched. These are local checks, not confirmation of current
Snowflake contents. The older `configs/transactions.json` and
`output/transactions.csv` are not the v2 transaction contract/input.

## Actual account columns and profile

The actual CSV header, in order, has these six columns. CSV values are text;
the types below describe their observed meaning, not an existing SQL schema.

| Column | Observed meaning | Distinct values | Missing values |
| --- | --- | ---: | ---: |
| account_id | Canonical UUID; account key | 2,000 | 0 |
| customer_id | Canonical UUID; customer reference | 1,000 | 0 |
| account_type | Account category | 3 | 0 |
| spend_profile | Synthetic generation category | 3 | 0 |
| balance | Independently generated decimal number | 2,000 | 0 |
| opened_at | Timestamp with UTC offset | 1 | 0 |

There are **2,000 rows, 2,000 unique account IDs, zero duplicate account IDs,
and zero exact duplicate rows**. Both ID columns contain valid canonical
UUIDs. Customer IDs are not unique and must not be used as the account key.
Missing checks covered absent values, whitespace-only values, and the
case-insensitive sentinels `null`, `none`, and `n/a`; none occurred.

| Category field | Value | Rows |
| --- | --- | ---: |
| account_type | current | 667 |
| account_type | savings | 667 |
| account_type | credit | 666 |
| spend_profile | low_spender | 667 |
| spend_profile | normal | 667 |
| spend_profile | high_spender | 666 |

Every `opened_at` is `2026-04-21 10:05:15 +0000 UTC`. Parse the explicit
offset and derive opening date in UTC, matching the generator's date rule.
The observed balance range is approximately 2.369045654467272 to
9998.688276765604; values are not restricted to two decimal places.

## Transaction coverage

All **10,000 transaction rows** have account IDs in the frozen account file:
zero orphan rows and zero orphan distinct IDs. Transactions reference
**1,973 distinct accounts**; **27 accounts have no transaction attempts**.
This is a many-to-one transaction-to-account join with no row multiplication
when the account key remains unique. Do not require every account to have a
transaction.

There are 10,000 unique transaction IDs, 9,000 payments, and 1,000 refund
attempts. Status counts are 9,000 completed, 700 pending, and 300 failed.
The existing generator's full `validate_dataset` function passed against the
verified frozen accounts, including dates/opening dates, exact amount format,
GBP, direction, statuses, and refund parent rules. Refund parents are distinct
completed payments on the same account with matching amount, currency, and
merchant category, and an earlier date.

## Current loader and dbt structure

The controlled Snowflake loader targets only
`BANKING_ANALYTICS.RAW.TRANSACTIONS`. It validates local hashes and the ten
transaction columns before connection, requires an empty compatible target,
uses bound exact Decimal amounts in an explicit transaction, checks unique
IDs and grouped counts/sums, and rolls back on failure. Blank payment parent
IDs become SQL NULL. It does not load accounts. The existing transaction DDL
has required columns except nullable `original_transaction_id`; uniqueness
and relationships are validated rather than assumed from SQL key declarations.

The active graph is `banking_raw.transactions → stg_transactions →
monthly_transaction_summary`. Staging preserves every attempt and status.
The monthly view filters completed attempts and groups by calendar month and
currency. Active tests cover transaction keys, required fields, vocabularies,
amount/date/direction rules, refund relationships, unique refund parents,
unique month/currency groups, and monthly reconciliation. An account
relationship test is currently absent because accounts are not an active source.

The project defaults to views, with `staging` and `marts` schema suffixes.
The README documents `DBT_AOIFE_STAGING` and `DBT_AOIFE_MARTS` for the current
target; actual output schema names depend on the target. Archived
`dim_accounts` and `fct_transactions` are outside active model paths and are
unfinished examples, not contracts to restore. In particular, their balance
status and transaction band derivations are not proposed here.

## Proposed raw accounts

Proposed relation: `BANKING_ANALYTICS.RAW.ACCOUNTS`, declared as
`source('banking_raw', 'accounts')`. **Grain: one row per frozen account ID**,
exactly 2,000 rows for this snapshot. Preserve all six source columns and their
order; no joins, aggregation, or silently chosen duplicate rows.

| Column | Proposed raw type | Required |
| --- | --- | --- |
| account_id | VARCHAR(36) | Yes |
| customer_id | VARCHAR(36) | Yes |
| account_type | VARCHAR(32) | Yes |
| spend_profile | VARCHAR(32) | Yes |
| balance | VARCHAR, preserving the original numeric text | Yes for this frozen input |
| opened_at | VARCHAR, preserving the original timestamp text | Yes |

Raw retention of balance is for source fidelity only, not a financial
measure. Keeping its text avoids rounding the synthetic source to monetary
precision. Opening timestamp conversion belongs in staging. A future loader
should verify the frozen manifest, validate shape/keys/categories and parsing,
and reconcile row/key counts without logging source records. Loader design
and implementation are deferred; this document does not create the relation.

## Proposed stg_accounts

**Grain: one row per raw account ID**, with the same 2,000 accounts and no
filtering or deduplication. Proposed materialization: view in staging.
Exact proposed columns:

| Column | Type | Meaning |
| --- | --- | --- |
| account_id | VARCHAR(36) | Unchanged natural account key |
| customer_id | VARCHAR(36) | Unchanged customer reference |
| account_type | VARCHAR(32) | Validated account vocabulary |
| spend_profile | VARCHAR(32) | Synthetic account generation label |
| opened_at | TIMESTAMP_TZ | Parsed opening instant with explicit offset |
| opened_date | DATE | UTC date derived from opened_at |

Reject invalid parsing rather than hiding it with an unchecked nullable cast.
Do not carry balance into this model.

## Proposed dim_accounts

**Grain: one row per account ID**, including the 27 accounts without attempts.
Proposed materialization: view in marts, selected from `stg_accounts`.
Exact columns and types: `account_id VARCHAR(36)`, `customer_id VARCHAR(36)`,
`account_type VARCHAR(32)`, `spend_profile VARCHAR(32)`,
`opened_at TIMESTAMP_TZ`, `opened_date DATE`.

Use `account_id` directly as the dimension key for this fixed dataset.
No surrogate key, effective-date range, or slowly changing dimension is
needed without account history. Retaining `customer_id` supports a future
customer dimension, but does not imply that a customer relationship has been
tested in this slice. Label spend profile as synthetic, not measured spending.

## Proposed fct_transactions

**Grain: one row per payment or refund attempt, uniquely identified by
transaction_id**, preserving all 10,000 rows and all three statuses.
Proposed materialization: view in marts, selected from `stg_transactions`.
Exact proposed columns:

| Column | Type | Meaning |
| --- | --- | --- |
| transaction_id | VARCHAR(36) | Unique attempt ID |
| account_id | VARCHAR(36) | Foreign key to dim_accounts |
| transaction_type | VARCHAR(32) | payment or refund |
| merchant_category | VARCHAR(64) | Source merchant category |
| amount | NUMBER(18,2) | Positive magnitude in source currency |
| direction | VARCHAR(16) | debit for payment, credit for refund |
| transaction_date | DATE | Attempt date |
| transaction_month | DATE | First calendar day of transaction_date's month |
| status | VARCHAR(32) | completed, pending, or failed |
| currency | VARCHAR(3) | GBP in v2 |
| original_transaction_id | VARCHAR(36), nullable | Parent payment for refunds; NULL for payments |

Account attributes remain in the dimension and are joined when reporting.
Do not filter completed rows in the fact, aggregate attempts, net refunds into
payments, or join refund children in a way that changes the fact grain.

## Fields excluded and why

- Exclude `balance` from staging, dimension, fact, and summaries. The account
  configuration generates it independently in the 0–10,000 range; it has no
  balance-as-of contract, ledger opening position, or transaction derivation.
  The v2 specification explicitly does not model balance reconciliation.
  Consequently neither balance changes nor overdraft/health labels can be
  inferred from it. Raw retention does not make it an analytical measure.
- Exclude the archived `balance_status` and `transaction_band`. The former
  depends on that unsupported balance; the latter adds arbitrary thresholds
  and drops important fields in the archived example.
- Exclude customer emails and other customer/card attributes: they are not
  account CSV columns and are unnecessary for this slice. Keep the opaque
  customer reference only; do not enrich with personal data.
- Exclude fabricated account currency, account status, closing dates, and
  history fields: none exists in the frozen account input. GBP is a
  transaction-level v2 assumption, not an observed account attribute.

## Proposed tests

Tests should expose bad source rows rather than repair them by deduplication
or by dropping unmatched transactions.

| Layer | Proposed checks |
| --- | --- |
| raw accounts | account_id unique and not_null; all six fields not_null plus nonblank checks; canonical UUIDs for both IDs; accepted account/spend categories; balance numeric parseability only; opened_at parseability and explicit timezone |
| stg_accounts | account_id unique; all six proposed columns not_null; account_type in current/savings/credit; spend_profile in low_spender/normal/high_spender; opened_date equals UTC date of opened_at; key set/count equal raw |
| dim_accounts | account_id unique; all six columns not_null; category tests; account_id relationship to stg_accounts plus reverse key-set/count reconciliation, preserving accounts without transactions |
| stg_transactions | retain current tests; add account_id relationship to stg_accounts.account_id; date must be on/after the related opened_date |
| fct_transactions | transaction_id unique; all columns not_null except original_transaction_id; account_id relationship to dim_accounts.account_id; original_transaction_id relationship to fct_transactions.transaction_id for non-NULL values; key-set/count and unchanged source-column reconciliation to stg_transactions; transaction_month matches transaction_date |
| future typed summary | unique (transaction_month, currency, account_type); all keys/measures not_null; accepted account types; exact count/amount reconciliation to the existing monthly summary |

Retain transaction vocabularies and positive-amount/payment-debit/refund-credit
rules in the fact contract. Parent IDs must be NULL for payments and required
for refunds; retain the stricter refund checks for completed payment parent,
same account/category/currency/full amount, strictly later date, and unique
refund parent across attempts. A generic relationship test alone is insufficient.
Do not test customer_id uniqueness or require transactions for every account.
A customer relationship test requires a future authoritative customer source.

For this frozen version, local acceptance also requires exactly 2,000 account
and 10,000 transaction rows, manifest hashes, and the documented v2 type/status
allocations. These are dataset-version checks, not perpetual production volume
thresholds. Standard Snowflake key declarations must not replace these checks.

## Monthly account-type reconciliation

Future `monthly_transaction_summary_by_account_type` has **one row per
(transaction_month, currency, account_type)** for completed attempts only.
Exact columns: `transaction_month DATE`, `currency VARCHAR(3)`,
`account_type VARCHAR(32)`, `transaction_count` (integer count),
`debit_total NUMBER(38,2)`, `credit_total NUMBER(38,2)`,
`net_outflow NUMBER(38,2)`.

Join the fact many-to-one to `dim_accounts` on account_id, after uniqueness
and relationship checks pass. Group completed rows by those three keys;
count every completed attempt, sum positive amounts separately by direction,
and calculate `net_outflow = debit_total - credit_total`. Refunds belong to
their own transaction month, not their parent's payment month. Keep currency
in the grain and never sum different currencies together.

Roll up the typed summary by month/currency, summing transaction_count,
debit_total, credit_total, and net_outflow. Full-outer-join that result to the
existing `monthly_transaction_summary` and require identical key sets and
exact equality of all four measures using NULL-safe comparisons, as the
existing `dbt/tests/monthly_reconciliation.sql` does. Use decimal arithmetic,
not floating tolerances or averages of group totals. Also reconcile joined
fact row counts to the completed fact count to catch dropped or multiplied
rows before aggregation. A left join during diagnostics makes unmatched
accounts visible; acceptance requires zero unmatched rows, not a silent
unknown bucket or inner-join loss.

Local completed counts by account type are current **3,055**, savings
**2,925**, and credit **3,020**, totaling **9,000**. The 700 pending and 300
failed attempts remain available in the fact but contribute nothing to these
monthly financial totals. Accounts without completed activity need not
produce summary rows. The existing summary remains the comparison baseline;
no change to its implementation is part of this documentation slice.

## Reproducing the local checks

Profiling used Python's csv.DictReader on the frozen accounts and actual v2
transactions, Counter for categories/statuses, sets for keys and duplicate
rows, Decimal for the balance range, UUID parsing for IDs, and SHA-256 for
byte verification. Coverage was calculated as follows (only counts need be
printed; never print raw account/customer records):

```python
account_ids = {row['account_id'] for row in account_rows}
used_ids = {row['account_id'] for row in transaction_rows}
orphan_rows = sum(row['account_id'] not in account_ids for row in transaction_rows)
unreferenced_accounts = len(account_ids - used_ids)
```

The imported generator functions `read_and_validate_accounts()` and
`validate_dataset(transaction_rows, accounts)` were called without invoking
the generation entry point. All reported counts and hashes are from this
local inspection. Live warehouse contents and future model execution remain
unverified; loaders, models, and tests are proposals only.
