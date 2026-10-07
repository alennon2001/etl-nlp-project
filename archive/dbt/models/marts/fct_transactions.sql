select
    transaction_id,
    account_id,
    amount,
    transaction_type,
    transaction_date,

    case 
        when amount > 1000 then 'high_value'
        when amount > 100 then 'medium_value'
        else 'low_value'
    end as transaction_band

from {{ ref('stg_transactions') }}