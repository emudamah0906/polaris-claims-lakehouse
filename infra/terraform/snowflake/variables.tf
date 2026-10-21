variable "snowflake_organization" {
  description = "Snowflake organization name (Snowsight > Admin > Accounts)."
  type        = string
}

variable "snowflake_account" {
  description = "Snowflake account name inside the organization."
  type        = string
}

variable "snowflake_user" {
  description = "Service user Terraform logs in as. Needs ACCOUNTADMIN (see README bootstrap)."
  type        = string
  default     = "TERRAFORM_SVC"
}

variable "snowflake_private_key_path" {
  description = "Path to the RSA private key for snowflake_user. Lives outside the repo."
  type        = string
  default     = "~/.snowflake/terraform_svc_rsa.p8"
}

variable "database_name" {
  description = "Top-level database. dbt profiles and .env use the same name."
  type        = string
  default     = "POLARIS"
}

variable "warehouse_transform" {
  description = "Warehouse for dbt, Great Expectations and Streamlit reads."
  type        = string
  default     = "POLARIS_WH_TRANSFORM"
}

variable "warehouse_load" {
  description = "Warehouse for COPY INTO loads only, so loads and transforms never queue behind each other."
  type        = string
  default     = "POLARIS_WH_LOAD"
}

variable "monthly_credit_quota" {
  description = "Credits per month before both warehouses are suspended."
  type        = number
  default     = 100
}
