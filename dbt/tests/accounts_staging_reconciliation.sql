-- Bidirectional row comparison plus counts exposes missing/extra/changed rows.
with expected as (
    select
        account_id, customer_id, account_type, spend_profile,
        to_timestamp_tz(opened_at, 'YYYY-MM-DD HH24:MI:SS TZHTZM "UTC"') as opened_at
    from {{ source('banking_raw', 'accounts') }}
), actual as (
    select account_id, customer_id, account_type, spend_profile, opened_at
    from {{ ref('stg_accounts') }}
), missing as (
    select * from expected except select * from actual
), extra as (
    select * from actual except select * from expected
)
select 'missing' as failure from missing
union all
select 'extra' as failure from extra
union all
select 'count' as failure
where (select count(*) from expected) <> (select count(*) from actual)
