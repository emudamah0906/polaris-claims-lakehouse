# ── Roles (RBAC) ──────────────────────────────────────────────────────────────
# Three roles, each with only the grants its job needs (least privilege):
#
#   POLARIS_LOADER_ROLE   writes RAW only            (COPY INTO from Airflow)
#   POLARIS_DBT_ROLE      reads RAW, builds the rest (dbt build)
#   POLARIS_ANALYST_ROLE  reads STAGING + MARTS      (BI, Streamlit, ad-hoc)
#
# Each table grant comes in two parts: "all" covers tables that exist today,
# "future" covers tables created later. Without "future", every new dbt model
# would be invisible to analysts until someone re-ran the grant.

# for_each needs every key at plan time. Schema names are only known after
# apply, so the keys are fixed words written here and the names sit in the values.
locals {
  raw = snowflake_schema.raw.fully_qualified_name
  analyst_read = {
    staging = snowflake_schema.staging.fully_qualified_name
    marts   = snowflake_schema.marts.fully_qualified_name
  }
  dbt_targets = {
    staging      = snowflake_schema.staging.fully_qualified_name
    intermediate = snowflake_schema.intermediate.fully_qualified_name
    marts        = snowflake_schema.marts.fully_qualified_name
  }
}

resource "snowflake_account_role" "loader" {
  name    = "POLARIS_LOADER_ROLE"
  comment = "COPY INTO RAW from the Bronze stage"
}

resource "snowflake_account_role" "dbt" {
  name    = "POLARIS_DBT_ROLE"
  comment = "dbt build: read RAW, create/replace STAGING, INTERMEDIATE, MARTS"
}

resource "snowflake_account_role" "analyst" {
  name    = "POLARIS_ANALYST_ROLE"
  comment = "Read-only on STAGING + MARTS"
}

# Hang all three under SYSADMIN, so admins can see and manage what they create.
# Snowflake's own recommendation; otherwise objects end up orphaned from the
# admin hierarchy.
resource "snowflake_grant_account_role" "to_sysadmin" {
  for_each = {
    loader  = snowflake_account_role.loader.name
    dbt     = snowflake_account_role.dbt.name
    analyst = snowflake_account_role.analyst.name
  }
  role_name        = each.value
  parent_role_name = "SYSADMIN"
}

# ── Every role: USAGE on the database ─────────────────────────────────────────

resource "snowflake_grant_privileges_to_account_role" "usage_db" {
  for_each = {
    loader  = snowflake_account_role.loader.name
    dbt     = snowflake_account_role.dbt.name
    analyst = snowflake_account_role.analyst.name
  }
  account_role_name = each.value
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.polaris.name
  }
}

# ── Warehouses: loader gets LOAD, the other two share TRANSFORM ───────────────

resource "snowflake_grant_privileges_to_account_role" "usage_wh" {
  for_each = {
    loader  = { role = snowflake_account_role.loader.name, wh = snowflake_warehouse.load.name }
    dbt     = { role = snowflake_account_role.dbt.name, wh = snowflake_warehouse.transform.name }
    analyst = { role = snowflake_account_role.analyst.name, wh = snowflake_warehouse.transform.name }
  }
  account_role_name = each.value.role
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = each.value.wh
  }
}

# ── Loader: write RAW ─────────────────────────────────────────────────────────
# CREATE TABLE so the load DAG can create RAW tables on first run.
# CREATE STAGE / file formats arrive with Stage 5.

resource "snowflake_grant_privileges_to_account_role" "loader_raw_schema" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE", "CREATE TABLE"]
  on_schema {
    schema_name = local.raw
  }
}

resource "snowflake_grant_privileges_to_account_role" "loader_raw_tables_all" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["SELECT", "INSERT"]
  on_schema_object {
    all {
      object_type_plural = "TABLES"
      in_schema          = local.raw
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "loader_raw_tables_future" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["SELECT", "INSERT"]
  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = local.raw
    }
  }
}

# ── dbt: read RAW, build STAGING / INTERMEDIATE / MARTS ───────────────────────

resource "snowflake_grant_privileges_to_account_role" "dbt_raw_schema" {
  account_role_name = snowflake_account_role.dbt.name
  privileges        = ["USAGE"]
  on_schema {
    schema_name = local.raw
  }
}

resource "snowflake_grant_privileges_to_account_role" "dbt_raw_tables_all" {
  account_role_name = snowflake_account_role.dbt.name
  privileges        = ["SELECT"]
  on_schema_object {
    all {
      object_type_plural = "TABLES"
      in_schema          = local.raw
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "dbt_raw_tables_future" {
  account_role_name = snowflake_account_role.dbt.name
  privileges        = ["SELECT"]
  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = local.raw
    }
  }
}

# dbt creates the objects in these schemas, so it owns them and needs no
# per-table grants here.
resource "snowflake_grant_privileges_to_account_role" "dbt_targets" {
  for_each          = local.dbt_targets
  account_role_name = snowflake_account_role.dbt.name
  privileges        = ["USAGE", "CREATE TABLE", "CREATE VIEW", "MODIFY", "MONITOR"]
  on_schema {
    schema_name = each.value
  }
}

# ── Analyst: read STAGING + MARTS ─────────────────────────────────────────────
# Staging models are views and marts are tables, so grant SELECT on both kinds.

resource "snowflake_grant_privileges_to_account_role" "analyst_schemas" {
  for_each          = local.analyst_read
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["USAGE"]
  on_schema {
    schema_name = each.value
  }
}

locals {
  # Every (schema, object type) pair the analyst reads: 2 schemas x 2 types.
  # Keys like "staging_views" come from the fixed words above, so plan knows them.
  analyst_select = {
    for pair in setproduct(keys(local.analyst_read), ["TABLES", "VIEWS"]) :
    "${pair[0]}_${lower(pair[1])}" => { schema = local.analyst_read[pair[0]], type = pair[1] }
  }
}

resource "snowflake_grant_privileges_to_account_role" "analyst_select_all" {
  for_each          = local.analyst_select
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["SELECT"]
  on_schema_object {
    all {
      object_type_plural = each.value.type
      in_schema          = each.value.schema
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "analyst_select_future" {
  for_each          = local.analyst_select
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["SELECT"]
  on_schema_object {
    future {
      object_type_plural = each.value.type
      in_schema          = each.value.schema
    }
  }
}
