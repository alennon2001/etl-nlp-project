with expected as (
    select
        cast(date_trunc('month', transaction_date) as date) as transaction_month,
        currency,
        count(*) as transaction_count,
        sum(case when direction = 'debit' then amount else 0 end) as debit_total,
        sum(case when direction = 'credit' then amount else 0 end) as credit_total
    from {{ ref('stg_transactions') }}
    where status = 'completed'
    group by 1, 2
),
actual as (
    select * from {{ ref('monthly_transaction_summary') }}
)
select
    coalesce(e.transaction_month, a.transaction_month) as transaction_month,
    coalesce(e.currency, a.currency) as currency
from expected e
full outer join actual a
    on e.transaction_month = a.transaction_month
   and e.currency = a.currency
where e.transaction_month is null
   or a.transaction_month is null
   or a.transaction_count is distinct from e.transaction_count
   or a.debit_total is distinct from e.debit_total
   or a.credit_total is distinct from e.credit_total
   or a.net_outflow is distinct from (e.debit_total - e.credit_total)
