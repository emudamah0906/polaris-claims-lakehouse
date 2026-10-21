terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    # Stage 5: looks up Snowflake's app in Azure AD by name
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
  }

  # Local state for now, same as the Snowflake stack. Once this storage
  # account exists, a tfstate container in it can hold both stacks' state.
}

provider "azurerm" {
  features {}

  # azurerm v4 needs the subscription spelled out. It doesn't fall back to
  # whatever `az account set` points at.
  subscription_id = var.subscription_id

  # Terraform logs in with your `az login` session. No keys or secrets in
  # this folder (ADR-0008).
}

# Same `az login` session, same tenant.
provider "azuread" {}
