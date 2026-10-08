-- Compare complete rows and their multiplicities, including NULL parent links.
-- Grouped counts detect duplicates even when total row count is unchanged.
with expected as (
    select transaction_id, account_id, transaction_type, merchant_category, amount, direction, transaction_date, status, currency, original_transaction_id, count(*) as row_count
    from {{ ref('stg_transactions') }}
    group by transaction_id, account_id, transaction_type, merchant_category, amount, direction, transaction_date, status, currency, original_transaction_id
), actual as (
    select transaction_id, account_id, transaction_type, merchant_category, amount, direction, transaction_date, status, currency, original_transaction_id, count(*) as row_count
    from {{ ref('fct_transactions') }}
    group by transaction_id, account_id, transaction_type, merchant_category, amount, direction, transaction_date, status, currency, original_transaction_id
), missing_or_changed as (
    select * from expected except select * from actual
), extra_or_changed as (
    select * from actual except select * from expected
)
select 'missing_or_changed' as failure from missing_or_changed
union all
select 'extra_or_changed' as failure from extra_or_changed
