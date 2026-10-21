-- ============================================================================
-- load_claims_system.sql  |  Stage 7: COPY one day of claims-system extracts into RAW
--
-- Run by Airflow as POLARIS_SVC / POLARIS_LOADER_ROLE:
--   scripts/sf.sh POLARIS_LOADER_ROLE POLARIS_WH_LOAD -f ingestion/snowflake/load_claims_system.sql \
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

COPY INTO CUSTOMERS
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/claims_system/customers/year=<% year %>/month=<% month %>/day=<% day %>/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;

COPY INTO POLICIES
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/claims_system/policies/year=<% year %>/month=<% month %>/day=<% day %>/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;

COPY INTO CLAIMS
FROM (
    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/claims_system/claims/year=<% year %>/month=<% month %>/day=<% day %>/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;

COPY INTO CLAIM_PAYMENTS
FROM (
    SELECT $1, $2, $3, $4, $5, $6,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @BRONZE_ADLS/claims_system/claim_payments/year=<% year %>/month=<% month %>/day=<% day %>/
)
FILE_FORMAT = (FORMAT_NAME = 'POLARIS.RAW.BRONZE_CSV')
ON_ERROR = ABORT_STATEMENT;
