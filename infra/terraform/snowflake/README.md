# Terraform: Snowflake foundation (Stage 1)

Everything Polaris needs inside Snowflake, written as code: the database, one
schema per layer, two warehouses, three roles and a credit cap. No clicking
around Snowsight after the one-time bootstrap below.

> **Status:** applied 15 Oct 2026 to a Snowflake trial account. 39 resources
> created, second plan clean, analyst grants checked. See the checklist at the bottom.

## What gets created

```
DATABASE  POLARIS                         7-day time travel
  SCHEMA  RAW            ← COPY INTO target (Stage 5)
  SCHEMA  STAGING        ← dbt staging views
  SCHEMA  INTERMEDIATE   ← dbt intermediate (mostly ephemeral)
  SCHEMA  MARTS          ← dbt mart tables

WAREHOUSE POLARIS_WH_TRANSFORM  XSMALL  suspend after 60s  ← dbt, GE, Streamlit
WAREHOUSE POLARIS_WH_LOAD       XSMALL  suspend after 60s  ← COPY INTO only

ROLE  POLARIS_LOADER_ROLE   USAGE + CREATE TABLE on RAW, SELECT/INSERT on RAW tables, WH_LOAD
ROLE  POLARIS_DBT_ROLE      SELECT on RAW, CREATE TABLE/VIEW on STAGING/INT/MARTS, WH_TRANSFORM
ROLE  POLARIS_ANALYST_ROLE  SELECT on STAGING + MARTS tables and views, WH_TRANSFORM
      (all three granted to SYSADMIN)

RESOURCE MONITOR  POLARIS_MONTHLY_GUARDRAIL  100 credits/month
                  notify 50/75/90%, suspend 100%, kill queries 110%
```

Expected `terraform plan` count before you run it: **39 to add**
(1 database, 4 schemas, 2 warehouses, 1 monitor, 3 roles, 3 SYSADMIN grants,
25 privilege grants). If plan says something else, stop and compare.

## Bootstrap (one time, by hand)

Terraform can't log in until a user exists for it to log in as. So a human
creates that first user, once. Everything after that is code.

1. **Make a key pair** for the Terraform service user. This is Snowflake's
   documented format (unencrypted PKCS#8):

   ```bash
   mkdir -p ~/.snowflake
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.snowflake/terraform_svc_rsa.p8 -nocrypt
   openssl rsa -in ~/.snowflake/terraform_svc_rsa.p8 -pubout -out ~/.snowflake/terraform_svc_rsa.pub
   chmod 600 ~/.snowflake/terraform_svc_rsa.p8
   ```

2. **Create the user in Snowsight** as ACCOUNTADMIN. Paste the public key body
   without the `-----BEGIN/END-----` lines:

   ```sql
   CREATE USER TERRAFORM_SVC TYPE = SERVICE RSA_PUBLIC_KEY = '<public key body>';
   GRANT ROLE ACCOUNTADMIN TO USER TERRAFORM_SVC;
   ```

3. **Fill in your account details**:

   ```bash
   cd infra/terraform/snowflake
   cp terraform.tfvars.example terraform.tfvars   # gitignored
   ```

   Org and account names are in Snowsight under Admin > Accounts.

4. **Run it**, one command at a time, reading the output in between:

   ```bash
   terraform init
   terraform validate
   terraform plan -out tfplan
   terraform apply tfplan
   ```

## Stage 5: reading the ADLS bronze container

`landing.tf` adds the link from Snowflake to Azure. No storage key or SAS
token exists anywhere: Snowflake gets its own identity in your Azure tenant,
and Azure gives that identity read access to one container.

```
STORAGE INTEGRATION  POLARIS_ADLS_BRONZE   allowed: azure://<account>.blob.core.windows.net/bronze/
FILE FORMAT          POLARIS.RAW.BRONZE_CSV   header row, comma, optional quotes
STAGE                POLARIS.RAW.BRONZE_ADLS  points at the bronze container
GRANT                USAGE on the stage and the file format to POLARIS_LOADER_ROLE
```

It's a handshake across two clouds, so the order matters. One step at a
time, checking each result:

1. **Two values into `terraform.tfvars`** (see the example file):
   `azure_tenant_id` from `az account show --query tenantId -o tsv`, and
   `adls_account = "polaris599i8o"`.
2. **Snowflake plan and apply.** `terraform plan -out tfplan` should show
   **5 to add, 0 to change, 0 to destroy** (integration, file format, stage,
   2 grants). Then `terraform apply tfplan`.
3. **Consent, in a browser.** `terraform output -raw azure_consent_url`, open
   it, sign in as the subscription owner, Accept. This registers Snowflake's
   app in your tenant. It grants nothing yet.
4. **Azure side** (`infra/terraform/azure`). Put
   `snowflake_app_name = "<terraform output -raw azure_multi_tenant_app_name>"`
   in its `terraform.tfvars`, then `terraform init` (new azuread provider),
   `terraform plan -out tfplan`: **1 to add** (Storage Blob Data Reader on the
   bronze container), then apply.
5. **Wait two minutes.** Azure role assignments take a moment to apply.
6. **Load.** `ingestion/snowflake/load_raw.sql` in Snowsight, one section at a
   time. It lists the stage, checks `_SUCCESS`, creates the RAW tables and
   runs COPY INTO.
7. **Re-plan both stacks.** Both should show no changes.

Why it's built this way:

- **Integration, not a key.** A SAS token in a stage definition works, but
  it's a long-lived secret that nobody rotates. To cut off a storage
  integration, you remove one role assignment in Azure.
- **Reader, not Contributor, and only on bronze.** Snowflake only reads
  files. With write access it could delete the one copy of Bronze.
- **`storage_allowed_locations`** is a whitelist on the Snowflake side. A
  stage written later can't point this integration anywhere else.
- **COPY INTO isn't in Terraform.** Terraform manages objects that should
  exist. Loading data is a pipeline step that runs every day, so it lives in
  SQL now and moves to Airflow in Stage 7.
- **Preview features.** In provider v1, storage integration, stage and file
  format are "preview" resources that can change in a minor release, so
  `versions.tf` switches each one on by name.

## State

State is local (`terraform.tfstate`, gitignored) for now. The `backend
"azurerm"` block in `versions.tf` moves it to Azure Blob with locking once the
Azure side exists, which is what CI needs before it can apply safely.

## Why it's built this way

- **Two warehouses, not one.** Workloads are kept apart. A runaway dbt query
  can't delay the nightly load, and a backfill can't slow analysts. The cost
  is the same because billing is per second per warehouse.
- **Least privilege.** The loader can't read marts. The analyst can't write
  anywhere. Only dbt can create objects in STAGING, INTERMEDIATE and MARTS. A
  stolen analyst credential can read marts and nothing else.
- **Future grants.** Each grant has an `all` part (tables that exist now) and a
  `future` part (tables created later). Without the future part, every new dbt
  model would be invisible to analysts until someone re-ran the grants.
- **Resource monitor.** Snowflake has no spending cap by default. The
  notifications at 50, 75 and 90% give a window to react, and suspending at
  100% caps the bill.
- **Key-pair auth (ADR-0008).** No shared password. The key can be rotated and
  works for automation.
- **`initially_suspended = true`.** A new warehouse costs nothing until its
  first query.

## Applied checklist

- [x] `terraform plan` showed 39 to add
- [x] `terraform apply` finished clean
- [x] `SHOW GRANTS TO ROLE POLARIS_ANALYST_ROLE;` shows only USAGE (4 rows; SELECT rows appear once dbt creates tables)
- [x] Second `terraform plan` shows no changes

Stage 5 (20 Oct 2026):

- [x] Snowflake plan showed 5 to add, applied clean
- [x] Consent URL accepted; `SnowflakePACInt1363` exists in the tenant
- [x] Azure plan showed 1 to add, applied clean
- [x] `LIST @BRONZE_ADLS` shows the four CSVs and `_SUCCESS` (first try gave a
      403: the role assignment was minutes old. Fine on retry)
- [x] RAW counts 3,000 / 5,000 / 10,000 / 11,203, 0 errors
- [x] Second COPY INTO loads 0 files and counts stay the same
- [x] Both stacks re-plan clean
- [x] `POLARIS_SVC` service user (users.tf, 3 added): key pair only, holds the
      loader and dbt roles. The load ran as POLARIS_SVC / POLARIS_LOADER_ROLE
