-- Singular tests pass when they return zero failing rows.
select transaction_id
from {{ ref('stg_transactions') }}
where amount <= 0
   or not (
       (transaction_type = 'payment' and direction = 'debit')
       or (transaction_type = 'refund' and direction = 'credit')
   )
   or transaction_date < date '2026-04-21'
   or transaction_date > date '2026-09-30'
   or (transaction_type = 'payment' and original_transaction_id is not null)
