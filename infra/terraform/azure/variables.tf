variable "subscription_id" {
  description = "Azure subscription to deploy into. `az account show --query id -o tsv` prints it."
  type        = string
}

variable "location" {
  description = "Azure region. Canada Central keeps the data in Canada."
  type        = string
  default     = "canadacentral"
}

variable "resource_group_name" {
  description = "Resource group holding everything Polaris creates in Azure."
  type        = string
  default     = "polaris-rg"
}
