# SageCommand V3 Canonical Event Model

## Overview

The **Canonical Event Model** represents the foundational, immutable ledger for all occurrences within the SageCommand V3 industrial operations environment. It provides a standardized data contract for capturing events ranging from simple telemetry updates and state changes to critical security incidents and anomaly detections.

This model is strictly observational. 

### Explicit Non-Goals
- **No Execution**: The event model does not execute actions. It records them. Execution is handled exclusively by the Execution Gateway.
- **No Message Brokers (Yet)**: The current V3 foundation persists events to a deterministic, append-only SQLite repository. It does not introduce distributed message queues (like Kafka or RabbitMQ) in the foundation layer, focusing first on data correctness and immutable contracts.
- **No Implicit State Mutations**: Writing an event does not automatically mutate the digital twin or knowledge graph. It simply logs that an observation occurred.

## Core Characteristics

### 1. Deterministic Fingerprinting
Every event generates a deterministic cryptographic fingerprint (`SHA-256`) based on its canonical properties (tenant, category, type, occurrence time, provenance, and payload). 

This solves the distributed observability problem of duplicate event processing. If the exact same physical event is reported multiple times (e.g., due to network retries), the fingerprint deduplicates it at the storage layer, ensuring true idempotency.

### 2. Tenant & Scope Isolation
Every event belongs to an authoritative `tenant_id`. Queries strictly bound to the tenant layer, and cryptographic hashes integrate the tenant ID, ensuring that fingerprints are isolated across tenants. Further scope isolation is provided by `workspace_id` and `plant_id`.

### 3. Temporal Semantics
Events track time in three distinct phases:
- `occurred_at`: When the event physically or logically happened at the edge.
- `observed_at`: When the event was detected or processed by the system.
- `recorded_at`: When the event was permanently committed to the immutable ledger.

### 4. Rich Referencing
Events link directly to V3 domain entities via the `EventReferences` schema:
- `ontology_id`
- `twin_id`
- `kg_node_id`
- `anomaly_id`

## Schemas

### EventLifecycle
- `RECORDED`: The default state upon entry.
- `ACTIVE`: The event represents an ongoing state.
- `RESOLVED`: The event condition has concluded.
- `SUPERSEDED`: A newer event has overridden this one.
- `INVALIDATED`: The event was determined to be a false positive or erroneous observation.

### EventSeverity
- `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`

### EventCategory
Broad classifications including: `SYSTEM`, `TELEMETRY`, `STATE_CHANGE`, `ANOMALY`, `QUALITY`, `MAINTENANCE`, `PRODUCTION`, `INVENTORY`, `SECURITY`, `OPERATOR`, `SIMULATION`, `KNOWLEDGE`, `TWIN`.

## API Layer

The event routes provide tenant-isolated, bounded querying capabilities:
- `POST /api/v3/events`: Record a new event (idempotent via fingerprint).
- `GET /api/v3/events`: Bounded list query with strict limit (max 500) and tenant isolation.
- `GET /api/v3/events/{event_id}`: Retrieve by unique identifier.
- `GET /api/v3/events/fingerprint/{fingerprint}`: Retrieve by deterministic fingerprint.
