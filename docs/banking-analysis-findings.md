# Banking analysis findings

## Source and period

These are **user-supplied Snowflake query results**, supplied on October 8,
2026. They were not independently executed or verified against Snowflake by
the agent. The user subsequently supplied the exact Snowflake SQL for the active-account
and activity-group analyses. Those saved files preserve its expressions,
aliases, labels and ordering, replacing qualified relations with ref().
The first completed-totals query remains the saved implementation; its exact
original Snowflake SQL has not been supplied. The queries use the inspected dim_accounts and
fct_transactions columns and cover the complete banking-v2 dataset:
April 21 through September 30, 2026, inclusive. They have no additional date
filter; results will change if the underlying dataset period changes.

## Completed activity by account type

| Frozen account type | Currency | Active accounts | Completed transactions | Net outflow | Net outflow per active account |
| --- | --- | ---: | ---: | ---: | ---: |
| credit | GBP | 651 | 3,020 | 605,049.44 | 929.42 |
| current | GBP | 651 | 3,055 | 594,508.41 | 913.22 |
| savings | GBP | 658 | 2,925 | 585,911.46 | 890.44 |

An active account has at least one completed transaction during the dataset
period. The denominator is COUNT(DISTINCT account_id) among completed rows,
within each account-type/currency group; accounts with only pending/failed
attempts or no attempts are excluded. This is net outflow divided by active
accounts, rounded to two decimal places, not an average transaction amount
or a monthly average. In a future multi-currency dataset an account can be
active in more than one currency, so currency-level account counts cannot
necessarily be summed to a distinct overall account count.

Completed transaction count includes completed payment and refund attempts.
Debit total sums positive debit amounts, credit total sums positive credit
amounts, and net outflow equals debit total minus credit total from the
customer-account perspective. Pending and failed attempts do not contribute.
Refunds count separately and use their own dates. Debit/credit results were
not supplied here; the saved first query returns both without inventing values.

The supplied rows sum arithmetically to 1,960 active accounts, 9,000 completed
transactions and GBP 1,785,469.31 net outflow. These arithmetic observations
are not a new warehouse reconciliation or database query execution.

Saved queries:

- [Completed counts and monetary totals](../dbt/analyses/completed_transactions_by_account_type.sql)
- [Net outflow per active account](../dbt/analyses/net_outflow_per_active_account.sql)

Both join fact account_id to the unique dimension account_id, filter completed
attempts, and group by frozen account_type and transaction currency. The first
query casts debit/credit totals and net outflow to NUMBER(38,2). The supplied
active-account query sums signed amounts directly, divides by active_accounts
using Snowflake same-select aliases, and rounds the ratio to two decimal
places. It orders by that ratio descending and retains Snowflake-derived
numeric types without additional casts.

## Account activity groups

| Activity group | Definition | Accounts |
| --- | --- | ---: |
| At least one completed transaction | At least one completed transaction | 1,960 |
| Attempts, none completed | At least one attempt, but none completed | 13 |
| No transaction attempts | No transaction attempts | 27 |
| Total | All frozen accounts | 2,000 |

[Account activity groups](../dbt/analyses/account_activity_groups.sql) starts
from every dimension account and LEFT JOINs all fact attempts. It does not
filter status in WHERE: doing so would remove accounts without completed
activity. A per-account aggregation counts matched transaction IDs and uses
a conditional sum for completed attempts, then assigns mutually exclusive
groups before counting accounts.

COUNT(transaction_id) ignores the NULL transaction ID in an unmatched LEFT
JOIN row and therefore correctly gives zero attempts. COUNT(*) at that step
would count the unmatched account row as one and misclassify no-attempt
accounts. COUNT(*) is appropriate in the final grouped query because the
classified input has exactly one row per account; it is also appropriate for
completed counts after the validated many-to-one inner join.

## Interpretation limits

These are synthetic learning data, not evidence about real banking customers
or performance. Account types are frozen snapshot attributes, not their
historically effective values at transaction time. Spend profile is a
generation label. Source balance was generated independently, is excluded
from analytical models, and cannot reconcile these transaction flows to an
account balance. Currency is GBP only; no currency conversion is modeled.
Refunds are full-amount synthetic attempts under the v2 parent-link rules.
The partial April and September dataset window does not support annualizing
these results or treating them as comparable full monthly periods.

## Saved dbt analyses and offline checks

`dbt_project.yml` declares analysis-paths as analyses. These files are saved
queries with ref() model references, not additional models automatically
built or executed by dbt build. They do not create views or tables. They can
be compiled for subsequent manual query execution; model build commands
continue to build the six active models and their tests.

Offline dbt parsing and Snowflake-dialect SQL syntax checks passed for the
initial saved queries, with local fixtures covering their definitions. After
matching the supplied SQL, Snowflake-dialect syntax and ref() dependency checks
were repeated. The active-account query uses Snowflake same-select aliases,
so SQLite cannot execute that exact projection directly.
Those checks validate the saved logic, not the supplied Snowflake results.
No Snowflake connection, commit or push occurred.
