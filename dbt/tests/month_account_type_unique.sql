select transaction_month, currency, account_type, count(*) as summary_rows
from {{ ref('monthly_transaction_summary_by_account_type') }}
group by transaction_month, currency, account_type
having count(*) > 1
