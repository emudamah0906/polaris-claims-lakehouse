# ── Stage 2c: Azure Data Factory moves vendor files from landing to Bronze ────
# Terraform builds the factory and what it may touch. The pipeline itself is
# built by hand in ADF Studio, then exported to adf/pipelines/ (see
# docs/runbooks/stage-2c-adf.md).

# Where vendors drop files. Separate from bronze on purpose: landing holds
# whatever arrived, bronze only what passed the row-count check.
resource "azurerm_storage_container" "landing" {
  name                  = "landing"
  storage_account_id    = azurerm_storage_account.lake.id
  container_access_type = "private"
}

resource "azurerm_data_factory" "polaris" {
  # Factory names are global across Azure, so reuse the storage suffix
  name                = "polaris-adf-${random_string.suffix.result}"
  location            = azurerm_resource_group.polaris.location
  resource_group_name = azurerm_resource_group.polaris.name

  # The factory's own Azure AD identity. Linked services log in as it, so no
  # storage key or SAS token is ever pasted into ADF.
  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

# ── What the factory may do, per container (least privilege) ─────────────────
# Read landing: it never changes what a vendor sent.
# Write bronze: copy in, and delete its own file if the row count is wrong.

resource "azurerm_role_assignment" "adf_landing_reader" {
  scope                = azurerm_storage_container.landing.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_data_factory.polaris.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "adf_bronze_writer" {
  scope                = azurerm_storage_container.layer["bronze"].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_data_factory.polaris.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}
