-- Frozen account types; one row per completed month/currency/account_type.
with completed as (
    select
        cast(date_trunc('month', t.transaction_date) as date) as transaction_month,
        t.currency,
        a.account_type,
        t.direction,
        t.amount
    from {{ ref('fct_transactions') }} t
    join {{ ref('dim_accounts') }} a on t.account_id = a.account_id
    where t.status = 'completed'
), monthly as (
    select
        transaction_month,
        currency,
        account_type,
        count(*) as transaction_count,
        cast(sum(case when direction = 'debit' then amount else 0 end)
             as number(38, 2)) as debit_total,
        cast(sum(case when direction = 'credit' then amount else 0 end)
             as number(38, 2)) as credit_total
    from completed
    group by transaction_month, currency, account_type
)
select
    transaction_month,
    currency,
    account_type,
    transaction_count,
    debit_total,
    credit_total,
    cast(debit_total - credit_total as number(38, 2)) as net_outflow
from monthly
