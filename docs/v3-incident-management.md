# SageCommand V3 — Incident Management Foundation

## Overview
The Incident Management subsystem in SageCommand V3 provides an immutable, tenant-isolated record of operational and security cases. It establishes the "source of truth" for what happened, when it happened, and who was involved, explicitly decoupled from the physical execution systems that might automate remediation.

## Core Principles
1. **Tenant Isolation**: Complete logical separation of incident data. Every operation requires a valid `tenant_id`.
2. **Strict Separation of Duties**: Incident Management tracks state, evidence, and timelines. It **does not** perform root-cause analysis (owned by Prompt 19) or trigger physical execution/remediation (owned by Execution Gateway).
3. **Immutability & Provenance**: Incidents have an append-only timeline. Transitions, notes, and evidence are strictly tracked by user/actor.
4. **Deterministic Identity**: Deduplication keys ensure idempotent creation of incidents from external triggers.

## Architecture

### 1. Data Contracts
Located in `backend/data/schemas/incident_contract.py`:
- `IncidentContract`: The core domain model.
- `IncidentLifecycle`: State machine (`OPEN`, `ACKNOWLEDGED`, `INVESTIGATING`, `MITIGATED`, `RESOLVED`, `CLOSED`).
- `IncidentTimelineEntry`: Immutable ledger of all state changes, evidence, and notes.

### 2. Incident Repository
Located in `backend/services/incident_repository.py`:
- Backed by SQLite (`SAGE_INCIDENT_DB_PATH`) using WAL mode for concurrency.
- Enforces optimistic concurrency control using a `version` integer to prevent lost updates during simultaneous triage.

### 3. Incident Service
Located in `backend/services/incident_service.py`:
- Encapsulates business logic, state transitions, and timeline generation.
- Enforces strict validations (e.g., cannot transition from `OPEN` straight to `RESOLVED` without appropriate steps, or cannot alter incidents belonging to another tenant).

### 4. API Endpoints
Located in `backend/api/incident_routes.py`:
- `POST /api/v3/incidents`: Create a new incident.
- `GET /api/v3/incidents`: List incidents (with tenant-scoped authorization).
- `GET /api/v3/incidents/{id}`: Retrieve full incident details including the timeline.
- `PATCH /api/v3/incidents/{id}/lifecycle`: Advance the incident state.
- `POST /api/v3/incidents/{id}/notes`: Add a note.
- `POST /api/v3/incidents/{id}/evidence`: Attach evidence or associate related events.

## Integration with ABAC
The API endpoints are secured by the core ABAC system, utilizing permissions like:
- `incidents.create`
- `incidents.read`
- `incidents.transition`
- `incidents.update`

## Concurrency
Optimistic locking ensures that if two operators attempt to acknowledge or transition an incident simultaneously, only one succeeds, and the other receives a 409 Conflict.

## UI Component
A diagnostic React component `IncidentModal.tsx` is provided in the frontend to inspect incident timelines and current state.
