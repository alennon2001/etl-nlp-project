-- Run separately in a Snowflake worksheet before the interactive Python load.
-- Existing tables/data are preserved. The loader checks schema compatibility.
USE ROLE BANKING_DEVELOPER;
USE WAREHOUSE BANKING_DEV_WH;

CREATE SCHEMA IF NOT EXISTS BANKING_ANALYTICS.RAW;

CREATE TABLE IF NOT EXISTS BANKING_ANALYTICS.RAW.TRANSACTIONS (
    transaction_id        VARCHAR(36) NOT NULL,
    account_id            VARCHAR(36) NOT NULL,
    transaction_type      VARCHAR(32) NOT NULL,
    merchant_category     VARCHAR(64) NOT NULL,
    amount                NUMBER(18,2) NOT NULL,
    direction             VARCHAR(16) NOT NULL,
    transaction_date      DATE NOT NULL,
    status                VARCHAR(32) NOT NULL,
    currency              VARCHAR(3) NOT NULL,
    original_transaction_id VARCHAR(36)
);

-- Empty payment parent fields load as SQL NULL; refunds have a parent UUID.
-- Uniqueness and refund integrity are validated by Python, not assumed from
-- unenforced primary/foreign key declarations on a standard Snowflake table.
