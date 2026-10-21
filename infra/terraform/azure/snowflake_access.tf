# ── Stage 5: let Snowflake read the bronze container ──────────────────────────
# The Azure half of the handshake. The Snowflake stack's storage integration
# creates an app; once you accept its consent URL, that app exists in your
# tenant as a service principal. This gives it read access to bronze.
#
# snowflake_app_name starts empty, so nothing here is created until the
# consent step is done. Plans before that stay clean.

locals {
  # Snowflake prints e.g. "abcdefsnowflakepacint_1700000000000". The app's
  # name in Azure is the part before the underscore.
  snowflake_sp_name = split("_", var.snowflake_app_name)[0]
}

data "azuread_service_principal" "snowflake" {
  count        = var.snowflake_app_name == "" ? 0 : 1
  display_name = local.snowflake_sp_name
}

# Reader, not Contributor: Snowflake only lists and reads files, so it can
# never delete Bronze. Scoped to the bronze container, not the whole account.
resource "azurerm_role_assignment" "snowflake_bronze_reader" {
  count                = var.snowflake_app_name == "" ? 0 : 1
  scope                = azurerm_storage_container.layer["bronze"].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = data.azuread_service_principal.snowflake[0].object_id
  principal_type       = "ServicePrincipal" # skips a lookup that can fail on a brand-new app
}
