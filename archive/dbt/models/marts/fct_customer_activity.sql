select
    c.customer_id,
    count(t.transaction_id) as transaction_count,
    sum(case when t.transaction_type = 'debit' then t.amount else 0 end) as total_spend,
    sum(case when t.transaction_type = 'credit' then t.amount else 0 end) as total_income,

    case
        when count(t.transaction_id) = 0 then 'dormant'
        when count(t.transaction_id) < 5 then 'low_activity'
        else 'active'
    end as activity_status

from {{ ref('stg_customers') }} c
left join {{ ref('stg_accounts') }} a
    on c.customer_id = a.customer_id
left join {{ ref('stg_transactions') }} t
    on a.account_id = t.account_id

group by c.customer_id