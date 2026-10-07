select
    account_id,
    customer_id,
    balance,

    case 
        when balance < 0 then 'overdrawn'
        when balance = 0 then 'zero_balance'
        when balance < 1000 then 'low_balance'
        else 'healthy'
    end as balance_status

from {{ ref('stg_accounts') }}