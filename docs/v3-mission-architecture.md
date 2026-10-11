# SageCommand V3 — Mission Architecture Foundation
**Repository:** `joyab786/sage_command_production`  
**Workspace:** `E:\js\sage_command_production`  
**Branch:** `main`  
**Prompt 35 Implementation Commit:** `62f4f3646c63eab903118fe1793e50d5a988149f`  
**Prompt 35 Follow-up Commit:** `7c634f6d94becf888f6a9e0f54eb7c856534a4c6`  
**Prompt 35A Starting Baseline:** `7c634f6d94becf888f6a9e0f54eb7c856534a4c6`  
**Prompt 35A Implementation Commit:** `76f3b3297a3a3c7efb4e7bc2400f834e465f4378`  
**Prompt 35A Documentation Commit:** `08fc1738d35eafcc618596fcd3ef3b8353aad840`  
**Prompt 35A Test Teardown Commit:** `36de22416ec1a533ad03eeb0c169c9b139db080d`  
**Prompt 35B Starting Baseline:** `6dc4c1bbbbc19f8657071231c89b90e25303d55e`  
**Prompt 35B Implementation Commit:** `7cf387f740f53793e59af8609d583da03ca4e945`  
**Prompt 35B Documentation Commit:** `b26eaa94a337f5f483e38557730a0cf04d137fac`  
**Prompt 35B Baseline Final Commit:** `3a2154921a861e8bf33bc86b38ff37859736623d`  

## 1. Mission Domain and Purpose

In **SageCommand V3**, an industrial mission represents a **governed, auditable, bounded operational objective** that organizes work intent across complex industrial domains. A mission coordinates decisions, evidence requirements, structured actions, policy reviews, approvals, and post-outcome verification.

### Core Principle
> **A Mission is a governed representation of an industrial objective and its intended work—NOT permission to execute that work.**

A mission is:
- **NOT** a chatbot conversation or conversational prompt.
- **NOT** a free-form LLM plan.
- **NOT** an execution command, SQL mutation, shell script, or direct PLC/SCADA write.

It formally captures:
- **What** operational objective is pursued (`objective`).
- **Why** it matters (`provenance.origin_reason`, related incidents, or RCAs).
- **What scope and constraints apply** (`scope.plant_id`, `constraints`).
- **What reviewable outcomes define success** (`success_criteria`).
- **Which structured actions or decisions are relevant** (`planned_steps`, `related_resources`).
- **What dependencies exist between steps** (acyclic DAG).
- **What evidence is required** to determine whether objectives have been met (`evidence_requirements`).

```mermaid
flowchart TD
    U[Operator or Agent] --> API[Mission API: /api/v3/missions]
    API --> AUTH[Authentication and Scope Validation]
    AUTH --> MD[Mission Domain: Mission, Steps, DAG, Criteria]
    MD --> VAL[Deterministic Mission Validation: DAG Cycle Detection, Bounds, Anti-Smuggling]
    VAL --> STORE[Mission Repository: SQLite WAL, Composite PK, Idempotency]
    MD --> ACT[Structured Action References]
    MD --> DEC[Decision References]
    MD --> EVID[Evidence and Provenance]
    MD --> MEM[Organizational Memory References]
    STORE --> AUD[Audit and Decision Ledger]
    ACT --> FUTURE[Future Policy and Execution Boundaries]
```

---

## 2. Canonical Architecture Selected

After inspecting the repository, no competing `MissionService`, `MissionRepository`, `MissionRegistry`, `MissionStore`, `MissionEngine`, or `MissionOrchestrator` was found. A stub `MissionObject` existed in `backend/data/schemas/mission.py` for early tests.

The canonical implementation establishes:
- **Contracts:** `backend/data/schemas/mission_contract.py` defining full domain models, DAG validation, and lifecycle transitions. `backend/data/schemas/mission.py` preserves `MissionObject` for backward compatibility while re-exporting the new contracts.
- **Repository:** `backend/repositories/mission_repository.py` backed by SQLite WAL with thread safety (`threading.Lock()`), composite primary key `(tenant_id, workspace_id, mission_id)`, table for `missions`, `mission_revisions`, `mission_audit_ledger`, and `mission_idempotency_records`.
- **Service:** `backend/services/mission_service.py` enforcing authoritative caller identity, fail-closed workspace isolation, plant scope intersections, deterministic DAG validation, immutable revisions, and atomic audit logging.
- **API:** `backend/api/mission_routes.py` exposing 10 versioned REST endpoints rooted at `/api/v3/missions`.
- **Authorization:** `backend/services/authorization_service.py` registering canonical `mission.*` permissions and role assignments across VIEWER, ANALYST, OPERATOR, PLANT_MANAGER, and ADMINISTRATOR.
- **Server Registration:** `backend/server.py` mounts `mission_router` at `/api/v3/missions`.

---

## 3. Mission Schema and Versioning

### Schema Version
`schema_version = "3.0.0"`

### Canonical Fields
```text
mission_id: str                (Unique identifier: msn_<uuid16>)
schema_version: str            (3.0.0)
revision: int                  (Monotonically increasing: 1, 2, 3...)
title: str                     (Bounded, max 256 characters)
description: str               (Bounded, max 4000 characters)
mission_type: MissionType      (Strict allowlist enum)
objective: str                 (Bounded, max 4000 characters)
scope: MissionScope            (Authoritative tenant_id, workspace_id, plant_id, session_id)
constraints: List[...]         (Max 30 structured, reviewable constraints)
success_criteria: List[...]    (Max 30 non-executable conditions, defaults to UNKNOWN)
planned_steps: List[...]       (Max 50 DAG-validated planned work steps)
evidence_requirements: List... (Max 30 typed evidence requirements)
related_resources: Dict...     (Referenced Action proposals, Decisions, Incidents, RCAs, Memories)
data_mode: DataMode            (SIMULATION vs REAL, authoritative server boundary)
status: MissionStatus          (Deterministic lifecycle status)
provenance: MissionProvenance  (Creator, origin reason, incident/RCA parentage)
created_at: str                (ISO-8601 UTC)
updated_at: str                (ISO-8601 UTC)
created_by: str                (Authoritative creator identity)
validation_errors: List[str]   (Deterministic validation findings)
validation_warnings: List[str] (Domain advisory warnings)
review_notes: Optional[str]    (Governance rationale)
reviewed_by: Optional[str]     (Reviewer identity)
reviewed_at: Optional[str]     (Review timestamp)
```

---

## 4. Lifecycle and Transition Map

The mission lifecycle is deterministic and state-machine guarded:

```text
DRAFT ----------> VALIDATED ----------> REVIEW_REQUIRED ----------> ACCEPTED (Terminal accepted)
  |                  |                      |                       |
  v                  v                      v                       v
CANCELLED        CANCELLED               REJECTED               CANCELLED
                                            |
                                            v
                                          DRAFT (Revision)
```

### Transition Table
| Current Status | Allowed Target Statuses | Guard Condition |
| :--- | :--- | :--- |
| `DRAFT` | `PROPOSED`, `VALIDATING`, `VALIDATED`, `CANCELLED` | Validation passes with 0 errors to reach `VALIDATED` |
| `PROPOSED` | `VALIDATING`, `VALIDATED`, `DRAFT`, `CANCELLED` | Same as draft |
| `VALIDATING` | `VALIDATED`, `DRAFT`, `REJECTED`, `CANCELLED` | Validation evaluation |
| `VALIDATED` | `REVIEW_REQUIRED`, `DRAFT`, `CANCELLED` | Requires formal submission |
| `REVIEW_REQUIRED` | `ACCEPTED`, `REJECTED`, `DRAFT`, `CANCELLED` | Governance decision by authorized reviewer |
| `ACCEPTED` | `CANCELLED` | Terminal accepted state; cannot be directly executed or mutated |
| `REJECTED` | `DRAFT`, `CANCELLED` | Can revert to draft for revision |
| `CANCELLED` | None | Terminal state |

---

## 5. Scope and Ownership (Prompt 35A Hardened)

1. **Authoritative Server Identity:** Client-supplied tenant or workspace fields are ignored. Identity is derived strictly from `identity.tenant_id` and `identity.workspace_id`.
2. **Fail-Closed Workspace Isolation:** If `identity.workspace_id` is missing or empty, access is rejected immediately with `403 Forbidden`.
3. **Fail-Closed Plant Authorization:**
   - Any fallback converting empty plant assignments into wildcard access (`getattr(identity, "assigned_plants", ["*"]) or ["*"]`) is strictly removed.
   - Only an explicit, authoritative wildcard assignment (`["*"]`) grants unrestricted plant access.
   - An explicitly empty plant assignment (`[]`), `None`, or missing attribute fails closed immediately across all operations: creation, retrieval, listing, updates, validation, submission, review, cancellation, revision history, and audit retrieval.
   - Plant filtering in `list_missions` is pushed down into database-level SQL queries (`COUNT(*)` and `SELECT *`). Callers cannot query or infer the existence of missions in unauthorized plants through pagination totals or counts.
4. **Cross-Tenant & Cross-Workspace Isolation:** All queries filter on `tenant_id = ? AND workspace_id = ?`. Queries never cross boundaries.

---

## 6. Objectives and Success Criteria (Outcome Integrity)

- Objectives define the operational problem and boundary.
- **Server-Authoritative Status Rules:**
  - For newly proposed missions and draft updates, criterion status must be `UNKNOWN`.
  - Client-supplied values such as `SATISFIED` or `NOT_SATISFIED` are strictly rejected. LLMs and API clients cannot self-certify completion.
  - Client payloads cannot set mission status directly on creation or update (e.g., attempting to pass `status: VALIDATED` or `status: ACCEPTED` is rejected with HTTP 422).
- **Anti-Code Smuggling & Secret Scanning:**
  - All criteria, objectives, descriptions, and titles pass strict regex checks rejecting SQL statements (`SELECT`, `DROP`, `INSERT`), shell commands (`rm -rf`, `curl`, `bash`), and code invocation (`eval(`, `exec(`).
  - Automated regex secret scanners reject embedded credentials, private keys, connection strings with passwords, and bearer tokens.

---

## 7. Planned Steps and Dependencies

A mission represents its planned work as a directed acyclic graph (DAG) of typed steps:
- **Step Types:** `ANALYSIS`, `INVESTIGATION`, `EVIDENCE_COLLECTION`, `ACTION_PROPOSAL`, `DECISION_REQUEST`, `POLICY_CHECK`, `REVIEW`.
- **Server-Authoritative Step Status:**
  - Initial step status must be `PLANNED` or `PENDING`.
  - Client-supplied states such as `IN_PROGRESS`, `COMPLETED`, or `FAILED` are strictly rejected on creation and draft updates without an authorized execution mechanism.
  - A model-generated status is never interpreted as evidence that work occurred.
- **Deterministic DAG Validation:**
  - Detects duplicate step IDs.
  - Enforces dependency existence in planned steps.
  - Rejects self-dependencies.
  - Rejects cyclic dependencies using Kahn's algorithm topological sorting.
  - Enforces bounds: max 50 steps, max 100 total dependencies, max 20 `related_resource_ids` per step, max 20 `required_evidence` items per step.

---

## 8. Resource Reference Validation Against Canonical Systems

Every referenced resource in `related_resources`, `step.related_resource_ids`, `step.required_evidence`, `evidence_requirements[].linked_evidence_id`, and `provenance.parent_*` is validated against canonical subsystems:

1. **Resolution via Approved Repositories:**
   - `actions`: Resolved via `action_store`.
   - `decisions`: Resolved via `DecisionEngineRepository`.
   - `evidence`: Resolved via `evidence_explainability_repository`.
   - `incidents`: Resolved via `IncidentRepository`.
   - `rcas`: Resolved via `RcaRepository`.
   - `memories`: Resolved via `OrganizationalMemoryRepository`.
2. **Authorized Scope Enforcement:**
   - Enforces matching `tenant_id`, `workspace_id`, and `plant_id` against the caller's authorized scope.
   - Cross-tenant and cross-workspace references are rejected fail-closed with a non-disclosing error: `"Resource reference '{res_id}' is invalid or inaccessible in the authorized scope."`
   - Callers assigned only to specific plants cannot reference resources from other plants.
3. **Unsupported Categories Rejected:**
   - Only categories in `SUPPORTED_RESOURCE_CATEGORIES = {"actions", "decisions", "evidence", "incidents", "rcas", "memories"}` are allowed.
   - Any unsupported or arbitrary category string is rejected during schema validation.
4. **Evidence Integrity:**
   - A linked evidence reference does NOT imply that evidence satisfies a criterion or that work has completed.
   - Missing evidence remains missing. Unverified evidence raises a domain warning during validation and never satisfies success criteria.
5. **Untrusted Context Fencing:**
   - When mission data is provided to LLM agents, it is treated as untrusted context with security fences.

---

## 9. Risk and Governance

- LLMs and clients **cannot** set risk classification or waive required human approvals.
- Accepting a mission (`ACCEPTED`) confirms governance acceptance of the plan. It **does NOT** invoke execution.
- Operational actions require separate approval through the canonical Structured Action and Policy boundaries.

---

## 10. Data Mode Enforcement

- Supports `SIMULATION` and `REAL`.
- Default is authoritatively `SIMULATION`.
- Client and LLM inputs **cannot** escalate `SIMULATION` to `REAL`.
- If mode cannot be determined, system fails closed.

---

## 11. Persistence and Revision History

- **Persistence:** SQLite WAL database at `SAGE_MISSION_DB_PATH`.
- **Composite Primary Key:** `(tenant_id, workspace_id, mission_id)`.
- **Immutability:** Once in `VALIDATED`, `REVIEW_REQUIRED`, or `ACCEPTED`, missions cannot be mutated in place. Any update requires creating an explicit revision (`revision = current + 1`).
- **Snapshots:** Each update stores a full JSON snapshot in `mission_revisions`.
- **Optimistic Concurrency:** Updates take an `expected_revision` parameter to prevent concurrent overwrite.

---

## 12. API Contract

Mounted at `/api/v3/missions`:

| Method | Endpoint | Permission | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v3/missions` | `mission.create` | Create draft mission |
| `GET` | `/api/v3/missions/{id}` | `mission.read` | Retrieve mission |
| `GET` | `/api/v3/missions` | `mission.read` | List missions with pagination |
| `PUT` | `/api/v3/missions/{id}` | `mission.update` | Update editable draft |
| `POST` | `/api/v3/missions/{id}/validate` | `mission.validate` | Run deterministic validation |
| `POST` | `/api/v3/missions/{id}/submit` | `mission.update` | Submit validated mission for review |
| `POST` | `/api/v3/missions/{id}/review` | `mission.review` | Accept or reject mission |
| `POST` | `/api/v3/missions/{id}/cancel` | `mission.cancel` | Cancel mission |
| `GET` | `/api/v3/missions/{id}/revisions` | `mission.read` | Retrieve revision snapshots |
| `GET` | `/api/v3/missions/{id}/audit` | `mission.read` | Retrieve audit ledger |

**Strict Rule:** No execution endpoints (`/execute`, `/run`) exist.

---

## 13. Audit and Provenance

All lifecycle mutations write an atomic event to `mission_audit_ledger`:
- `MISSION_CREATED`
- `MISSION_VALIDATION_SUCCEEDED`
- `MISSION_VALIDATION_FAILED`
- `MISSION_SUBMITTED_FOR_REVIEW`
- `MISSION_ACCEPTED`
- `MISSION_REJECTED`
- `MISSION_CANCELLED`
- `MISSION_REVISION_CREATED`
- `MISSION_SCOPE_ACCESS_DENIED`

Records contain `audit_id`, `mission_id`, `revision`, `tenant_id`, `workspace_id`, `plant_id`, `event_type`, `result`, `actor_id`, `actor_role`, `request_id`, `trace_id`, `details`, `timestamp`. Never contains secrets or credentials.

---

## 14. Agent and LangGraph Integration

- Agents can propose missions or analyze mission context.
- All agent output is treated as untrusted input and passes through strict server-side validation.
- Autonomous mission execution is **strictly prohibited** in this prompt.

---

## 15. Frontend and WebSocket Integration

- WebSockets may emit mission lifecycle status events (`MISSION_STATUS_CHANGED`).
- Events are purely notifications, never an execution channel.
- Frontend builds cleanly with zero errors.

---

## 16. Security Review (Prompt 35A Hardened)

| Review Question | Result | Details |
| :--- | :--- | :--- |
| Can an LLM execute a mission directly? | **NO** | No execution methods or endpoints exist. |
| Can a mission bypass the Structured Action boundary? | **NO** | Missions only reference Actions; Action API maintains independent validation. |
| Can an LLM or client self-certify criterion completion? | **NO** | Criterion status must be `UNKNOWN`; `SATISFIED` or `NOT_SATISFIED` input is rejected. |
| Can a client claim completed or in-progress steps? | **NO** | Step status must be `PLANNED` or `PENDING`; execution outcomes rejected on drafts. |
| Can an empty plant assignment grant wildcard access? | **NO** | Fail-closed plant authorization requires explicit `["*"]`; `[]` or `None` denies access. |
| Can unauthorized plants be inferred from pagination? | **NO** | Database-level SQL `COUNT(*)` filters strictly by authorized plants. |
| Can a client forge tenant/workspace/plant identity? | **NO** | Server identity is authoritative; missing workspace fails closed. |
| Can cross-tenant or cross-workspace resources be referenced? | **NO** | Scope validation rejects them with non-disclosing 422 errors. |
| Can a mission change SIMULATION into REAL? | **NO** | Data mode is strictly server-assigned. |
| Can a mission claim approval without server authorization? | **NO** | Review endpoint requires `mission.review` permission and state `REVIEW_REQUIRED`. |
| Can invalid dependencies be accepted? | **NO** | Kahn's algorithm validates acyclicity; self-deps and unknown deps rejected. |
| Can a mission access evidence from another workspace? | **NO** | All queries strictly scoped by tenant and workspace. |
| Can a retry create duplicate missions? | **NO** | Supported via atomic idempotency key checking. |
| Can mission data contain raw secrets or unbounded payloads? | **NO** | Depth, key-count, and byte-size bounded; regex secret scanning and anti-smuggling active. |

---

## 17. Payload Bounds and Metadata Constraints

To prevent denial of service and data poisoning:
- **`MissionConstraint.parameters`:**
  - Maximum nesting depth: 3 levels.
  - Maximum key count: 20 keys.
  - Maximum serialized JSON size: 4096 bytes.
  - Prohibited parameter keys: `password`, `token`, `secret`, `api_key`, `credential`, `private_key`, `conn_str`, `connection_string`, `auth_token`.
- **`related_resources`:**
  - Maximum categories: 10.
  - Maximum resource IDs per category: 25.
  - Maximum aggregate resource IDs across all categories: 50.
  - Validated ID regex: `^[a-zA-Z0-9_\-]{3,128}$`.
- **`MissionPlannedStep`:**
  - Maximum `related_resource_ids`: 20.
  - Maximum `required_evidence`: 20.
- **Text Bounds & Secret Scanning:**
  - `title` <= 256 chars, `description` <= 4000 chars, `objective` <= 4000 chars, `origin_reason` <= 1000 chars, `submission_notes` <= 2000 chars, `cancel_reason` <= 2000 chars.
  - Regex pattern scanning blocks embedded private keys (`BEGIN.*PRIVATE KEY`), connection strings with passwords (`postgres://.*:.*@`), bearer tokens (`Bearer\s+[a-zA-Z0-9_\-\.]{20,}`), and API keys.

---

## 18. Explicitly Deferred Capabilities

The following are strictly deferred to future prompts:
- Autonomous multi-step mission execution.
- Multi-step mission scheduling and automatic dispatch.
- Continuous verification engine (Prompt 36).
- Closed-loop learning.
- Direct ExecutionGateway invocation from mission steps.
- Distributed sagas or distributed transactions.

---

## 19. Prompt 35B Outcome Integrity, Scoped Resource Lookup, and Input-Safety Corrections

1. **Server-Authoritative Outcome Status:**
   - **Criteria:** Only `UNKNOWN` may be supplied as the initial criterion status. `SATISFIED`, `NOT_SATISFIED`, and `NOT_APPLICABLE` are rejected on create and draft-update requests. Client-supplied `evaluation_notes` are rejected on create and draft updates.
   - **Steps:** Only `PLANNED` or `PENDING` may be accepted on create and draft-update requests. `SKIPPED`, `BLOCKED`, `CANCELLED`, `COMPLETED`, `IN_PROGRESS`, and `FAILED` are strictly rejected.
   - Enforced at both Pydantic request validation and domain/service boundaries to prevent direct programmatic bypass.

2. **Canonical Scoped Resource Lookup & Information Non-Disclosure:**
   - Zero private repository connections: removed all direct connection calls (`_get_connection()`, `_get_conn()`) from `_validate_single_resource`.
   - Scoped repository APIs used across all 6 categories: `action_store.get_by_scope()`, `DecisionEngineRepository.get_by_id(..., workspace_id=...)`, `evidence_explainability_repository.get_evidence_or_explanation_scope()`, `IncidentRepository.get_incident_scoped()`, `RcaRepository.get_analysis_scoped()`, and `OrganizationalMemoryRepository.get_entry()`.
   - Non-disclosure requirement: nonexistent and inaccessible references produce the identical generic error message (`reference '{id}' is invalid or inaccessible in the authorized scope`), exposing zero cross-scope metadata.

3. **Explicit Fail-Closed Plant Scope Policy:**
   - All 6 operational resource categories in SageCommand are site/plant-scoped.
   - Missing or untagged plant metadata on plant-sensitive resources fails closed immediately. Global scope is never silently inferred.
   - Referenced resource plant must match the mission's authorized plant (`mission.scope.plant_id`) AND the caller's assigned plants.

4. **Plant Identifier Validation & Secret Prevention:**
   - Canonical plant ID regex `^[A-Za-z0-9_\-\.]{2,64}$` strictly enforced on `MissionCreateRequest.plant_id`, `MissionScope.plant_id`, and `list_missions(plant_id=...)`.
   - Credential-bearing URLs, tokens, private keys, and passwords rejected in plant IDs and free-text fields.
   - Wildcard plant assignments (`["*"]`) on caller identities cannot bypass identifier validation.

5. **Fail-Closed Missing/Empty Plant Authorization:**
   - `list_missions()` fails closed with `MissionPermissionError` (HTTP 403 Forbidden) when caller has missing or empty assigned plants, preventing unauthorized existence discovery.
