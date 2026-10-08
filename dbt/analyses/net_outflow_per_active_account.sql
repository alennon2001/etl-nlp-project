-- User-supplied Snowflake analysis; relation names replaced with ref().
select
    a.account_type,
    f.currency,
    count(distinct f.account_id) as active_accounts,
    count(*) as completed_transaction_count,
    sum(
        case
            when f.direction = 'debit' then f.amount
            when f.direction = 'credit' then -f.amount
        end
    ) as net_outflow,
    round(
        net_outflow / nullif(active_accounts, 0),
        2
    ) as net_outflow_per_active_account
from {{ ref('fct_transactions') }} as f
inner join {{ ref('dim_accounts') }} as a
    on f.account_id = a.account_id
where f.status = 'completed'
group by a.account_type, f.currency
order by net_outflow_per_active_account desc
