# SageCommand V3 — Digital Twin Foundation

The **Digital Twin Foundation** (Prompt 13) introduces the deterministic virtual operational state layer for SageCommand OS V3. 

Building upon the Industrial Ontology (identity and structure) and the Operational Knowledge Graph (context and relationships), the Digital Twin maintains the high-fidelity, versioned state of physical and operational assets.

## Cardinal Invariant: Isolation from Execution

The Digital Twin is strictly a **state representation and simulation context layer**. It is explicitly isolated from the execution pipeline. 

- **No Actuation:** The twin cannot turn on machines, move robots, or write to PLCs.
- **Fail-Safe Isolation:** The twin has ZERO imports of `ExecutionGateway`, `Action`, or `ActionStatus`. 
- **Read-Only Context:** The twin can read from the Ontology and Knowledge Graph but cannot mutate operational configuration or canonical facts through those paths.

## Core Capabilities

1. **State Ingestion & Versioning**
   - Observations are strictly typed (String, Integer, Float, Boolean, Enum, Timestamp, JSON).
   - Every property update creates an immutable `TwinStateVersion` with monotonic `version_id`.
   - Supports deterministic out-of-order resolution using `effective_at` vs `recorded_at` timestamps.

2. **Classification & Provenance**
   - States are classified as `OBSERVED`, `SIMULATED`, `DERIVED`, or `UNKNOWN`.
   - Full provenance tracking via `source_type` (e.g., `SENSOR_TELEMETRY`, `API`, `SYSTEM`) and `source_id`.

3. **Freshness & Validity**
   - States are evaluated dynamically as `FRESH`, `STALE`, or `EXPIRED` based on `recorded_at` thresholds (configurable via `SAGE_DT_FRESHNESS_STALE_SECONDS` and `SAGE_DT_FRESHNESS_EXPIRED_SECONDS`).

4. **Temporal Reconstruction**
   - Retrieves the precise deterministic state of an entity at any timestamp in the past (`get_state_at_time`).

5. **Snapshots & Scenarios**
   - **Snapshots:** Immutable point-in-time capture of the state across multiple entities.
   - **Scenarios:** Isolated, what-if workspaces built on top of a snapshot. Changes in a scenario do not affect the observed real-world state.

6. **State Comparison**
   - Compute structural diffs between two snapshots, a snapshot and current state, or between scenarios.

## UI Integration

The `DigitalTwinModal` provides a visual interface to explore:
- Current State and Properties (with freshness indicators and types).
- State Version History.
- Snapshot and Scenario metadata.

## Backend Architecture

- **Domain Models:** `backend/data/schemas/digital_twin_contract.py`
- **Service:** `backend/services/digital_twin_service.py` (Thread-safe, handles versioning and freshness logic)
- **Repository:** `backend/services/digital_twin_repository.py` (SQLite, strict tenant isolation)
- **API Routes:** `backend/api/digital_twin_routes.py` (REST endpoints)

All state changes are persistently logged in a dedicated, tenant-partitioned SQLite database (`sage_digital_twin.sqlite`).
