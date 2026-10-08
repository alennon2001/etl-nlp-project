-- Full dataset period; completed attempts only, grouped by snapshot account type.
with totals as (
    select
        a.account_type,
        t.currency,
        count(*) as transaction_count,
        cast(sum(case when t.direction = 'debit' then t.amount else 0 end)
             as number(38, 2)) as debit_total,
        cast(sum(case when t.direction = 'credit' then t.amount else 0 end)
             as number(38, 2)) as credit_total
    from {{ ref('fct_transactions') }} t
    join {{ ref('dim_accounts') }} a on t.account_id = a.account_id
    where t.status = 'completed'
    group by a.account_type, t.currency
)
select
    account_type,
    currency,
    transaction_count,
    debit_total,
    credit_total,
    cast(debit_total - credit_total as number(38, 2)) as net_outflow
from totals
order by account_type, currency
