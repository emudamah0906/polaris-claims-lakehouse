# ── Stage 3: Unity Catalog objects inside the Databricks workspace ────────────
#
#   storage credential   UC's way in to ADLS: the access connector's managed
#                        identity (infra/terraform/azure/databricks.tf)
#   external locations   the ADLS paths UC governs: bronze (read), silver (write)
#   catalog "polaris"    Silver tables live in OUR silver container, not in
#                        Databricks-managed storage, so the data outlives the
#                        workspace
#   schema  "silver"     the Delta tables the Silver job writes

locals {
  account = "polaris599i8o"
  url     = { for c in ["bronze", "silver"] : c => "abfss://${c}@${local.account}.dfs.core.windows.net/" }
}

resource "databricks_storage_credential" "adls" {
  name    = "polaris_adls"
  comment = "Access connector managed identity: Reader on bronze, Contributor on silver"
  azure_managed_identity {
    access_connector_id = data.terraform_remote_state.azure.outputs.databricks_access_connector_id
  }
}

resource "databricks_external_location" "layer" {
  for_each        = local.url
  name            = "polaris_${each.key}"
  url             = each.value
  credential_name = databricks_storage_credential.adls.name
  read_only       = each.key == "bronze" # Silver jobs must never write to Bronze
  comment         = "ADLS ${each.key} container"
}

resource "databricks_catalog" "polaris" {
  name         = "polaris"
  storage_root = "${local.url["silver"]}uc"
  comment      = "Polaris lakehouse. Managed tables stored in the ADLS silver container."
  depends_on   = [databricks_external_location.layer]
}

resource "databricks_schema" "silver" {
  catalog_name = databricks_catalog.polaris.name
  name         = "silver"
  comment      = "Conformed claims-system data. policies keeps full history (SCD2, ADR-0004)."
}
