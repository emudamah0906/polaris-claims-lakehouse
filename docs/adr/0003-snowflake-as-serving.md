# ADR-0003: Snowflake as the serving layer (not Databricks SQL)

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture

## Context

Polaris already runs Spark on Databricks for Silver. The obvious question — and one any senior interviewer will ask — is: *why pay for two compute platforms*? Why not serve Gold via Databricks SQL Warehouses and avoid Snowflake entirely?

The serving layer must support:

1. **Persona isolation** — finance, actuarial, fraud, and BI users have different cost ownership and different access patterns; one team's runaway query should not throttle another's dashboard.
2. **BI tool ergonomics** — the realistic Canadian carrier consumer is Power BI or Excel-via-ODBC, not a Databricks notebook.
3. **Ephemeral CI environments** — every PR needs an isolated Snowflake schema for `dbt build` against real data.
4. **Cost predictability** — finance gets a credit-by-warehouse view; engineering gets per-query attribution.
5. **Snowpipe-style continuous loads** from ADLS without standing up our own Databricks-side load process.

## Decision

Use **Snowflake** as the serving layer for all Gold marts. Maintain three warehouses with strict separation: `WH_LOAD` (XS, autosuspend 60s — Snowpipe + COPY targets), `WH_TRANSFORM` (S — dbt runs), `WH_BI` (M — analyst + dashboard queries). Authentication via key-pair only.

Real-time fraud signals **stay in Delta on Databricks** (read directly by the Streamlit fraud console) because Snowpipe latency is unacceptable for sub-minute alerting. Snowflake is the serving layer for everything else.

## Alternatives considered

### Alternative A: Databricks SQL Warehouses only
- **Pros:** Single platform; no Snowpipe latency; Photon performance is competitive; lakehouse story is cleaner architecturally.
- **Cons:** Persona/cost isolation is weaker (warehouses share the metastore + workspace permissions model in ways that are harder to audit for finance). BI tool experience is improving but Power BI Direct Query against Databricks is still less mature than against Snowflake. Ephemeral CI environments are clumsier.
- **Rejected because:** persona isolation and BI ergonomics are non-negotiable for the simulated carrier; the operational cost of running both is justified by what each is best at.

### Alternative B: Azure Synapse (Serverless or Dedicated)
- **Pros:** All-Azure story; tight ADLS integration; Power BI native.
- **Cons:** Smaller ecosystem; weaker dbt adapter; less common in Toronto FS hiring; cost model less transparent than Snowflake credits.
- **Rejected because:** we lose interview leverage (Snowflake fluency is the senior-DE baseline at Canadian banks/insurers) for marginal Azure integration gains.

### Alternative C: BigQuery (cross-cloud)
- **Pros:** Excellent serverless model; the user has prior GCP DE experience.
- **Cons:** Cross-cloud egress from ADLS becomes a significant cost; no operational reason to span clouds for a single workload; complicates IaC.
- **Rejected because:** cross-cloud is unjustified complexity for this project's constraints.

## Consequences

### Positive
- **Persona isolation by warehouse** — finance can be capped at a credit budget without affecting dbt CI runs.
- **Per-PR ephemeral schemas** via dbt's `generate_schema_name` macro + a CI workflow that creates `POLARIS_CI_PR<n>` schemas — clean, fast, throwaway.
- **Power BI integration** is first-class; dashboards we build will look like the ones interviewers' actual analysts use.
- **Snowflake's `QUERY_HISTORY` view** powers a dbt-built cost dashboard — the kind of cost-mindset artifact senior engineers are expected to produce.

### Negative / accepted trade-offs
- **Two compute platforms** to operate, monitor, and budget for.
- **Snowpipe latency** (~30 sec to a few minutes) means real-time fraud signals cannot live in Snowflake. We accept this and make Databricks the source for sub-minute reads.
- **Data movement cost** — every Silver row written to ADLS is also loaded into Snowflake. Mitigated by Snowflake's external table / Iceberg interop for cold reads where freshness doesn't matter.

### Mitigations
- All warehouses configured with `AUTO_SUSPEND = 60` and `AUTO_RESUME = TRUE` to minimize idle credit burn.
- Resource monitors (`CREATE RESOURCE MONITOR`) set hard caps per warehouse with email alerts at 75/90/100%.
- The Snowflake cost dashboard (under `dbt/analyses/cost_by_warehouse.sql`) is a recurring review artifact.

## Revisit triggers

- Databricks SQL Warehouse pricing or performance eclipses Snowflake for our query mix.
- The carrier's BI standard shifts from Power BI to a Databricks-native tool.
- Snowpipe latency becomes acceptable for fraud (Snowpipe Streaming has narrowed this gap — re-evaluate annually).
