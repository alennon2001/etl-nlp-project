-- Exactly one account match per fact attempt; catch loss and multiplication
-- separately, even if their effects cancel in a total count.
select t.transaction_id
from {{ ref('fct_transactions') }} t
left join {{ ref('dim_accounts') }} a on t.account_id = a.account_id
group by t.transaction_id
having count(a.account_id) <> 1
