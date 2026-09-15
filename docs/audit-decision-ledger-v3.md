# SageCommand V3 — Audit & Decision Ledger Architecture

**Document Version**: 1.0  
**Specification**: SageCommand V3 — Prompt 08: Audit & Decision Ledger  
**Status**: ACTIVE & IMPLEMENTED  
**Date**: September 14, 2026  

---

## 1. Executive Summary & Foundational Invariants

The **Audit & Decision Ledger** is the authoritative, immutable, append-only historical recording layer of SageCommand V3. It provides a tamper-evident record of all system events, AI proposals, authorization evaluations, policy outcomes, simulation previews, human approvals, and operational state transitions.

### 1.1 Architectural Boundary & Separation of Duties

The system strictly enforces the cardinal architectural invariant:

$$\text{Authentication} \neq \text{Authorization} \neq \text{Policy} \neq \text{Approval} \neq \text{Execution} \neq \text{Ledger}$$

- **Authentication**: Verifies identity and issues identity credentials.
- **Authorization**: Evaluates RBAC + ABAC permissions and attributes.
- **Policy Engine**: Determines whether an action conforms to deterministic safety rules (`ALLOW`, `DENY`, `HOLD`, `REQUIRE_APPROVAL`).
- **Approval Layer**: Verifies human-in-the-loop authorization without self-approval.
- **Execution Gateway**: Enforces the execution boundary (remains strictly `405 Method Not Allowed`).
- **Audit & Decision Ledger**: **Passive and observational**. The ledger records facts, lineage, and cryptographic hashes; it never authorizes, mutates, or executes operations.

```
       [ Client / Operator / Agent ]
                     │
                     ▼
          [ Authentication (AuthN) ]
                     │
                     ▼
          [ Authorization (AuthZ) ] ──────────┐
                     │                         │
                     ▼                         │
            [ Structured Action ]              ▼
                     │                 ┌───────────────┐
                     ▼                 │  AUDIT &      │
          [ Policy Engine (Rules) ] ──▶│  DECISION     │
                     │                 │  LEDGER       │
                     ▼                 │  (Append-Only │
          [ Simulation Preview ] ─────▶│   Tamper-     │
                     │                 │   Evident     │
                     ▼                 │   SQLite)     │
          [ HITL Approval / Hold ] ───▶│               │
                     │                 └───────────────┘
                     ▼                         ▲
         [ Future Execution Engine ] ──────────┘
           (STATUS: 405 RESTRICTED)
```

---

## 2. Canonical Domain Schemas & Event Taxonomy

The ledger is governed by standard schemas defined in `backend/data/schemas/ledger_contract.py`.

### 2.1 Event Taxonomy & Categories

| Event Category | Canonical Event Types | Description |
| :--- | :--- | :--- |
| **SYSTEM** | `SYSTEM_STARTUP`, `SYSTEM_SHUTDOWN`, `CONFIG_CHANGE` | Core platform lifecycle and configuration transitions |
| **SECURITY** | `SECURITY_ALERT`, `INTRUSION_DETECTED`, `CREDENTIAL_ROTATED` | Threat intelligence, blast radius anomalies, and credential events |
| **AUTHENTICATION** | `AUTH_LOGIN_SUCCESS`, `AUTH_LOGIN_FAILURE`, `AUTH_TOKEN_ISSUED`, `AUTH_LOGOUT` | User session creation, validation failures, and terminations |
| **AUTHORIZATION** | `AUTHZ_EVALUATION`, `AUTHZ_PERMITTED`, `AUTHZ_DENIED`, `ROLE_ASSIGNED` | RBAC + ABAC decisions, scope validations, and clearance checks |
| **POLICY** | `POLICY_EVALUATION`, `POLICY_ALLOW`, `POLICY_DENY`, `POLICY_HOLD`, `POLICY_APPROVAL_REQUIRED` | Deterministic safety rule evaluations from the Policy Enforcement Engine |
| **ACTION** | `ACTION_PROPOSED`, `ACTION_VALIDATED`, `ACTION_REJECTED`, `ACTION_SIMULATION_COMPLETED`, `ACTION_CANCELLED`, `ACTION_EXECUTED` | Lifecycle transitions of structured operational actions |
| **DATA_GATEWAY** | `DB_CONNECTION_CREATED`, `DB_QUERY_EXECUTED`, `DB_CONNECTION_ERROR` | Database connection lifecycle, read-only SQL profiling, and gateway errors |
| **EVIDENCE** | `EVIDENCE_LINKED`, `TELEMETRY_RECORDED` | Telemetry anomalies, sensor snapshots, and grounding artifacts |

### 2.2 Actor Model & AI Model Provenance

Every event records a structured `LedgerActor` defining the identity and role responsible for the operation:
- `HUMAN`: Interactive human operator, manager, or auditor (`actor_id`, `acting_user_id`).
- `AGENT`: AI agent or LLM copilot proposing actions (`actor_id`, `model_provenance`).
- `SYSTEM`: Platform daemon or automated background worker.
- `POLICY_ENGINE`: Deterministic policy evaluator.
- `GATEWAY`: Database or external integration gateway.

When an AI agent initiates an operation, `ModelProvenance` captures:
- `model_name` (e.g., `gpt-4o`, `claude-3-5-sonnet`, `gemini-1.5-pro`)
- `provider` (e.g., `openai`, `anthropic`, `google`)
- `prompt_tokens` & `completion_tokens`
- `prompt_template_id`
- `reasoning_summary`

### 2.3 Evidence & Grounding References

Operational actions and AI recommendations must reference authoritative evidence items:
- `provenance_type`: `DATABASE_READ`, `TELEMETRY_SNAPSHOT`, `SENSOR_READING`, `OPERATOR_INPUT`, `POLICY_DOCUMENT`, `COMPLIANCE_RECORD`.
- `source_uri`: Canonical URI of the source evidence (e.g., `db://plant_001/telemetry/vibration`).
- `sha256_fingerprint`: Cryptographic hash of the raw telemetry snapshot or document.
- `recorded_at`: Timestamp of evidence capture.

---

## 3. Cryptographic Tamper-Evidence & Hash Chaining

The ledger guarantees data integrity through SHA-256 hash chaining.

### 3.1 Event Hash Computation

Every `LedgerEvent` computes a deterministic SHA-256 hash of its canonical normalized representation:
$$\text{event\_hash} = \text{SHA256}(\text{tenant\_id} \parallel \text{event\_type} \parallel \text{occurred\_at} \parallel \text{actor\_id} \parallel \text{previous\_event\_hash} \parallel \text{payload\_json})$$

### 3.2 Tenant Hash Chain

- Each tenant maintains an ordered sequence of events.
- When recording an event, the system retrieves the `event_hash` of the immediately preceding event for that tenant (`previous_event_hash`).
- Genesis events set `previous_event_hash = None`.
- Any external modification, deletion, or reordering of SQLite records breaks the cryptographic hash chain, allowing verification audits to detect tampering immediately.

---

## 4. Security Redaction & Payload Bounding

To prevent credential leakage and resource exhaustion, all incoming event payloads undergo strict sanitization before storage.

### 4.1 Recursive Deep Redaction

The `sanitize_payload` engine (`backend/governance/redaction.py`) recursively scrubs data structures:
1. **Sensitive Key Redaction**: Any dictionary key matching `password`, `secret`, `token`, `key`, `authorization`, `dsn`, `connection_string`, `private`, `credential`, `pin`, `cvv` has its value replaced with `"[REDACTED]"`.
2. **Bearer Token Scrubbing**: Text values matching `Bearer [A-Za-z0-9\-\._~\+\/]+=*` are scrubbed.
3. **Connection URI Password Scrubbing**: URIs with embedded credentials (e.g., `postgres://user:password@host/db`) have passwords replaced with `postgres://user:***@host/db`.

### 4.2 Payload Size Bounding

Event payloads are bounded by `SAGE_AUDIT_MAX_PAYLOAD_SIZE` (default: 65,536 bytes / 64 KB). Payloads exceeding this threshold are truncated with an explicit `_truncated: True` flag and warning annotation.

---

## 5. Decision Lineage Reconstruction (`DecisionRecord`)

To understand the full provenance of operational actions, the ledger provides the high-level `DecisionRecord` graph:

```json
{
  "action_id": "act_01JABC...",
  "tenant_id": "tenant_001",
  "workspace_id": "workspace_001",
  "action_type": "SETPOINT_ADJUSTMENT",
  "status": "APPROVED",
  "data_mode": "SIMULATION",
  
  "proposal_event": { ... },
  "authorization_decision": { ... },
  "policy_evaluation": { ... },
  "simulation_event": { ... },
  "evidence_references": [ ... ],
  
  "approval_id": "NOT_AVAILABLE",
  "execution_id": "NOT_AVAILABLE",
  "verification_id": "NOT_AVAILABLE"
}
```

### 5.1 Explicit Boundary Invariant

In strict compliance with the Prompt 05–08 execution boundary:
- Real-world operational execution is not implemented.
- `approval_id`, `execution_id`, and `verification_id` remain explicitly `"NOT_AVAILABLE"`.
- Execution states (`EXECUTING`, `SUCCEEDED`, `FAILED`, `ROLLED_BACK`) are strictly uninstantiated.

---

## 6. Storage & Concurrency Architecture

### 6.1 Dedicated SQLite Database

Audit records are stored in a dedicated, durable SQLite database:
- Configured via `SAGE_AUDIT_LEDGER_DB_PATH` (default: `sage_audit_ledger.sqlite`).
- Ephemeral LangGraph checkpoints in `sage_memory.sqlite` and operational actions in `sage_actions.sqlite` are physically isolated from audit records.
- WAL (Write-Ahead Logging) mode and thread-safe locking (`threading.Lock`) prevent concurrency deadlocks.

### 6.2 Table Schema (`audit_ledger_v3`)

```sql
CREATE TABLE IF NOT EXISTS audit_ledger_v3 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    plant_id TEXT,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    event_status TEXT NOT NULL,
    data_mode TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    acting_user_id TEXT,
    action_id TEXT,
    correlation_id TEXT,
    causation_id TEXT,
    occurred_at TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    previous_event_hash TEXT,
    payload_json TEXT NOT NULL,
    evidence_json TEXT,
    provenance_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Indexed on `tenant_id`, `occurred_at`, `action_id`, `event_type`, `category`, and `actor_id`.

---

## 7. Canonical API Contract

All ledger query endpoints are hosted under `/api/v3/audit` and require authentication and the `audit.read` permission.

### 7.1 Security Invariant: No Client Ingestion

To prevent external client forgery, **there is NO client-facing event creation endpoint** (`POST /api/v3/audit/events` is strictly omitted). All events are recorded server-side by authoritative services (`AuditLedgerService`).

### 7.2 Read Endpoints

| Method | Endpoint | Query Parameters | Description | Required Permission |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v3/audit/events` | `category`, `event_type`, `action_id`, `actor_id`, `limit`, `offset` | Query paginated events scoped to caller's tenant | `audit.read` |
| `GET` | `/api/v3/audit/events/{event_id}` | none | Retrieve single event by UUID | `audit.read` |
| `GET` | `/api/v3/audit/timeline` | `action_id`, `limit` | Retrieve chronological decision event timeline | `audit.read` |
| `GET` | `/api/v3/audit/decisions/{action_id}` | none | Reconstruct unified decision lineage graph | `audit.read` |

---

## 8. Verification & Test Coverage

The Audit & Decision Ledger is verified by 17 automated tests in `backend/test_v3_audit_ledger.py`:
- `test_record_and_query_event`: Append event, retrieve by ID, verify fields.
- `test_hash_chain_integrity`: Verify SHA-256 chain links consecutive events.
- `test_tenant_isolation`: Confirm tenant data cannot leak across tenant boundaries.
- `test_workspace_and_session_scoping`: Multi-attribute query filtering.
- `test_payload_redaction_secrets`: Verify password, token, and DSN scrubbing.
- `test_payload_size_bounding`: Confirm 64 KB truncation safety.
- `test_concurrent_writes`: Thread-safe concurrent write transactions.
- `test_decision_record_reconstruction`: Lineage stitching across action lifecycle.
- `test_api_query_events_success`: HTTP query verification.
- `test_api_decision_record_success`: HTTP decision graph retrieval.
- `test_api_unauthorized_missing_token`: Rejection on unauthenticated access.
- `test_api_forbidden_missing_permission`: Rejection when lacking `audit.read`.
- `test_execution_boundary_remains_405`: Verification that `POST /api/v3/actions/{id}/execute` remains 405.
