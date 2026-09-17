# SageCommand V3 — Incident Management Foundation (Prompt 18)

## 1. Overview & Core Philosophy

The **SageCommand V3 Incident Management subsystem** provides an authoritative, structured, and tenant-isolated operational case tracking foundation. It represents an operational situation requiring tracking, human ownership, investigation, communication, or resolution.

> [!IMPORTANT]
> **Core Architectural Boundary**:
> Prompt 18 provides incident tracking and lifecycle management. It does **not** determine root cause and does **not** execute physical remediation.
> - **Prompt 19** owns the future **Root-Cause Analysis (RCA)** engine.
> - **Deterministic Execution Gateway & Action API** own physical operational write boundaries and safety checks.
> - Incident Management is strictly an operational tracking and lifecycle domain.

---

## 2. Incident vs. Event Model

A fundamental invariant of SageCommand V3 is the separation between Events and Incidents:

| Attribute | Canonical Event (Prompt 16) | Operational Incident (Prompt 18) |
| :--- | :--- | :--- |
| **Concept** | Something that happened, was observed, detected, or recorded at a specific instant. | An operational situation tracked over time requiring investigation, ownership, and triage. |
| **Mutability** | **Immutable**: Never updated or deleted after persistence. | **Mutable Case Record**: Lifecycle transitions, metadata updates, and ownership assignments mutate current record state while recording append-only history. |
| **Cardinality** | Atomic single telemetry point, threshold breach, or message. | References one or multiple canonical events, anomalies, and operational evidence records. |
| **Identity** | Deterministic cryptographic SHA-256 fingerprint from immutable event fields. | Unique incident ID (`inc_...`) with optional deterministic deduplication key fingerprint. |

---

## 3. Canonical Incident Contract

Defined in `backend/data/schemas/incident_contract.py`:

- **Identity**:
  - `incident_id`: Unique deterministic ID (`inc_<hex>`).
  - `incident_fingerprint`: Deduplication SHA-256 hash based on `tenant_id | category | deduplication_key`.
  - `schema_version`: Constant `"3.0"`.
- **Scope**:
  - `tenant_id`: Mandatory tenant isolation boundary.
  - `workspace_id`: Optional workspace boundary.
  - `plant_id`: Optional plant site boundary.
- **Classification & Assessment**:
  - `category`: `OPERATIONAL`, `SAFETY`, `QUALITY`, `MAINTENANCE`, `PRODUCTION`, `INVENTORY`, `SECURITY`, `INFRASTRUCTURE`, `SYSTEM`, `OTHER`.
  - `severity`: Describes operational impact (`INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - `priority`: Describes handling attention order (`LOW`, `NORMAL`, `HIGH`, `URGENT`).
- **Timestamps**:
  - `detected_at`: Timestamp when the condition was observed.
  - `opened_at`: Timestamp when the incident was created.
  - `acknowledged_at`: Timestamp when an operator acknowledged the incident.
  - `resolved_at`: Timestamp when lifecycle reached `RESOLVED`.
  - `closed_at`: Timestamp when lifecycle reached `CLOSED`.
  - `updated_at`: Timestamp of most recent mutation.
- **Ownership**:
  - `assigned_user`: Individual owner identity.
  - `assigned_team`: Department or response team identity.
  - `acknowledged_by`: Authenticated identity that acknowledged the incident.
- **Concurrency**:
  - `version`: Monotonically increasing integer for optimistic concurrency protection.

---

## 4. Deterministic Lifecycle State Machine

Valid lifecycle states: `OPEN`, `ACKNOWLEDGED`, `INVESTIGATING`, `MITIGATED`, `RESOLVED`, `CLOSED`, `REOPENED`, `CANCELLED`.

```
          ┌─────────────┐
          │    OPEN     │
          └──────┬──────┘
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
┌──────────────┐    ┌─────────────┐
│ ACKNOWLEDGED │    │  CANCELLED  │ (Terminal)
└──────┬───────┘    └─────────────┘
       │
       ▼
┌──────────────┐
│INVESTIGATING │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  MITIGATED   │
└──────┬───────┘
       │
       ▼
┌──────────────┐         ┌──────────┐
│   RESOLVED   │ ◄─────► │ REOPENED │
└──────┬───────┘         └──────────┘
       │
       ▼
┌──────────────┐
│    CLOSED    │
└──────────────┘
```

- Invalid transitions (such as direct `OPEN -> RESOLVED`) are strictly rejected with HTTP 400.
- `RESOLVED` and `CLOSED` incidents may transition to `REOPENED` if operational issues recur.

---

## 5. Audit History & Deterministic Timeline

1. **Append-Only History (`incident_history`)**:
   Every state transition preserves:
   - `incident_id`
   - `previous_state`
   - `new_state`
   - `actor`
   - `timestamp`
   - `reason`
2. **Deterministic Timeline (`incident_timeline`)**:
   Captures all incident activities in sequence:
   - `CREATED`, `EVENT_ASSOCIATED`, `EVIDENCE_ADDED`, `LIFECYCLE_TRANSITION`, `ASSIGNMENT_CHANGED`, `SEVERITY_CHANGED`, `PRIORITY_CHANGED`, `NOTE_ADDED`.
   - Deterministic sorting: ordered by `timestamp ASC`, with `entry_id ASC` as the tie-breaker.

---

## 6. Associations & References

- **Canonical Events (`incident_events`)**:
  - Mapped via `incident_id` and `event_id` with relationship labels: `TRIGGER`, `SUPPORTING`, `RELATED`, `FOLLOW_UP`, `RESOLUTION`.
  - Associations are idempotent; duplicate attempts do not corrupt state.
  - **Cross-tenant event associations are strictly blocked**.
- **Evidence References (`incident_evidence`)**:
  - Supported evidence types: `EVENT`, `ANOMALY`, `TWIN_STATE`, `KNOWLEDGE_GRAPH`, `DATA_QUALITY`, `OPERATOR_NOTE`, `EXTERNAL_REFERENCE`.
  - Cross-tenant references in metadata are validated and rejected.
  - Payloads are bounded to a maximum of 32KB JSON metadata.
- **Operator Notes (`incident_notes`)**:
  - Bounded to 4096 characters per note.
  - Authentic author attribution from authenticated identity context.

---

## 7. Security, RBAC, and ABAC Integration

### Canonical Permissions
Registered in `authorization_service.py`:
- `incidents.read`: View incidents, timelines, evidence, and notes.
- `incidents.create`: Create new incident records.
- `incidents.update`: Modify severity, priority, or associate events.
- `incidents.assign`: Assign or reassign incident owners and teams.
- `incidents.acknowledge`: Dedicated permission to acknowledge incidents.
- `incidents.transition`: Transition incident lifecycle states.
- `incidents.evidence.write`: Attach evidence references.
- `incidents.notes.write`: Add operator notes.
- `incidents.admin`: Administrative authority over incident configuration.

### System Roles
- `VIEWER`: Granted `incidents.read`.
- `OPERATOR`: Granted `incidents.create`, `incidents.acknowledge`, `incidents.transition`, `incidents.update`, `incidents.assign`, `incidents.evidence.write`, `incidents.notes.write`.
- `PLANT_MANAGER`, `ADMINISTRATOR`, `SECURITY_ADMIN`: Granted `incidents.admin`.

### Multi-Tenant Isolation
All repository queries and service methods require `tenant_id`. Cross-tenant retrieval, modification, event association, or evidence attachment fails closed with HTTP 404 or ValueError.

---

## 8. Controlled Frontend Incident Management UI

The frontend component `frontend/app/components/IncidentModal.tsx` provides a controlled, interactive incident management workspace:
- **Acknowledge Incident**: One-click acknowledgement button for `OPEN` incidents.
- **Lifecycle Transition**: Contextual dropdown displaying only valid transitions from the current state with reason input.
- **Ownership Assignment**: Inline user and team assignment controls.
- **Severity & Priority Adjustments**: Selectors to update operational assessment.
- **Operator Notes Ledger**: Threaded notes feed with character-counter form.
- **Event Linker**: Interface to associate canonical Prompt 16 events.
- **Evidence Reference Attacher**: Interface to link anomalies, twin states, and external references.
- **Incident Creator**: Controlled dialog to register new operational cases.

### Strict Execution Isolation Guardrails
The UI explicitly does **NOT** expose:
- Action API execution
- Execution Gateway controls
- Physical machine, PLC, or actuator controls
- Rollback mechanisms
- Autonomous remediation buttons
- Root-cause analysis or causal inference algorithms
- Blast-radius intelligence calculations
