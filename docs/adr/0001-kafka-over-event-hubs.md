# ADR-0001: Use Apache Kafka (Docker) over Azure Event Hubs for FNOL streaming

**Status:** Accepted
**Date:** 2026-05-14
**Decision-makers:** Polaris architecture (single-author portfolio project)

## Context

Polaris streams First-Notice-of-Loss (FNOL) events from claim-intake channels into a Silver fraud-signal table with sub-minute end-to-end latency. The streaming layer must satisfy five constraints:

1. **Exactly-once semantics** from producer through to the Silver Delta table. Duplicate FNOL events would inflate fraud scores and trigger false-positive SIU alerts — operationally expensive and credibility-damaging.
2. **Schema registry support** for Avro/Protobuf evolution. Claim event schemas change quarterly as new product lines launch (e.g. cyber, pet, gig-economy auto), and producers across the carrier need a single source of truth for compatibility rules.
3. **Cloud portability.** The production target carrier may run multi-cloud or migrate; consumer code must not be locked to a vendor protocol.
4. **Local-laptop runnability** with zero cloud spend. This project develops on a $200 Azure credit budget, and CI must run the full streaming pipeline without provisioning real cloud resources.
5. **Interview defensibility.** The producer/consumer code must match the Kafka literacy that constitutes the senior-DE baseline at every Toronto-market employer the author is targeting.

The platform is otherwise Azure-native (ADLS, Databricks, Key Vault), which would normally make Azure Event Hubs the path-of-least-resistance choice. Event Hubs offers a Kafka-compatible endpoint ("Event Hubs for Kafka") which superficially solves constraint 3.

## Decision

Use **Apache Kafka 3.7 in Docker** (KRaft mode, three-broker cluster) with the **Confluent Schema Registry** for the FNOL streaming layer. Producers and consumers use the official `confluent-kafka` Python and JVM clients with `enable.idempotence=true` and transactional writes (`transactional.id` set per producer instance).

## Alternatives considered

### Alternative A: Azure Event Hubs (native AMQP API)
- **Pros:** Fully managed; integrates with Azure RBAC and Event Grid; the "Capture" feature lands events directly into ADLS without a consumer.
- **Cons:** No native schema registry (Schema Registry is preview-only on Event Hubs and lags Confluent's feature set significantly). No transactional producer API on the AMQP path. Partition-key-based ordering only. Vendor lock-in — consumer code is not portable.
- **Rejected because:** the lack of a transactional producer API breaks our exactly-once guarantee at the source, and Capture-to-ADLS bypasses our Schema-Registry-backed contract enforcement.

### Alternative B: Event Hubs for Kafka (Kafka-protocol endpoint on Event Hubs)
- **Pros:** Same Kafka client code as Alternative C below, but managed. Avoids broker operations.
- **Cons:** Implements only a subset of the Kafka API — no transactions, no exactly-once across topics, no compacted topics, no end-to-end idempotent producer guarantees. Schema Registry is a separate add-on with limited tooling. Cost model (throughput units) is unpredictable under burst FNOL load. Consumer offsets behave subtly differently from open-source Kafka, producing hard-to-debug at-least-once duplicates in `foreachBatch` Spark sinks.
- **Rejected because:** the API gaps directly break the exactly-once requirement, and the runtime divergence from real Kafka means I cannot defend my exactly-once design in an interview without caveats — which is a self-inflicted weakness for the portfolio's primary purpose.

### Alternative C: Apache Kafka (self-managed in Docker / Kubernetes)
- **Pros:** Full Kafka API including transactions and idempotent producers. First-class Confluent Schema Registry support. Identical client code from laptop to production. Zero cost on a developer laptop. The skill set transfers to every employer running Kafka.
- **Cons:** Broker operations are the team's problem. KRaft mode (no ZooKeeper) is recent — we accept the operational learning curve.
- **Selected.**

### Alternative D: Azure Service Bus
Not seriously considered. Service Bus is a message broker, not a streaming platform — no log retention, no consumer-group rewind, no replay for backfills. None of these are negotiable for an event-time streaming workload.

### Alternative E: Confluent Cloud (managed Kafka)
- **Pros:** Real Kafka API with managed broker ops; Schema Registry included.
- **Rejected because:** local-laptop runnability constraint (constraint 4) — Confluent Cloud has no free local runtime, and the free tier still requires cloud connectivity. Revisit if the project moves to a hosted demo environment (see revisit triggers).

## Consequences

### Positive
- **Exactly-once end-to-end** is achievable: Kafka transactional producer → Spark Structured Streaming `foreachBatch` with idempotent Delta MERGE on `event_id`.
- **Schema evolution** is governed by Confluent Schema Registry with explicit BACKWARD compatibility mode; producers cannot publish breaking changes without a new subject version.
- **Zero cloud cost** for local development; CI runs the full streaming pipeline against an in-process Kafka via testcontainers.
- **Portable consumer code** — works against any Kafka-compatible broker (Confluent Cloud, MSK, Strimzi on AKS, on-prem) without modification.

### Negative / accepted trade-offs
- I own broker operations: rolling restarts, partition rebalancing, retention sizing, JVM tuning. For a single-developer portfolio this is acceptable and is itself a learning artifact.
- The local Kafka cluster is **not highly available** — single Docker host. A production deployment would require Confluent Cloud, Strimzi on AKS, or another managed offering.
- Cross-region disaster recovery requires MirrorMaker 2 or Confluent Replicator; neither is configured in this project.

### Mitigations
- `infra/docker/kafka/docker-compose.yml` pins the broker version and JVM flags so behavior is reproducible across machines.
- `docs/runbooks/kafka-consumer-lag.md` documents recovery from lag spikes.
- The Spark streaming job's checkpoint location is documented and recovery from broker loss is exercised in the test suite.

## Revisit triggers

- **Sustained throughput exceeds 50k msg/sec** → reconsider Confluent Cloud to offload broker ops.
- **Single-cloud Azure mandate** → revisit Event Hubs for Kafka, accept the at-least-once compromise, and document explicit duplicate-handling at the Silver MERGE.
- **Schema Registry feature parity** on Event Hubs (transactions, subject-level compatibility modes, deletion semantics) → reconsider.
- **Project moves to a hosted demo environment** with always-on cloud connectivity → Confluent Cloud becomes viable.
