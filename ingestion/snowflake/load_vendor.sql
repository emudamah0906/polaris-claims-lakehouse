-- ============================================================================
-- load_vendor.sql  |  Stage 7: COPY one day of the vendor's repair estimates into RAW
--
-- Run by Airflow as POLARIS_SVC / POLARIS_LOADER_ROLE:
--   scripts/sf.sh POLARIS_LOADER_ROLE POLARIS_WH_LOAD -f ingestion/snowflake/load_vendor.sql \
--       -D year=2026 -D month=10 -D day=19
--
-- Two sources land each day:
--   claims_system/<table>/...           the incremental extract (Stage 2b)
--   vendor/autobody/repair_estimates/...   the vendor file ADF copied (Stage 2c)
--
-- RAW is append-only. A changed claim arrives again in a later day's extract
-- and is appended; staging keeps the newest version per key. A file already
-- loaded is skipped by COPY's load history, so a retry loads nothing twice.
-- ============================================================================

-- The vendor's table. ADF adds vendor_file and vendor_ingest_date on the way
-- into Bronze; our own three load columns come after them.
CREATE TABLE IF NOT EXISTS REPAIR_ESTIMATES (
    estimate_id        VARCHAR,
    claim_id           VARCHAR,
    shop_id            VARCHAR,
    estimate_date      VARCHAR,
    parts_amount       VARCHAR,
    labour_amount      VARCHAR,
    total_amount       VARCHAR,
    currency           VARCHAR,
    vendor_file        VARCHAR,
    vendor_ingest_date VARCHAR,
    _source_file       VARCHAR,
    _file_row_number   NUMBER,
    _loaded_at         TIMESTAMP_LTZ
);

COPY INTO REPAIR_ESTIMATES
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/vendor/autobody/repair_estimates/year=<% year %>/month=<% month %>/day=<% day %>/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;
