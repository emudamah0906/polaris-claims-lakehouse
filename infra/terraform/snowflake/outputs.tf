# Printed after apply. Copy these into .env and dbt/profiles/profiles.yml.

output "database" {
  description = "Top-level database."
  value       = snowflake_database.polaris.name
}

output "schemas" {
  description = "One schema per layer."
  value = {
    raw          = snowflake_schema.raw.name
    staging      = snowflake_schema.staging.name
    intermediate = snowflake_schema.intermediate.name
    marts        = snowflake_schema.marts.name
  }
}

output "warehouses" {
  description = "Transform (dbt, GE, BI) and load (COPY INTO) warehouses."
  value = {
    transform = snowflake_warehouse.transform.name
    load      = snowflake_warehouse.load.name
  }
}

output "roles" {
  description = "Least-privilege roles for each workload."
  value = {
    loader  = snowflake_account_role.loader.name
    dbt     = snowflake_account_role.dbt.name
    analyst = snowflake_account_role.analyst.name
  }
}

output "resource_monitor" {
  description = "Monthly credit cap on both warehouses."
  value = {
    name         = snowflake_resource_monitor.guardrail.name
    credit_quota = snowflake_resource_monitor.guardrail.credit_quota
  }
}
