# ADR-0008: Secrets via Azure Key Vault; CI auth via GitHub OIDC; no long-lived credentials

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture

## Context

Polaris has the usual sensitive-credential problem: ADLS access keys, Snowflake private keys, Databricks OAuth client secrets, Slack webhook URLs. These need to be available at runtime to:

1. Local developer machines.
2. GitHub Actions CI/CD workflows.
3. Databricks Jobs (batch + streaming).
4. Airflow DAG runs.

The temptation in portfolio projects is to drop everything into GitHub repository secrets and call it done. That works, but it leaves long-lived credentials sitting in a system whose breach blast radius is the entire repo's CI history. For a project explicitly billed as "production-grade," that gap is the first thing a security-conscious interviewer will probe.

## Decision

**All secrets live in Azure Key Vault.** Nothing else.

**GitHub Actions authenticates to Azure via OIDC federation:**
- An Azure AD app registration trusts the GitHub OIDC issuer for this specific repository.
- Federated credential is scoped per branch / per environment (e.g. `main` branch can deploy to prod; PR branches can plan only).
- Workflows use `azure/login@v2` with `client-id`, `tenant-id`, `subscription-id` — no `client-secret`.
- Once authenticated, the workflow reads secrets from Key Vault on demand for that run; nothing persists after the workflow ends.

**Snowflake authentication is key-pair, not password:**
- The RSA private key lives in Key Vault (or `~/.snowflake/` locally, gitignored).
- The public key is registered against the Snowflake user.
- Rotation is scripted in `scripts/rotate_snowflake_key.sh`.

**Databricks authentication is OAuth (M2M), not PAT:**
- Service principal with OAuth credentials in Key Vault.
- PATs are explicitly forbidden — `databricks.cfg` is gitignored and `.databrickscfg` validation runs in pre-commit.

**Local developer experience:**
- `.env` (gitignored) holds non-sensitive config (region, account name).
- Sensitive values are pulled at runtime from Key Vault using `az keyvault secret show` or the Python `azure-keyvault-secrets` SDK.
- A `make bootstrap-secrets` target documents the one-time `az login` flow.

## Alternatives considered

### Alternative A: GitHub repo secrets only (Azure Service Principal client secret stored as GH secret)
- **Pros:** Trivial setup; works immediately.
- **Cons:** Long-lived client secret sitting in GitHub. If repo permissions are misconfigured or a workflow is compromised, the credential is exfiltrated. Rotation is manual and forgettable.
- **Rejected because:** the "no long-lived credentials in CI" property is exactly what an interviewer will ask about; we should be the answer, not the bad example.

### Alternative B: HashiCorp Vault
- **Pros:** Industry-standard secret manager; cloud-agnostic.
- **Cons:** Operating Vault for a single-developer project is overkill; running Vault in a way that itself doesn't have a chicken-and-egg secrets problem requires more infra than this project needs.
- **Rejected because:** Azure Key Vault gives us the same security properties for this scope at zero operational cost.

### Alternative C: Doppler / 1Password Secrets Automation / Infisical
- **Pros:** Polished developer experience.
- **Cons:** Vendor dependency for a transient project; another bill; another auth surface.
- **Rejected because:** Key Vault is already in scope and free under our Azure credits.

### Alternative D: Plain `.env` files committed to the repo (encrypted with `git-crypt` or `sops`)
- **Pros:** Self-contained; works offline.
- **Cons:** Encrypted secrets in git history are still secrets in git history — recoverable forever if a key leaks.
- **Rejected because:** "no secrets in git, ever" is a hard rule.

## Consequences

### Positive
- **Zero long-lived credentials in CI.** Every workflow run authenticates fresh via OIDC; the federated token expires when the workflow ends.
- **Single source of truth** for production secrets — Key Vault.
- **Auditable access** — Key Vault access logs show who/what/when read each secret.
- **Defendable interview answer** — "we use OIDC federation to Azure and pull secrets from Key Vault per-run" is the answer security-aware staff engineers want to hear.

### Negative / accepted trade-offs
- **Setup complexity.** Federated identity setup is more involved than dropping a secret into GH. Mitigated by Terraform-managing the Azure AD app registration + federated credential, so reproduction is `terraform apply`.
- **Local dev requires `az login`** before running anything that touches a real secret. Accepted; documented in the bootstrap runbook.
- **Cold-start cost** — first secret fetch in a new workflow adds ~1 second. Negligible.

### Mitigations
- `infra/terraform/azure/` provisions the Azure AD app, federated credential, and Key Vault role assignments — no clickops in the Azure portal.
- Pre-commit hook (`detect-secrets` + `gitleaks`) blocks accidental secret commits.
- `.gitignore` is paranoid: `.env`, `*.pem`, `*.key`, `*.p8`, `*.p12`, `secrets/`, `credentials/`.
- A quarterly key-rotation runbook (`docs/runbooks/secret-rotation.md`) ensures keys don't outlive their useful life.

## Revisit triggers

- We move beyond a single Azure tenant / single GitHub org → revisit federation scoping.
- We add a non-Azure cloud → either federate to that cloud's IAM separately or adopt a multi-cloud secret manager.
- Compliance regime changes (e.g. SOC 2, OSFI E-21) require BYO-KMS — Key Vault supports customer-managed keys; revisit configuration.
