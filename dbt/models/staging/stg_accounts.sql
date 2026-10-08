-- One row per frozen account, including accounts without transactions.
-- Strict explicit parsing preserves the instant; balance stays in raw only.
with typed as (
    select
        cast(account_id as varchar(36)) as account_id,
        cast(customer_id as varchar(36)) as customer_id,
        cast(account_type as varchar(32)) as account_type,
        cast(spend_profile as varchar(32)) as spend_profile,
        to_timestamp_tz(opened_at, 'YYYY-MM-DD HH24:MI:SS TZHTZM "UTC"') as opened_at
    from {{ source('banking_raw', 'accounts') }}
)
select
    account_id,
    customer_id,
    account_type,
    spend_profile,
    cast(opened_at as timestamp_tz) as opened_at,
    cast(convert_timezone('UTC', opened_at) as date) as opened_date
from typed
