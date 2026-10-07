select original_transaction_id, count(*) as refund_attempts
from {{ ref('stg_transactions') }}
where transaction_type = 'refund'
group by original_transaction_id
having count(*) > 1
