-- Keep every status and one row per transaction attempt. Do not deduplicate.
select
    cast(transaction_id as varchar(36)) as transaction_id,
    cast(account_id as varchar(36)) as account_id,
    cast(transaction_type as varchar(32)) as transaction_type,
    cast(merchant_category as varchar(64)) as merchant_category,
    cast(amount as number(18, 2)) as amount,
    cast(direction as varchar(16)) as direction,
    cast(transaction_date as date) as transaction_date,
    cast(status as varchar(32)) as status,
    cast(currency as varchar(3)) as currency,
    cast(nullif(original_transaction_id, '') as varchar(36)) as original_transaction_id
from {{ source('banking_raw', 'transactions') }}
