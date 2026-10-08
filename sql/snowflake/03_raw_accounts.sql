-- Run separately in a Snowflake worksheet before the interactive accounts load.
-- IF NOT EXISTS preserves existing tables/data; the loader refuses incompatibility.
USE ROLE BANKING_DEVELOPER;
USE WAREHOUSE BANKING_DEV_WH;

CREATE SCHEMA IF NOT EXISTS BANKING_ANALYTICS.RAW;

CREATE TABLE IF NOT EXISTS BANKING_ANALYTICS.RAW.ACCOUNTS (
    account_id    VARCHAR(36) NOT NULL,
    customer_id   VARCHAR(36) NOT NULL,
    account_type  VARCHAR(32) NOT NULL,
    spend_profile VARCHAR(32) NOT NULL,
    balance       VARCHAR(64) NOT NULL,
    opened_at     VARCHAR(64) NOT NULL
);

-- Frozen input maximum lengths: IDs 36, type 7, profile 12, balance 18,
-- opening timestamp 29. Text preserves balance precision and timestamp bytes.
-- Balance is independently generated, has no as-of/ledger meaning, and is
-- excluded from analytical models. It is not a monetary reconciliation target.
-- Uniqueness is checked by the loader/dbt, not an unenforced key declaration.
