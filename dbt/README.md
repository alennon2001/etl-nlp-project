This is the active dbt project for the first Snowflake transaction flow.

Frozen accounts ingestion and `stg_accounts` are now implemented alongside
the transaction flow. See [accounts setup and execution](../docs/accounts-ingestion.md)
for raw DDL, the validated loader, and the targeted staging build.
The first `dim_accounts` and `fct_transactions` views are implemented; see
[mart SQL, tests and build command](../docs/account-transaction-marts.md).

### Current state

`banking_raw.transactions` → `stg_transactions` → `monthly_transaction_summary`
is implemented. The original transaction flow has 27 generic and singular
data tests. Staging preserves
transaction-attempt grain and all statuses; the summary uses completed rows
at month/currency grain. Both models are views.

The original starter examples and
unfinished banking marts are preserved in `../archive/dbt/models/`, outside
the configured resource paths. See the root README for the interactive
targeted build command and exact schema names. Offline parsing and SQL syntax
checks passed. The saved October 8 staging build succeeded with all 32
selected database tests passing, including 13 accounts-related tests.
New mart database builds/tests remain pending. Offline parsing recognizes
66 total tests, including source, staging, mart and summary tests; the build
selection determines which execute.

`monthly_transaction_summary_by_account_type` joins completed fact attempts
to frozen account types. Its join-cardinality and rollup reconciliation tests
protect the unchanged monthly summary baseline. See
[account-type summary and full-project build](../docs/monthly-account-type-summary.md).
The saved October 8 mart build succeeded: four models and all 47 selected
tests passed, including all eight dimension/fact tests. The new account-type
summary has only been checked offline; its database build remains pending.


### Resources:
- Learn more about dbt [in the docs](https://docs.getdbt.com/docs/introduction)
- Check out [Discourse](https://discourse.getdbt.com/) for commonly asked questions and answers
- Join the [chat](https://community.getdbt.com/) on Slack for live discussions and support
- Find [dbt events](https://events.getdbt.com) near you
- Check out [the blog](https://blog.getdbt.com/) for the latest news on dbt's development and best practices
