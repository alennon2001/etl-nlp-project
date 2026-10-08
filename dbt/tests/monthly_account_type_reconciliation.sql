with rolled_up as (
    select
        transaction_month,
        currency,
        sum(transaction_count) as transaction_count,
        sum(debit_total) as debit_total,
        sum(credit_total) as credit_total,
        sum(net_outflow) as net_outflow
    from {{ ref('monthly_transaction_summary_by_account_type') }}
    group by transaction_month, currency
), baseline as (
    select * from {{ ref('monthly_transaction_summary') }}
)
select
    coalesce(b.transaction_month, r.transaction_month) as transaction_month,
    coalesce(b.currency, r.currency) as currency
from baseline b
full outer join rolled_up r
    on b.transaction_month = r.transaction_month
   and b.currency = r.currency
where b.transaction_month is null
   or r.transaction_month is null
   or r.transaction_count is distinct from b.transaction_count
   or r.debit_total is distinct from b.debit_total
   or r.credit_total is distinct from b.credit_total
   or r.net_outflow is distinct from b.net_outflow
