select
    customer_id,
    email,
    created_at,

    -- customer lifecycle flags
    case 
        when created_at > current_date - interval '30 days' then 'new'
        when created_at > current_date - interval '180 days' then 'active'
        else 'established'
    end as customer_segment

from {{ ref('stg_customers') }}