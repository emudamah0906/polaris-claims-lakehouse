# ── Database + schemas ────────────────────────────────────────────────────────
# One database, one schema per layer. RAW is the Bronze landing zone in
# Snowflake; dbt owns everything after it.

resource "snowflake_database" "polaris" {
  name                        = var.database_name
  comment                     = "P&C claims lakehouse, managed by Terraform"
  data_retention_time_in_days = 7 # time travel: lets us UNDROP a table for a week
}

resource "snowflake_schema" "raw" {
  database = snowflake_database.polaris.name
  name     = "RAW"
  comment  = "Bronze landing. Loaded by COPY INTO from the ADLS external stage (Stage 5)"
}

resource "snowflake_schema" "staging" {
  database = snowflake_database.polaris.name
  name     = "STAGING"
  comment  = "dbt staging views: renames, casts, light filters"
}

resource "snowflake_schema" "intermediate" {
  database = snowflake_database.polaris.name
  name     = "INTERMEDIATE"
  comment  = "dbt intermediate models (mostly ephemeral)"
}

resource "snowflake_schema" "marts" {
  database = snowflake_database.polaris.name
  name     = "MARTS"
  comment  = "dbt marts: claims, fraud, finance, actuarial"
}

# ── Warehouses ────────────────────────────────────────────────────────────────
# Two warehouses split by workload. A slow dbt build can't hold up a load, and a
# big backfill can't slow analysts. Same cost: billing is per second per
# warehouse and each one suspends on its own.

resource "snowflake_warehouse" "transform" {
  name                = var.warehouse_transform
  warehouse_size      = "XSMALL"
  auto_suspend        = 60   # seconds idle before it stops billing
  auto_resume         = true # wakes up on the next query
  initially_suspended = true # costs nothing until first used
  resource_monitor    = snowflake_resource_monitor.guardrail.fully_qualified_name
  comment             = "dbt build, Great Expectations, Streamlit reads"
}

resource "snowflake_warehouse" "load" {
  name                = var.warehouse_load
  warehouse_size      = "XSMALL"
  auto_suspend        = 60
  auto_resume         = true
  initially_suspended = true
  resource_monitor    = snowflake_resource_monitor.guardrail.fully_qualified_name
  comment             = "COPY INTO loads from the RAW external stage"
}

# ── Resource monitor: the credit cap ──────────────────────────────────────────
# Snowflake has no spending limit by default. This emails the admin at 50/75/90%
# of the monthly quota, suspends both warehouses at 100% (running queries
# finish), and kills running queries at 110%.

resource "snowflake_resource_monitor" "guardrail" {
  name            = "POLARIS_MONTHLY_GUARDRAIL"
  credit_quota    = var.monthly_credit_quota
  frequency       = "MONTHLY"
  start_timestamp = "IMMEDIATELY" # frequency needs a start; this means "today"

  notify_triggers           = [50, 75, 90]
  suspend_trigger           = 100
  suspend_immediate_trigger = 110
}
