-- One row per frozen account snapshot; no attribute history or synthetic balance.
select
    account_id,
    customer_id,
    account_type,
    spend_profile,
    opened_at,
    opened_date
from {{ ref('stg_accounts') }}
