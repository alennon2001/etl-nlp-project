# Banking v2 training dataset specification

Status: design agreed; generator and v2 output are not yet implemented.

## Frozen inputs

Preserve all four existing CSVs together in the ignored
`data_snapshots/banking-v1/` directory. `SHA256SUMS` records their byte-level
SHA-256 hashes. Never overwrite an existing snapshot: verify all four files
against the manifest instead. Source CSVs in `output/` remain untouched.
Customers, accounts and cards will retain their existing records and IDs.
The frozen accounts CSV is the generator's authoritative parent input.

## Training assumptions

- Generate exactly 10,000 transactions: 9,000 payments and 1,000 refund attempts.
- Dates are inclusive from 2026-04-21 through 2026-09-30, with no transaction
  before its account's opening date. All current accounts opened on April 21.
  Use the UTC opening date for this date-only exercise.
- Currency is GBP. Generate positive integer pence (100–50,000 for payments,
  retaining the original GBP 1–500 range), then write exactly two decimal
  places without converting through binary floating point.
- From the customer-account perspective, payments are debit and refunds credit.
- Overall statuses are exactly 9,000 completed, 700 pending and 300 failed.
  Pending and failed rows describe attempts, not settled financial activity.
- Each refund attempt references a distinct completed payment on the same
  account, copies its full amount, currency and merchant category, and has a
  strictly later date. At most one refund attempt per selected payment.
- Refunds may themselves be completed, pending or failed. No partial refunds,
  repeat refund attempts, currency conversion or balance reconciliation are
  modeled. These are synthetic learning assumptions, not production rules.
- Retain the existing merchant categories: groceries, travel, utilities and
  entertainment. Their distribution is not a business requirement.

## Planned CSV schema

One row represents one payment or refund attempt. Column order:

| Column | Representation / intended Snowflake type |
| --- | --- |
| transaction_id | Deterministic UUID string / VARCHAR(36) |
| account_id | Existing account UUID / VARCHAR(36) |
| transaction_type | payment or refund / VARCHAR(32) |
| merchant_category | Existing category vocabulary / VARCHAR(64) |
| amount | Positive GBP amount, exactly two decimals / NUMBER(18,2) |
| direction | debit or credit / VARCHAR(16) |
| transaction_date | YYYY-MM-DD / DATE |
| status | completed, pending or failed / VARCHAR(32) |
| currency | GBP / VARCHAR(3) |
| original_transaction_id | Blank for payments; parent UUID for refunds / VARCHAR(36) |

## Planned generation and publication

Use one Python generator with fixed seed 1234, accounts sorted by account_id,
explicit stable category ordering, and deterministic UUID5 transaction IDs
derived from a fixed namespace, dataset version, transaction type and ordinal.
Record the generator version, parameters and frozen input hashes alongside
the new output. Reproduction requires the same inputs and algorithm.

Assign payment statuses before selecting refund parents. Allocate payment
statuses as 8,100 completed, 630 pending and 270 failed; refund statuses as
900 completed, 70 pending and 30 failed. This preserves the exact overall
totals without relabeling eligible parents later. Select 1,000 distinct
completed payments dated before September 30; fail clearly if too few exist.
Choose each refund date between the day after its payment and September 30.

Write separately to `output/banking-v2/`, keeping old files intact and refusing
to overwrite existing final output. Validate the complete candidate before
publishing `transactions.csv`: row/type/status counts, unique deterministic
IDs, account references, date boundaries and opening dates, positive amounts
and two-decimal formatting, currency/direction rules, and every refund's
parent status, identity, amount, account, category, currency and later date.
Also verify that payment parent links are blank and refund parent IDs are
unique. Validate source account ID uniqueness before generation.

No Snowflake loading or dbt model execution is part of generation.
