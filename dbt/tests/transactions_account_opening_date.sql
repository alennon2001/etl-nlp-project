select t.transaction_id
from {{ ref('stg_transactions') }} t
join {{ ref('stg_accounts') }} a on t.account_id = a.account_id
where t.transaction_date < a.opened_date
