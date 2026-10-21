# ── Stage 5: Snowflake reads the ADLS bronze container ───────────────────────
# Three objects, then two grants:
#
#   storage integration   Snowflake's identity in Azure. Holds no secret.
#   file format           how to read the CSVs
#   external stage        a pointer at the bronze container. Files stay in Azure
#
# The integration is half of a handshake. After apply, someone opens
# azure_consent_url (see outputs.tf) and the Azure stack gives Snowflake's app
# read access to the container. Until then, LIST on the stage fails with 403.

locals {
  # Snowflake wants the blob endpoint here, even for ADLS Gen2 (not dfs).
  bronze_url = "azure://${var.adls_account}.blob.core.windows.net/bronze/"
}

resource "snowflake_storage_integration" "adls_bronze" {
  name             = "POLARIS_ADLS_BRONZE"
  type             = "EXTERNAL_STAGE"
  storage_provider = "AZURE"
  azure_tenant_id  = var.azure_tenant_id
  enabled          = true

  # A whitelist. Even a stage someone writes later can't point this
  # integration at any other container.
  storage_allowed_locations = [local.bronze_url]

  comment = "Reads the ADLS bronze container. No key or SAS token stored"
}

# Bronze keeps the data as it arrived, so this only says how to split the file.
# Types are not checked here: every RAW column is VARCHAR and dbt casts later.
resource "snowflake_file_format" "bronze_csv" {
  name                         = "BRONZE_CSV"
  database                     = snowflake_database.polaris.name
  schema                       = snowflake_schema.raw.name
  format_type                  = "CSV"
  skip_header                  = 1
  field_optionally_enclosed_by = "\""
  comment                      = "polaris-ingest CSVs: header row, comma, optional double quotes"
}

# No file_format on the stage itself. Each COPY INTO names BRONZE_CSV, so the
# load says exactly how it reads the file.
resource "snowflake_stage" "bronze" {
  name                = "BRONZE_ADLS"
  database            = snowflake_database.polaris.name
  schema              = snowflake_schema.raw.name
  url                 = local.bronze_url
  storage_integration = snowflake_storage_integration.adls_bronze.name
  comment             = "ADLS bronze container, read through POLARIS_ADLS_BRONZE"
}

# ── Loader: use the stage and the file format ─────────────────────────────────
# The loader needs no grant on the integration. Only whoever creates a stage
# does, and Terraform did that as ACCOUNTADMIN.

resource "snowflake_grant_privileges_to_account_role" "loader_stage" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE"]
  on_schema_object {
    object_type = "STAGE"
    object_name = snowflake_stage.bronze.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "loader_file_format" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE"]
  on_schema_object {
    object_type = "FILE FORMAT"
    object_name = snowflake_file_format.bronze_csv.fully_qualified_name
  }
}
