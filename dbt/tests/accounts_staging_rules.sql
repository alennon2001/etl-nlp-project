select account_id
from {{ ref('stg_accounts') }}
where not regexp_like(account_id, '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
   or not regexp_like(customer_id, '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
   or opened_date is distinct from cast(convert_timezone('UTC', opened_at) as date)
