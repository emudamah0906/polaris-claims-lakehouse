# ── Pipeline service user ─────────────────────────────────────────────────────
# What the load and dbt log in as. TYPE = SERVICE: no password, no MFA prompt,
# can't sign in to Snowsight. Key pair only (ADR-0008).
#
# One user holds two roles: loader for COPY INTO, dbt for dbt build. Each job
# picks its role at the start, so a session only has one role's privileges at
# a time. Production would split this into two users so one stolen key can't
# do both jobs; one is enough for a single-engineer project.

locals {
  # Snowflake wants the key body only: no BEGIN/END lines, no line breaks
  polaris_svc_public_key = replace(
    replace(file(pathexpand(var.polaris_svc_public_key_path)), "/-----[A-Z ]+-----/", ""),
    "\n", ""
  )
}

resource "snowflake_service_user" "pipeline" {
  name              = "POLARIS_SVC"
  comment           = "Pipeline user: COPY INTO (loader role) and dbt build (dbt role)"
  rsa_public_key    = local.polaris_svc_public_key
  default_role      = snowflake_account_role.dbt.name
  default_warehouse = snowflake_warehouse.transform.name
  default_namespace = snowflake_database.polaris.name
}

resource "snowflake_grant_account_role" "pipeline_roles" {
  for_each = {
    loader = snowflake_account_role.loader.name
    dbt    = snowflake_account_role.dbt.name
  }
  role_name = each.value
  user_name = snowflake_service_user.pipeline.name
}
