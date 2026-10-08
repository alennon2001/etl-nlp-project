-- One row per transaction attempt, preserving every status and parent link.
select
    transaction_id,
    account_id,
    transaction_type,
    merchant_category,
    amount,
    direction,
    transaction_date,
    status,
    currency,
    original_transaction_id
from {{ ref('stg_transactions') }}
