# Printed after apply. storage_account_name goes into .env as ADLS_ACCOUNT_NAME.

output "storage_account_name" {
  description = "Globally unique storage account name."
  value       = azurerm_storage_account.lake.name
}

output "bronze_url" {
  description = "Where polaris-ingest lands Bronze files."
  value       = "abfss://bronze@${azurerm_storage_account.lake.name}.dfs.core.windows.net/"
}

output "data_factory_name" {
  description = "Stage 2c: open it in ADF Studio from the portal, or adf.azure.com."
  value       = azurerm_data_factory.polaris.name
}

output "databricks_workspace_url" {
  description = "Stage 3: open this to reach the Databricks workspace."
  value       = "https://${azurerm_databricks_workspace.polaris.workspace_url}"
}

output "databricks_access_connector_id" {
  description = "Stage 3: Unity Catalog's storage credential uses this identity."
  value       = azurerm_databricks_access_connector.unity.id
}

output "containers" {
  description = "One container per medallion layer."
  value       = sort([for c in azurerm_storage_container.layer : c.name])
}
