-- User-supplied Snowflake analysis; relation names replaced with ref().
with account_activity as (
    select
        a.account_id,
        count(f.transaction_id) as attempt_count,
        sum(
            case when f.status = 'completed' then 1 else 0 end
        ) as completed_count
    from {{ ref('dim_accounts') }} as a
    left join {{ ref('fct_transactions') }} as f
        on a.account_id = f.account_id
    group by a.account_id
)
select
    case
        when attempt_count = 0 then 'No transaction attempts'
        when completed_count = 0 then 'Attempts, none completed'
        else 'At least one completed transaction'
    end as activity_group,
    count(*) as account_count
from account_activity
group by activity_group
order by activity_group
