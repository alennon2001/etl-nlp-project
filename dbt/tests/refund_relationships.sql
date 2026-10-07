with transactions as (
    select * from {{ ref('stg_transactions') }}
)
select r.transaction_id
from transactions r
left join transactions p
    on r.original_transaction_id = p.transaction_id
where r.transaction_type = 'refund'
  and (
      p.transaction_id is null
      or p.transaction_type is distinct from 'payment'
      or p.status is distinct from 'completed'
      or r.account_id is distinct from p.account_id
      or r.merchant_category is distinct from p.merchant_category
      or r.currency is distinct from p.currency
      or r.amount is distinct from p.amount
      or r.transaction_date <= p.transaction_date
  )
