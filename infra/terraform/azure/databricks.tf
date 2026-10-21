# ── Stage 3: Azure Databricks for the Silver layer ────────────────────────────
#
#   workspace          where notebooks and jobs live. Clusters it starts run as
#                      VMs in a managed resource group Azure creates for it.
#   access connector   an Azure identity Unity Catalog uses to reach ADLS.
#                      Same idea as ADF's managed identity: no keys anywhere.
#   budget             a cost alarm on the whole subscription, because cluster
#                      VMs live outside polaris-rg.
#
# Inside the workspace (catalog, external locations, the job) is configured
# with the databricks provider in infra/terraform/databricks.

resource "azurerm_databricks_workspace" "polaris" {
  name                        = "polaris-dbw-${random_string.suffix.result}"
  resource_group_name         = azurerm_resource_group.polaris.name
  location                    = azurerm_resource_group.polaris.location
  managed_resource_group_name = "polaris-dbw-managed-rg"

  # Premium: Unity Catalog needs it. ("trial" isn't allowed on an Azure Free
  # Trial subscription.) DBUs and VMs are billed only while a cluster runs;
  # a job cluster starts per run and stops after, so idle costs nothing.
  sku = "premium"

  tags = local.tags
}

resource "azurerm_databricks_access_connector" "unity" {
  name                = "polaris-dbw-connector"
  resource_group_name = azurerm_resource_group.polaris.name
  location            = azurerm_resource_group.polaris.location

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

# Unity Catalog reads Bronze and writes Silver. Least privilege per container.
resource "azurerm_role_assignment" "unity_bronze_reader" {
  scope                = azurerm_storage_container.layer["bronze"].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_databricks_access_connector.unity.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "unity_silver_writer" {
  scope                = azurerm_storage_container.layer["silver"].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.unity.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# ── Cost alarm ────────────────────────────────────────────────────────────────
# Emails the subscription Owner at 40%, 80% and 100% of the monthly amount,
# and when the forecast says the month will go over.

data "azurerm_subscription" "current" {}

resource "azurerm_consumption_budget_subscription" "polaris" {
  name            = "polaris-monthly"
  subscription_id = data.azurerm_subscription.current.id
  amount          = var.monthly_budget
  time_grain      = "Monthly"

  time_period {
    start_date = "2026-10-01T00:00:00Z" # budgets must start on the 1st of a month
  }

  dynamic "notification" {
    for_each = [40, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = "Actual"
      contact_roles  = ["Owner"]
    }
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Forecasted"
    contact_roles  = ["Owner"]
  }
}
