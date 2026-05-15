# ADR-0007: Spark Structured Streaming runs as a long-lived service outside Airflow

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture

## Context

Polaris uses Airflow to orchestrate batch DAGs (Bronze ingest → Silver batch → Snowflake load → dbt build). It also runs a Spark Structured Streaming job consuming FNOL events from Kafka into Silver.

There is a recurring temptation — observed often in junior architectures — to wrap the streaming job inside Airflow using `BashOperator`, `SparkSubmitOperator`, or a continuous DAG, so that Airflow "manages" it. This conflates two fundamentally different process models and is a recurring source of production incidents.

Airflow's scheduler was built to run finite, idempotent tasks on a cron-like cadence. A Structured Streaming job is a long-lived process that ideally never stops. Mixing them creates failure modes that neither tool handles well: Airflow task timeouts kill the streaming job; restart logic inside Airflow racing with the job's own checkpoint recovery; DAG-run state diverging from the actual process state.

## Decision

The Spark Structured Streaming job runs as a **long-lived Databricks Job** (configured `Continuous` mode, max-retries unlimited, restart on failure). On a developer laptop it runs as a long-lived `spark-submit` process via Docker.

Airflow's role is **observation, not control**:

- A `streaming_heartbeat` DAG runs every 5 minutes and checks the `_delta_log` last-modified timestamp on `silver.claim_events`.
- If the timestamp is stale beyond `STREAMING_STALE_THRESHOLD` (default 90 seconds), the DAG fails and pages via Slack webhook.
- The DAG never starts, stops, or restarts the streaming job. Recovery is operator-driven via the runbook.

Process supervision is the streaming runtime's job (Databricks Job retries / `kubectl rollout` / `systemd` depending on environment). Orchestration is Airflow's job. The two never overlap.

## Alternatives considered

### Alternative A: Wrap streaming in Airflow `SparkSubmitOperator`
- **Pros:** Single tool for everything; one UI for engineers.
- **Cons:** `SparkSubmitOperator` is a fire-and-forget batch submission. Long-running streaming under it ties up an Airflow worker slot indefinitely; task heartbeat and Spark heartbeat fight; restart-on-failure semantics are confused (does the DAG run retry? does the streaming query retry from checkpoint? both?).
- **Rejected because:** mixing process supervision with orchestration is a documented anti-pattern that causes production incidents.

### Alternative B: Continuous DAG with a sensor loop
- **Pros:** Stays inside Airflow.
- **Cons:** Fights Airflow's batch execution model; scheduler and webserver consume resources babysitting a process that should be supervised by something else.
- **Rejected because:** wrong abstraction — Airflow is not a process supervisor.

### Alternative C: Kubernetes Deployment (managed by ArgoCD or equivalent)
- **Pros:** Production-correct for a real carrier deployment; clean process supervision; rolling updates.
- **Cons:** Overkill for a portfolio project; adds a third operational platform (Airflow, Databricks, K8s).
- **Decision:** documented as the production target; not implemented in Polaris's portfolio scope. Databricks Jobs `Continuous` mode is the equivalent for this project's runtime.

### Alternative D: Databricks Delta Live Tables (DLT)
- **Pros:** Declarative; built-in supervision; quality expectations integrated.
- **Cons:** Vendor-specific (more so than Delta itself); abstracts away the Structured Streaming code we want to *show* in the portfolio; less defensible in interviews where the question is "walk me through your streaming code."
- **Rejected because:** the portfolio's purpose is to show explicit Structured Streaming + checkpoint logic, not to hide it.

## Consequences

### Positive
- **No race conditions** between Airflow restart logic and Spark checkpoint recovery.
- **Single-pane-of-glass alerting** preserved — Airflow still pages on streaming staleness, even though it doesn't manage the process.
- **Right tool for each job** — Airflow does orchestration; Databricks Jobs (or systemd / K8s in prod) does process supervision.
- **Interview-defendable separation** — answers the "how do you handle streaming in Airflow?" question with the senior answer ("I don't — and here's why").

### Negative / accepted trade-offs
- **Two operational paradigms** to learn and document. Mitigated by the heartbeat DAG providing a unified alert surface.
- **Manual recovery** if the streaming job dies — though automatic restart is configured at the runtime layer, not Airflow.

### Mitigations
- `docs/runbooks/streaming-job-down.md` (to be written) walks through diagnosis: check Databricks Job UI → checkpoint health → Kafka consumer lag → restart procedure.
- The heartbeat DAG's alert message links directly to the runbook.

## Revisit triggers

- We adopt Delta Live Tables for the streaming layer (re-evaluates the explicit-vs-declarative trade-off).
- We move to Kubernetes and unify orchestration + supervision under a single workflow engine like Argo Workflows or Temporal.
- Airflow gains first-class long-lived task support that genuinely solves the supervision problem (unlikely given Airflow 3's direction).
