# SageCommand V3 — Closed-Loop Learning Foundation

**Document Version:** 1.0.0  
**Prompt Reference:** Prompt 37  
**Subsystem:** Closed-Loop Learning Foundation (`backend/services/verification_trigger_coordinator.py`, `backend/data/schemas/closed_loop_contract.py`, `backend/repositories/verification_repository.py`, `backend/api/verification_routes.py`)  
**Starting Baseline Git Commit:** `8c18e6745e1704c51d4ed11b904f349160ce8e44`  
**Classification:** Governed Verification Feedback Loop (Observation, Deterministic Verification, Traceable Feedback — NOT Autonomous Execution)

---

## 1. Primary Objective and Architectural Scope

The **Closed-Loop Learning Foundation** implements a secure, deterministic, and observable event-triggered feedback loop in SageCommand V3. It connects incoming operational events to continuous verification and records persistent, auditable feedback without manual operator intervention.

### Core Architectural Principle
> **Closed-loop learning means SageCommand can observe new information, re-evaluate what it knows against evidence, and record a traceable result. It does not mean the system can silently change its own rules, alter model weights, or autonomously execute operational actions.**

The system learns from **recorded outcomes and evidence** by maintaining traceable feedback and improving the availability of verified context.

### What the Closed-Loop Learning Foundation Does NOT Do
- It does **not** execute missions or transition missions to `COMPLETED`.
- It does **not** approve Actions or call the `ExecutionGateway`.
- It does **not** write raw SQL or manage database connection engines.
- It does **not** alter industrial machinery or issue PLC/SCADA commands.
- It does **not** rewrite policy rules or train/fine-tune LLM weights.
- It does **not** introduce an autonomous reinforcement learning cycle against production equipment.

---

## 2. Architecture & Data Flow

The closed-loop architecture strictly reuses the existing `EventBus`, `EventDeliveryRepository`, `VerificationService`, and `VerificationRepository`.

```mermaid
flowchart TD
    E[Canonical Operational Event] --> B[Existing EventBus]
    B --> F[Eligibility Filter]
    F -->|REJECTED / IGNORED| L1[Record Safe Non-Verification Outcome]
    F -->|ELIGIBLE| S[Trusted Scope & Identity Validation]
    S -->|Scope Mismatch| L2[Reject Trigger (Fail Closed)]
    S -->|Valid Scope| C[Verification Trigger Coordinator]
    C --> V[Existing VerificationService]
    V --> R[VerificationRepository]
    R --> O[Persisted Verification Findings & Run]
    O --> P[Feedback Recorder (WAL Table: verification_feedback_records)]
    P --> FB[Canonical Feedback Event (verification.feedback.recorded)]
    FB --> B
    B --> G[Feedback Loop Guard]
    G -->|Provenance is closed_loop_coordinator| X[Stop - Deterministic Loop Break]
```

---

## 3. Five Distinct Stages of Closed-Loop Learning

### Stage A — Observe
Receives an existing canonical event (`CanonicalEvent`) ingested through the normal event delivery path via the existing `EventBus`.
Relevant event categories and types include:
- `TELEMETRY_UPDATED` (`telemetry.updated`)
- `EVIDENCE_RECORDED` (`evidence.recorded`)
- `EVIDENCE_INVALIDATED` (`evidence.invalidated`)
- `QUALITY_STATUS_CHANGED` (`quality.status_changed`)
- `MAINTENANCE_STATUS_CHANGED` (`maintenance.status_changed`)
- `ANOMALY_DETECTED` (`anomaly.detected`)
- `ASSET_STATE_CHANGED` (`asset.state_changed`)
- `INVENTORY_STATE_CHANGED` (`inventory.state_changed`)

### Stage B — Decide Whether Verification is Relevant
The `VerificationTriggerCoordinator` evaluates the event against an explicit, deterministic eligibility policy (`evaluate_eligibility`).
- Outcomes: `ELIGIBLE`, `IGNORED`, `REJECTED`, `DEFERRED`.
- Deterministic reasons include:
  - `UNSUPPORTED_EVENT_TYPE`: Category or event type not configured for verification.
  - `UNTRUSTED_PROVENANCE`: Missing or untrusted origin source.
  - `MISSING_SCOPE`: Missing required tenant or plant identifiers.
  - `MISSING_TARGET_REFERENCE`: Event does not reference a valid target mission.
  - `STALE_EVENT`: Event timestamp older than `SAGE_VERIFICATION_EVENT_MAX_AGE_SECONDS` (default: 3600s).
  - `FUTURE_DATED_EVENT`: Event timestamp is in the future beyond allowable clock skew tolerance (60s).
  - `INVALIDATED_EVENT`: Event lifecycle state is `INVALIDATED` or `SUPERSEDED`.
  - `FEEDBACK_LOOP_GUARD`: Event origin provenance is the coordinator itself.
  - `DISABLED`: Closed-loop trigger feature flag is disabled.
Fail-closed policy: LLMs never evaluate eligibility.

### Stage C — Verify
Invokes the existing `VerificationService.request_verification(...)` using a server-derived service identity:
- Revalidates the mission, its revision, and physical plant boundary.
- Resolves evidence strictly within caller's tenant and workspace boundaries.
- Preserves diagnostic versus authoritative verification semantics.
- Generates standard, persisted `VerificationFinding` records and `VerificationRun` records.
- Never executes the mission and never approves operational actions.

### Stage D — Record Feedback
Persists the relationship between:
- Triggering event ID & fingerprint
- Trigger rule version
- Authoritative tenant & workspace scope
- Verification run ID & outcome status
- Diagnostic status & outcome
- Feedback event ID
in the dedicated SQLite table `verification_feedback_records` in `VerificationRepository`.

### Stage E — Improve Future Context
Publishes a canonical feedback event (`verification.feedback.recorded`) back to the `EventBus` with provenance `closed_loop_coordinator`, making verification outcomes observable to downstream subscribers while the feedback loop guard stops recursion.

---

## 4. Trusted Identity, Scope Boundaries & Producer Validation (Prompt 37A Hardened)

A core invariant of Prompt 37A is that **a valid event schema is not proof of an authorized event scope**.

### 4.1 Authenticated Event Producer Boundary (`POST /api/v3/events`)
1. **Producer Identity is Authoritative:** The caller's authenticated identity (`identity.tenant_id`, `identity.workspace_id`, `identity.assigned_plants`) governs the event submission boundary. The event body is untrusted input.
2. **Tenant Mismatch Forbidden:** Cross-tenant event submissions return `HTTP 403 Forbidden`.
3. **Workspace Isolation:** Producers cannot choose an arbitrary workspace by editing the event body. Mismatched workspaces return `HTTP 403 Forbidden`.
4. **Physical Plant Scoping:** If a producer is assigned to specific physical plants, the submitted `plant_id` must belong to that authorized set (`HTTP 403 Forbidden` otherwise). Wildcard `*` in assigned plants is honored only if server-authoritative.
5. **Fail-Closed on Missing Scope:** Events with missing, empty, or manufactured scopes (`"global"`, `"unknown"`, `"default"`) return `HTTP 400 Bad Request`.
6. **No Privilege Escalation via Payload:** Payload fields attempting to inject `user_id`, `roles`, `permissions`, or `clearance` are completely ignored and cannot grant operational authority.
7. **Scope-Bound Fingerprint Validation:** Client-supplied `event_fingerprint` must match `event.compute_fingerprint()`. Inconsistent fingerprints return `HTTP 400 Bad Request`.
8. **Repository Return Scope Verification:** The API layer verifies the returned event's scope (`tenant_id`, `workspace_id`, `plant_id`) and fingerprint against the validated request before returning or publishing it.
9. **Persistence & Publication Ordering:**
   - Authenticated caller validation
   - Event body scope validation
   - Scope-bound fingerprint recomputation & verification
   - Immutably persist or resolve exact replay via `EventRepository.record_event_ex`
   - Validate returned event scope and canonical equality
   - Publish to `EventBus` only if newly persisted (`is_replay is False`)
   - Return canonical event response to caller

### 4.2 Independent Verification Scope Check (`VerificationTriggerCoordinator`)
Event fields cannot independently grant the coordinator authority to verify a mission:
1. **Scope Validation:** Validates that tenant, workspace, and plant are present, non-blank, and not manufactured strings (`"global"`, `"unknown"`, `"default"`).
2. **Independent Mission Resolution:** Before calling `VerificationService.request_verification(...)`, the coordinator independently resolves the target mission from `MissionRepository.get_mission(tenant_id, workspace_id, mission_id)`.
3. **Scope Alignment Verification:** Confirms that the mission's scope (`mission.scope.tenant_id`, `mission.scope.workspace_id`, `mission.scope.plant_id`) strictly matches the event's authorized scope.
4. **Revision & Target Validation:** Verifies that requested `mission_revision` matches `mission.revision`, and target criterion/step exists on the mission DAG.
5. **Strict Service Identity Construction:** Service identity is constructed strictly from the validated `Mission` scope via `_build_trusted_service_identity(mission)`:
   - `user_id`: `"system:closed_loop_coordinator:{tenant_id}"`
   - `tenant_id`: `mission.scope.tenant_id`
   - `workspace_id`: `mission.scope.workspace_id`
   - `roles`: `["SYSTEM_VERIFIER"]`
   - `permissions`: `["mission.verification.request", "mission.verification.read", "mission.read"]`
   - `assigned_plants`: `[mission.scope.plant_id]` (strictly the mission's plant, never wildcard)

### 4.3 Global Workspace Policy
- Missing or blank workspace scope fails closed.
- Manufactured scopes (`"global"`, `"default"`, `"unknown"`) are strictly rejected.
- No manufactured scope is ever stored in `verification_feedback_records`.

---

## 5. EventBus Reuse & Delivery Semantics

No competing event bus was introduced. The coordinator integrates with the existing `EventBus` (`backend/services/event_bus.py`):
- Registers explicitly configured tenant/workspace/plant subscriptions with `Subscription` records.
- Implements `SubscriberCallback` via `async def handle_event(delivery: EventDelivery, event: CanonicalEvent) -> bool`.
- Respects at-least-once delivery semantics:
  - If event is already processed or duplicate, acknowledges delivery safely without re-running verification.
  - Returns `False` on retryable errors so `EventBus` retry and dead-letter queue mechanisms function normally.
  - Acknowledges permanent rejections (`IGNORED`, `REJECTED`, `FEEDBACK_LOOP_GUARD`) as `True` to prevent dead-letter thrashing.

---

## 6. Scope-Bound Fingerprinting, Idempotency & Deduplication Safety (Prompt 37B)

### 6.1 Canonical Fingerprint Fields & Serialization
`CanonicalEvent.compute_fingerprint()` computes a deterministic SHA-256 fingerprint over an unambiguous canonical JSON structure with sorted keys and compact separators (`separators=(',', ':')`):
- **Included Fields (Canonical Reality & Scope):**
  - `schema_version`: Contract schema version (e.g. `"event.v1"`)
  - `tenant_id`: Authoritative tenant isolation boundary
  - `workspace_id`: Workspace isolation boundary
  - `plant_id`: Physical plant boundary
  - `category`: Event category enum string
  - `event_type`: Specific event type (e.g. `"telemetry.updated"`)
  - `occurred_at`: ISO timestamp of physical reality occurrence
  - `provenance`: Origin source string
  - `payload`: Canonicalized data dictionary
- **Excluded Fields (Transient & Non-Identity):**
  - `event_id`: Transient database UUID identifier
  - `event_fingerprint`: Excluded from its own hash
  - `recorded_at`: Server ingest timestamp
  - `observed_at`: Observation latency timestamp
  - `severity`: Alerting rating tag
  - `lifecycle`: Mutable state machine status (`RECORDED` -> `ACTIVE` -> `RESOLVED`)
  - `correlation_id` / `causation_id`: Distributed tracing links
  - `references`: Object links

### 6.2 Exact Replay vs. Conflicting Duplicate vs. Legacy Records
`EventRepository.record_event_ex(event)` strictly distinguishes three outcomes:
1. **Newly Persisted Event:**
   - Database insert succeeds.
   - Returns `(event, False)`.
   - Published to `EventBus`.
2. **Exact Legitimate Replay:**
   - Fingerprint matches an existing record in SQLite.
   - All canonical scope fields (`tenant_id`, `workspace_id`, `plant_id`) and content fields (`category`, `event_type`, `occurred_at`, `provenance`, `payload`, `schema_version`) match existing record exactly.
   - Returns `(existing_event, True)`.
   - **Publication Semantics:** Exact replays return the canonical event to the caller idempotently without re-publishing to `EventBus`, preventing downstream duplicate message traffic.
3. **Conflicting Duplicate:**
   - Fingerprint matches, but incoming event scope (`workspace_id`, `plant_id`) or payload differs.
   - Rejects deterministically by raising `EventIdempotencyConflictError`.
   - API translates to `HTTP 409 Conflict`. Zero publication to `EventBus`.
4. **Ambiguous Legacy Records:**
   - Existing record has missing/empty `workspace_id` or `plant_id`, or legacy unverified fingerprint.
   - Fails closed by raising `LegacyEventFingerprintError`.
   - Never returned as a verified exact replay.

### 6.3 Returned Event Integrity & Canonical Re-Verification (Prompt 37C)
After `EventRepository.record_event_ex()` returns, `POST /api/v3/events` requires comprehensive verification before returning or publishing the event:
- `saved_event.tenant_id == identity.tenant_id` (403 on mismatch)
- `saved_event.workspace_id == identity.workspace_id` (403 on mismatch)
- `saved_event.plant_id == event.plant_id` (403 on mismatch; mandatory exact check even for wildcard callers)
- Saved plant is authorized for caller (`"*" in auth_plants or saved_event.plant_id in auth_plants`)
- `saved_event.event_fingerprint == computed_fp` (409 on mismatch)
- `saved_event.compute_fingerprint() == computed_fp` (recomputes deterministic fingerprint; 409 on tampering)
- Canonical field comparison: verifies `schema_version`, `category`, `event_type`, `occurred_at`, `provenance`, and `payload` match the validated request.
- **Fail-Closed Guarantee:** If any check fails, the mismatched or tampered record is immediately rejected without publication to `EventBus` and without returning cross-scope data.

### 6.4 Publication Failure Recovery & Idempotent Retry (Prompt 37C)
To guarantee at-least-once delivery without duplicate executions:
1. **Initial Publication Failure:** If `EventBus.publish()` fails due to transient transport errors, the API request fails safely with `HTTP 500 Internal Server Error`, while preserving the persisted event in `EventRepository`.
2. **Replay Retry:** Re-submitting the exact same canonical event resolves to `is_replay=True`, creating **zero duplicate event records**.
3. **Selective Publication:** On replay, `bus.has_unfulfilled_deliveries(saved_event)` checks whether matching subscriptions lack `DeliveryStatus.SUCCESS`.
   - If unfulfilled deliveries exist, `bus.publish()` is retried (skipping already-succeeded subscriptions and delivering only to unfulfilled ones).
   - If all deliveries already succeeded, publication is skipped completely, preserving exact-replay idempotency with zero duplicate deliveries.
4. **Background Sweeper Recovery:** `EventBus.recover_pending_deliveries()` and background `_sweeper_loop()` sweep `deliveries` where `status = 'PENDING'`, resolve the canonical event from `EventRepository`, and fulfill deliveries directly.

---

## 7. Feedback Event Contract & Schema

Defined in [backend/data/schemas/closed_loop_contract.py](file:///E:/js/sage_command_production/backend/data/schemas/closed_loop_contract.py):

### Canonical Feedback Record
```python
class VerificationFeedbackRecord(BaseModel):
    feedback_id: str
    tenant_id: str
    workspace_id: str
    plant_id: str
    trigger_event_id: str
    trigger_event_fingerprint: str
    eligibility_status: EligibilityStatus
    eligibility_reason: EligibilityReasonCode
    mission_id: Optional[str]
    mission_revision: Optional[int]
    verification_id: Optional[str]
    verification_status: Optional[str]
    is_diagnostic: bool
    diagnostic_status: Optional[str]
    diagnostic_outcome: Optional[str]
    findings_count: int
    trigger_rule_version: str
    recorded_at: str
    feedback_event_id: Optional[str]
    dedup_hash: str
```

### Published Feedback Event
Published to `EventBus` as a `CanonicalEvent`:
- `event_type`: `"verification.feedback.recorded"`
- `category`: `EventCategory.AUDIT`
- `provenance.source`: `"closed_loop_coordinator"`
- `references.mission_id`: Mission ID
- `references.parent_event_id`: Triggering event ID
- `payload`: Contains verification outcome, diagnostic status, findings count, and feedback record reference.

---

## 8. Feedback Loop Guard (Preventing Infinite Recursion)

Without a deterministic guard, publishing a feedback event could cause infinite cycles (`event -> verify -> feedback -> event -> verify...`).
The `VerificationTriggerCoordinator` implements a multi-layer guard:
1. **Category Check:** `EventCategory.AUDIT` events are ignored (`EligibilityReasonCode.UNSUPPORTED_EVENT_TYPE`).
2. **Provenance Guard:** If `event.provenance.source == "closed_loop_coordinator"`, the eligibility filter immediately yields:
   ```text
   status = EligibilityStatus.IGNORED
   reason = EligibilityReasonCode.FEEDBACK_LOOP_GUARD
   ```
3. **Event Type Guard:** Events matching `verification.feedback.*` are ignored.
4. **Zero State Mutation:** Feedback events do not emit secondary verification events.

---

## 9. Diagnostic vs. Authoritative Semantics

Strictly preserves Prompt 36 and Prompt 36E–36H invariants:
- A diagnostic run (`rule_type=EVIDENCE_EXISTS`) produces:
  - `is_diagnostic = True`
  - `diagnostic_outcome = "CONFIRMED"`
  - `status = VerificationStatus.NOT_VERIFIED` (or `INDETERMINATE`)
  - `status != VerificationStatus.VERIFIED`
- The coordinator propagates `is_diagnostic`, `diagnostic_status`, and `diagnostic_outcome` into the feedback record and feedback event.
- Diagnostic confirmation is never reported as authoritative mission verification.

---

## 10. Copilot and Agent Integration Decision

**Decision:** Verification tools remain **UNREGISTERED** in the default `copilot_tools` registry for Prompt 37 / Prompt 37A / Prompt 37B.

**Reason:**
Current LangGraph `ToolNode` architecture in `backend/agents/copilot.py` does not provide an immutable, request-scoped identity propagation context for background sub-agents. Allowing the LLM to invoke verification tools without verified identity propagation would risk client-forged identity parameters.
As mandated by Prompt 37 Section 15, Prompt 37A Section 10, and Prompt 37B Section 7:
> *"If the current Copilot architecture cannot guarantee trusted identity propagation, keep the tool unregistered and document the blocker. Do not weaken the identity boundary to make a demo work."*

---

## 11. REST API Endpoints

Mounted in FastAPI:
1. `GET /api/v3/missions/{mission_id}/verifications/feedback`
   - Returns feedback records for a specific mission within caller's tenant and workspace.
   - Enforces `mission.verification.read` permission and mission plant scoping.
2. `GET /api/v3/verification/feedback`
   - Returns tenant-wide closed-loop feedback records with optional `mission_id` filtering.
   - Enforces `mission.verification.read` permission and tenant/workspace boundaries.
3. `POST /api/v3/events`
   - Ingests canonical operational events with strict producer tenant/workspace/plant authorization.
   - Enforces exact-replay deduplication and rejects conflicting duplicates (HTTP 409).
4. `GET /api/v3/events`
   - Retrieves events filtered by tenant, workspace, and authorized plant scoping.
5. `GET /api/v3/events/fingerprint/{fingerprint}`
   - Retrieves event by fingerprint with strict tenant, workspace, and plant access control.

---

## 12. Configuration Settings & Startup Subscriptions (Prompt 37A & 37B)

Configured in `backend/core/config.py`:
- `SAGE_CLOSED_LOOP_ENABLED` (bool, default: `False`): Master toggle for closed-loop subsystem. Defaults to `false` for startup safety.
- `SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED` (bool, default: `False`): Toggles event-triggered verification. Defaults to `false`.
- `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES` (str, default: `""`): Comma-separated triples `tenant:workspace:plant` defining explicitly authorized subscription scopes.
- `SAGE_VERIFICATION_EVENT_MAX_AGE_SECONDS` (int, default: `3600`): Maximum acceptable age of operational events.
- `SAGE_VERIFICATION_EVENT_DEDUP_WINDOW_SECONDS` (int, default: `300`): Deduplication window for identical event replays.
- `SAGE_VERIFICATION_EVENT_MAX_BATCH_SIZE` (int, default: `100`): Max batch processing size.

### Startup Behavior
- When either flag is `False`, no closed-loop subscriptions are registered on startup.
- Unconditional `register_tenant_subscription("default")` is permanently removed.
- When flags are `True`, the server subscribes only to explicitly configured scopes in `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES`.
- Missing or invalid subscription configuration logs a safe diagnostic and registers 0 subscriptions.

---

## 13. Test Coverage Summary

- **Focused Closed-Loop Test Suite:** `backend/test_v3_closed_loop_learning.py`
  - 68 tests covering eligibility, identity boundary, scope isolation, idempotency, loop guards, AST checks, producer authorization, coordinator independent scope verification, feature flag defaults, fingerprint integrity, workspace/plant fingerprint isolation, exact replay, conflicting duplicate rejection, repository-return tampering rejection, and publication failure recovery.
  - **Result: 68 passed (100%)**.
- **All Core Regression Suites:**
  - Canonical Event Model: 33 passed
  - Event Driven Architecture: 5 passed
  - Continuous Verification: 128 passed
  - Mission Architecture: 74 passed
  - Evidence Explainability: 140 passed
  - Organizational Memory: 83 passed
  - Root Cause Analysis: 30 passed
  - Incident Management: 56 passed
  - Confidence Uncertainty & Authorization: 171 passed
  - **Total: 788 passed, 0 failed.**

---

## 14. Remaining Limitations and Deferred Work

1. **Dynamic Subscriber Scope Discovery:** The server requires explicit configuration in `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES`; dynamic subscription authorization from a tenant directory is deferred until an external tenant registry is introduced.
2. **Autonomous Policy Mutation:** Self-modifying policy engines remain strictly forbidden.
3. **Model Weight Fine-Tuning:** Dynamic training of model weights is deferred.
4. **Autonomous Action Approval:** Human-in-the-loop governance remains mandatory for all operational actions.
5. **LangGraph Identity Context Propagation:** Tool registration deferred until request-scoped security context is added to LangGraph `ToolNode`.
