-- One row per month/currency with completed transactions only.
with completed as (
    select
        cast(date_trunc('month', transaction_date) as date) as transaction_month,
        currency,
        direction,
        amount
    from {{ ref('stg_transactions') }}
    where status = 'completed'
),
monthly as (
    select
        transaction_month,
        currency,
        count(*) as transaction_count,
        cast(sum(case when direction = 'debit' then amount else 0 end)
             as number(38, 2)) as debit_total,
        cast(sum(case when direction = 'credit' then amount else 0 end)
             as number(38, 2)) as credit_total
    from completed
    group by transaction_month, currency
)
select
    transaction_month,
    currency,
    transaction_count,
    debit_total,
    credit_total,
    cast(debit_total - credit_total as number(38, 2)) as net_outflow
from monthly
