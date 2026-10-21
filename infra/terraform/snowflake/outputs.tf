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

# ── Stage 5: the two values for the Azure half of the handshake ──────────────

output "azure_consent_url" {
  description = "Open in a browser, sign in as the subscription owner, Accept. Registers Snowflake's app in your tenant."
  value       = snowflake_storage_integration.adls_bronze.azure_consent_url
}

output "azure_multi_tenant_app_name" {
  description = "Paste into snowflake_app_name in infra/terraform/azure/terraform.tfvars."
  value       = snowflake_storage_integration.adls_bronze.azure_multi_tenant_app_name
}

output "bronze_stage" {
  description = "External stage the loader runs COPY INTO from."
  value       = snowflake_stage.bronze.fully_qualified_name
}

output "resource_monitor" {
  description = "Monthly credit cap on both warehouses."
  value = {
    name         = snowflake_resource_monitor.guardrail.name
    credit_quota = snowflake_resource_monitor.guardrail.credit_quota
  }
}
