# Terraform: Azure storage for Bronze (Stage 2)

The Azure side of Polaris: one resource group, one ADLS Gen2 storage account
and a container per medallion layer. Terraform and `polaris-ingest` both log
in with your `az login` session, so there are no keys in this folder.

> **Status:** code written, not yet applied.

## What gets created

```
RESOURCE GROUP   polaris-rg                 canadacentral
STORAGE ACCOUNT  polaris<6 random chars>    StorageV2, LRS, hierarchical namespace ON (= ADLS Gen2)
  CONTAINER      bronze                     polaris-ingest writes here
  CONTAINER      silver                     Stage 3
  CONTAINER      gold                       later
ROLE ASSIGNMENT  Storage Blob Data Contributor on the account, for you
```

Expected `terraform plan`: **7 to add** (resource group, random suffix,
storage account, 3 containers, role assignment).

## Run it

```bash
az login                                   # once; opens a browser
cd infra/terraform/azure
cp terraform.tfvars.example terraform.tfvars   # add your subscription ID
terraform init
terraform plan -out tfplan
terraform apply tfplan
terraform plan                             # should say No changes
```

Role assignments can take a few minutes to take effect after apply. A 403 from
`polaris-ingest` right after apply usually means wait and retry.

## Why it's built this way

- **Hierarchical namespace on.** That's what turns Blob storage into ADLS
  Gen2: real folders, so Spark can rename or delete a partition in one call.
- **Data access is its own role.** Owner can manage the account but can't
  read files. `Storage Blob Data Contributor` is the data-plane role.
- **Random suffix.** Storage account names are global across Azure.
- **LRS, Standard tier.** Cheapest option. A few MB of CSVs costs pennies a
  month.

## Production follow-ups

- Turn off shared access keys (`shared_access_key_enabled = false`) so only
  Azure AD logins work. Left on for now because the provider needs care to
  manage an account that way.
- Move both Terraform stacks' state into a `tfstate` container here.
