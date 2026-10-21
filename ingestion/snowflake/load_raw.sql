-- ============================================================================
-- load_raw.sql  |  Stage 5: copy one Bronze day from ADLS into POLARIS.RAW
--
-- Runs as the loader role, never ACCOUNTADMIN. Terraform built the stage and
-- the file format (infra/terraform/snowflake/landing.tf). This file creates
-- the RAW tables and runs COPY INTO.
--
-- Day loaded: 2026-10-16. The paths are written out by hand for now; Airflow
-- passes the date in Stage 7.
--
-- Expected, worked out in Stage 2 (seed 42) before running anything:
--   CUSTOMERS 3,000 · POLICIES 5,000 · CLAIMS 10,000 · CLAIM_PAYMENTS 11,203
--
-- Run one section at a time and check the result before the next.
-- ============================================================================

USE ROLE POLARIS_LOADER_ROLE;
USE WAREHOUSE POLARIS_WH_LOAD;
USE SCHEMA POLARIS.RAW;


-- ============================================================================
-- 1. CAN SNOWFLAKE SEE AZURE?
--
-- Expect the four part-00000.csv files and _SUCCESS, same sizes as the az
-- listing (791748 / 1593256 / 555250 / 567699 / 0). ADLS Gen2 has real
-- folders, so extra 0-byte rows ending in a folder name may show too. Fine.
--
-- A 403 or "not authorized" means the handshake isn't finished: the consent
-- URL wasn't accepted, the Azure role assignment is missing, or it's less
-- than a couple of minutes old.
-- ============================================================================
LIST @BRONZE_ADLS;


-- ============================================================================
-- 2. IS THE DAY COMPLETE?
--
-- Expect 1 row. polaris-ingest writes _SUCCESS last, so no marker means the
-- day may be half-written. Don't load it. (Airflow checks this in Stage 7.)
-- ============================================================================
LIST @BRONZE_ADLS/_markers/ingest_date=2026-10-16/;


-- ============================================================================
-- 3. RAW TABLES, every column VARCHAR
--
-- Bronze stores what arrived, it doesn't judge it. If premium were NUMBER,
-- one bad value would stop the whole file. dbt casts in staging.
--
-- Three load columns on every table: which file, which line, when loaded.
-- They let you trace any number back to the exact file and row.
--
-- The loader creates these, so it owns them. The dbt and analyst roles still
-- see them through the future grants from Stage 1.
--
-- Note: customers holds ssn and dob as plain text. A masking policy on those
-- two columns is on the Stage 7 list.
-- ============================================================================
CREATE TABLE IF NOT EXISTS CUSTOMERS (
    customer_id      VARCHAR,
    first_name       VARCHAR,
    last_name        VARCHAR,
    ssn              VARCHAR,
    dob              VARCHAR,
    email            VARCHAR,
    phone            VARCHAR,
    address_line1    VARCHAR,
    city             VARCHAR,
    province         VARCHAR,
    postal_code      VARCHAR,
    created_at       VARCHAR,
    updated_at       VARCHAR,
    _source_file     VARCHAR,
    _file_row_number NUMBER,
    _loaded_at       TIMESTAMP_LTZ
);

CREATE TABLE IF NOT EXISTS POLICIES (
    policy_id        VARCHAR,
    customer_id      VARCHAR,
    product_type     VARCHAR,
    effective_date   VARCHAR,
    expiry_date      VARCHAR,
    annual_premium   VARCHAR,
    coverage_limit   VARCHAR,
    status           VARCHAR,
    created_at       VARCHAR,
    updated_at       VARCHAR,
    _source_file     VARCHAR,
    _file_row_number NUMBER,
    _loaded_at       TIMESTAMP_LTZ
);

CREATE TABLE IF NOT EXISTS CLAIMS (
    claim_id         VARCHAR,
    claim_number     VARCHAR,
    policy_id        VARCHAR,
    customer_id      VARCHAR,
    product_type     VARCHAR,
    claim_type       VARCHAR,
    loss_date        VARCHAR,
    report_date      VARCHAR,
    claim_amount     VARCHAR,
    status           VARCHAR,
    is_fraud         VARCHAR,
    fraud_score      VARCHAR,
    adjuster_id      VARCHAR,
    created_at       VARCHAR,
    updated_at       VARCHAR,
    _source_file     VARCHAR,
    _file_row_number NUMBER,
    _loaded_at       TIMESTAMP_LTZ
);

CREATE TABLE IF NOT EXISTS CLAIM_PAYMENTS (
    payment_id       VARCHAR,
    claim_id         VARCHAR,
    payment_date     VARCHAR,
    payment_amount   VARCHAR,
    payment_type     VARCHAR,
    created_at       VARCHAR,
    _source_file     VARCHAR,
    _file_row_number NUMBER,
    _loaded_at       TIMESTAMP_LTZ
);

SHOW TABLES IN SCHEMA POLARIS.RAW;   -- expect 4, owner POLARIS_LOADER_ROLE


-- ============================================================================
-- 4. COPY INTO, one per table
--
-- FROM a folder path, not PATTERN. A pattern like '.*claim.*' would also
-- match claim_payments; the folder can only mean one table and one day.
--
-- ON_ERROR = ABORT_STATEMENT: one bad row stops that file and loads nothing
-- from it. Bronze should hold a whole file or none of it, never most of one.
--
-- Expect each to report 1 file LOADED with the row count from the top.
-- ============================================================================
COPY INTO CUSTOMERS
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/customers/year=2026/month=10/day=16/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;

COPY INTO POLICIES
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/policies/year=2026/month=10/day=16/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;

COPY INTO CLAIMS
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/claims/year=2026/month=10/day=16/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;

COPY INTO CLAIM_PAYMENTS
FROM (
    SELECT $1, $2, $3, $4, $5, $6,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/claim_payments/year=2026/month=10/day=16/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;


-- ============================================================================
-- 5. DID THE NUMBERS LAND?
--
-- Expect 3,000 / 5,000 / 10,000 / 11,203, and one source file per table.
-- ============================================================================
SELECT 'CUSTOMERS' AS table_name, COUNT(*) AS row_count, COUNT(DISTINCT _source_file) AS files FROM CUSTOMERS
UNION ALL SELECT 'POLICIES',       COUNT(*), COUNT(DISTINCT _source_file) FROM POLICIES
UNION ALL SELECT 'CLAIMS',         COUNT(*), COUNT(DISTINCT _source_file) FROM CLAIMS
UNION ALL SELECT 'CLAIM_PAYMENTS', COUNT(*), COUNT(DISTINCT _source_file) FROM CLAIM_PAYMENTS;


-- ============================================================================
-- 6. RUN SECTION 4 AGAIN, THEN SECTION 5
--
-- Expect "Copy executed with 0 files processed" four times, and the same
-- counts as before. Snowflake keeps load history per table for 64 days and
-- skips a file it has already loaded.
--
-- "0 files processed" can also mean the path matched nothing. The unchanged
-- counts in section 5 are what tell the two apart.
--
-- Know the limit: the history goes by file name AND contents. If a file is
-- rewritten with different bytes, Snowflake loads it again and the rows
-- double. That's why Stage 2's byte-identical re-run matters.
-- ============================================================================


-- ============================================================================
-- 7. THE AUDIT TRAIL
--
-- One row per file loaded into CLAIMS: when, how many rows, any errors.
-- This is where you look when someone asks "did last night's load run?"
-- ============================================================================
SELECT file_name, status, row_count, row_parsed, error_count, first_error_message, last_load_time
FROM TABLE(INFORMATION_SCHEMA.COPY_HISTORY(
    TABLE_NAME => 'POLARIS.RAW.CLAIMS',
    START_TIME => DATEADD(HOUR, -24, CURRENT_TIMESTAMP())
))
ORDER BY last_load_time DESC;
