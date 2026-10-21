terraform {
  required_version = ">= 1.6"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.70"
    }
  }
}

# The workspace URL and the access connector come from the Azure stack's
# state, so nothing is copied by hand between the two.
data "terraform_remote_state" "azure" {
  backend = "local"
  config = {
    path = "${path.module}/../azure/terraform.tfstate"
  }
}

provider "databricks" {
  host = data.terraform_remote_state.azure.outputs.databricks_workspace_url
  # Same `az login` session as the Azure stack (ADR-0008: no tokens in files)
  auth_type = "azure-cli"
}
