select transaction_month, currency, count(*) as summary_rows
from {{ ref('monthly_transaction_summary') }}
group by transaction_month, currency
having count(*) > 1
