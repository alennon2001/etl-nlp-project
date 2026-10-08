This is the active dbt project for the first Snowflake transaction flow.

Frozen accounts ingestion and `stg_accounts` are now implemented alongside
the transaction flow. See [accounts setup and execution](../docs/accounts-ingestion.md)
for raw DDL, the validated loader, and the targeted staging build. Account
dimensions and transaction facts remain deferred.

### Current state

`banking_raw.transactions` → `stg_transactions` → `monthly_transaction_summary`
is implemented, with 27 generic and singular data tests. Staging preserves
transaction-attempt grain and all statuses; the summary uses completed rows
at month/currency grain. Both models are views.

The original starter examples and
unfinished banking marts are preserved in `../archive/dbt/models/`, outside
the configured resource paths. See the root README for the interactive
targeted build command and exact schema names. Offline parsing and SQL syntax
checks passed; database tests are pending the user-run build.


### Resources:
- Learn more about dbt [in the docs](https://docs.getdbt.com/docs/introduction)
- Check out [Discourse](https://discourse.getdbt.com/) for commonly asked questions and answers
- Join the [chat](https://community.getdbt.com/) on Slack for live discussions and support
- Find [dbt events](https://events.getdbt.com) near you
- Check out [the blog](https://blog.getdbt.com/) for the latest news on dbt's development and best practices
