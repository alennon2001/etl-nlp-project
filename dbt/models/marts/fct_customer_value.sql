select
    customer_id,
    total_spend,
    total_income,

    (total_spend * 0.02) as estimated_revenue,

    case 
        when total_spend > 10000 then 'high_value_customer'
        when total_spend > 2000 then 'medium_value_customer'
        else 'low_value_customer'
    end as value_segment

from {{ ref('fct_customer_activity') }}