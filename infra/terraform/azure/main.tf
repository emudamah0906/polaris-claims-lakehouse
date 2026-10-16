# ── Resource group ────────────────────────────────────────────────────────────
# A folder for everything Polaris makes in Azure. Deleting it deletes them all.

resource "azurerm_resource_group" "polaris" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

locals {
  tags = {
    project    = "polaris"
    managed_by = "terraform"
  }
}

# ── Storage account (ADLS Gen2) ───────────────────────────────────────────────
# Storage account names are global across all of Azure, 3-24 lowercase letters
# and digits. "polarisstg" is almost certainly taken, so add a random suffix.
# It's generated once and kept in state, so the name doesn't change later.

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_storage_account" "lake" {
  name                     = "polaris${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.polaris.name
  location                 = azurerm_resource_group.polaris.location
  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS" # 3 copies in one datacentre. Cheapest, fine for a portfolio

  # This one setting is what makes it ADLS Gen2: real folders instead of a flat
  # list of blobs, so renaming or deleting a folder is one operation.
  is_hns_enabled = true

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false # nothing in here can be made public

  tags = local.tags
}

# ── Containers, one per medallion layer ───────────────────────────────────────
# Stage 2 writes only to bronze. Silver and gold are created now so the layout
# is fixed from day one.

resource "azurerm_storage_container" "layer" {
  for_each              = toset(["bronze", "silver", "gold"])
  name                  = each.key
  storage_account_id    = azurerm_storage_account.lake.id
  container_access_type = "private"
}

# ── Data access for you ───────────────────────────────────────────────────────
# Being Owner of the subscription lets you manage the storage account, but not
# read or write the files inside it. That's a separate data-plane role. Without
# this, polaris-ingest gets a 403 even though you "own" everything.

data "azurerm_client_config" "current" {}

resource "azurerm_role_assignment" "me_blob_contributor" {
  scope                = azurerm_storage_account.lake.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}
