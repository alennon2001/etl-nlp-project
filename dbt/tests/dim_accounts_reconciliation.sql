-- Compare complete rows and their multiplicities, including NULL parent links.
-- Grouped counts detect duplicates even when total row count is unchanged.
with expected as (
    select account_id, customer_id, account_type, spend_profile, opened_at, opened_date, count(*) as row_count
    from {{ ref('stg_accounts') }}
    group by account_id, customer_id, account_type, spend_profile, opened_at, opened_date
), actual as (
    select account_id, customer_id, account_type, spend_profile, opened_at, opened_date, count(*) as row_count
    from {{ ref('dim_accounts') }}
    group by account_id, customer_id, account_type, spend_profile, opened_at, opened_date
), missing_or_changed as (
    select * from expected except select * from actual
), extra_or_changed as (
    select * from actual except select * from expected
)
select 'missing_or_changed' as failure from missing_or_changed
union all
select 'extra_or_changed' as failure from extra_or_changed
