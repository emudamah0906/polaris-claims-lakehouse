terraform {
  required_version = ">= 1.6"

  required_providers {
    snowflake = {
      source  = "Snowflake-Labs/snowflake"
      version = "~> 1.0"
    }
  }

  # State stays local for now. Remote state in Azure Blob comes with the Azure
  # Terraform (ADR-0008); uncomment once the tfstate container exists.
  #
  # backend "azurerm" {
  #   resource_group_name  = "polaris-rg"
  #   storage_account_name = "polarisstg"
  #   container_name       = "tfstate"
  #   key                  = "snowflake/terraform.tfstate"
  # }
}

provider "snowflake" {
  # Key-pair auth, no password (ADR-0008). Values come from terraform.tfvars,
  # which is gitignored.
  organization_name = var.snowflake_organization
  account_name      = var.snowflake_account
  user              = var.snowflake_user
  authenticator     = "SNOWFLAKE_JWT" # provider v1 name; "JWT" was removed
  private_key       = file(pathexpand(var.snowflake_private_key_path))

  # Only Terraform runs as ACCOUNTADMIN. Every pipeline uses the roles in roles.tf.
  role = "ACCOUNTADMIN"

  # In provider v1 these three resources are "preview": they can change in a
  # minor release, so the provider makes you switch each one on by name.
  preview_features_enabled = [
    "snowflake_storage_integration_resource",
    "snowflake_file_format_resource",
    "snowflake_stage_resource",
  ]
}
