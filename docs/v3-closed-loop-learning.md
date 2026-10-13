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

## 4. Trusted Identity and Scope Isolation Boundary

A critical security invariant of Prompt 37 is the non-negotiable identity boundary:
1. **Never Trust Event Payload for Identity:**
   Fields inside `CanonicalEvent.payload` such as `user_id`, `roles`, `permissions`, `clearance`, or `tenant_id` are completely ignored.
2. **Authoritative Scope Derived from Envelope:**
   `tenant_id`, `workspace_id`, and `plant_id` are taken strictly from the canonical event envelope, which has passed prior cryptographic/server ingestion checks.
3. **Server-Derived Service Identity:**
   Background verification uses `_build_trusted_service_identity(event)`:
   - `user_id`: `"system:closed_loop_coordinator"`
   - `tenant_id`: Authoritative event `tenant_id`
   - `workspace_id`: Authoritative event `workspace_id`
   - `roles`: `["SERVICE_OPERATOR"]`
   - `permissions`: `["mission.verification.request", "mission.verification.read", "mission.read"]`
   - `assigned_plants`: Exactly `[event.plant_id]` (never wildcard `"*"` unless event specifically validates)
4. **Cross-Tenant and Cross-Plant Isolation:**
   Cross-tenant attempts fail closed with `SCOPE_MISMATCH`. Cross-plant attempts fail closed with `SCOPE_MISMATCH` or `MissionPermissionError`.

---

## 5. EventBus Reuse & Delivery Semantics

No competing event bus was introduced. The coordinator integrates with the existing `EventBus` (`backend/services/event_bus.py`):
- Registers tenant-scoped subscriptions with `Subscription` records.
- Implements `SubscriberCallback` via `async def handle_event(delivery: EventDelivery, event: CanonicalEvent) -> bool`.
- Respects at-least-once delivery semantics:
  - If event is already processed or duplicate, acknowledges delivery safely without re-running verification.
  - Returns `False` on retryable errors so `EventBus` retry and dead-letter queue mechanisms function normally.
  - Acknowledges permanent rejections (`IGNORED`, `REJECTED`, `FEEDBACK_LOOP_GUARD`) as `True` to prevent dead-letter thrashing.

---

## 6. Idempotency & Duplicate Suppression

The same logical trigger must never spawn duplicate verification runs:
1. **Deterministic Trigger Key:**
   ```text
   cltrig_<SHA-256(tenant_id:workspace_id:mission_id:revision:event_fingerprint:rule_version)>
   ```
2. **Dual-Layer Deduplication:**
   - **Repository Level:** `VerificationRepository.check_feedback_idempotency(...)` checks recent triggers within `SAGE_VERIFICATION_EVENT_DEDUP_WINDOW_SECONDS` (default: 300s).
   - **Verification Service Level:** Passes the deterministic trigger key as `idempotency_key` into `VerificationService.request_verification(...)`.
3. **Replay Determinism:**
   Replays of identical events return the existing `VerificationRun` and existing `VerificationFeedbackRecord` with `DeliveryStatus.ACKNOWLEDGED`.
4. **Fresh Events:**
   Distinct operational events with different fingerprints or payload timestamps legitimately produce fresh, independent verification runs.

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

**Decision:** Verification tools remain **UNREGISTERED** in the default `copilot_tools` registry for Prompt 37.

**Reason:**
Current LangGraph `ToolNode` architecture in `backend/agents/copilot.py` does not provide an immutable, request-scoped identity propagation context for background sub-agents. Allowing the LLM to invoke verification tools without verified identity propagation would risk client-forged identity parameters.
As mandated by Prompt 37 Section 15:
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

---

## 12. Configuration Settings

Configured in `backend/core/config.py`:
- `SAGE_CLOSED_LOOP_ENABLED` (bool, default: `True`): Master toggle for closed-loop subsystem.
- `SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED` (bool, default: `True`): Toggles event-triggered verification.
- `SAGE_VERIFICATION_EVENT_MAX_AGE_SECONDS` (int, default: `3600`): Maximum acceptable age of operational events.
- `SAGE_VERIFICATION_EVENT_DEDUP_WINDOW_SECONDS` (int, default: `300`): Deduplication window for identical event replays.
- `SAGE_VERIFICATION_EVENT_MAX_BATCH_SIZE` (int, default: `100`): Max batch processing size.

---

## 13. Test Coverage Summary

- **Focused Closed-Loop Test Suite:** `backend/test_v3_closed_loop_learning.py`
  - 24 tests covering eligibility, identity boundary, scope isolation, idempotency, loop guards, AST checks, and REST routes.
  - **Result: 24 passed (100%)**.
- **All Core Regression Suites:**
  - Event Driven Architecture: 5 passed
  - Continuous Verification: 128 passed
  - Mission Architecture: 74 passed
  - Evidence Explainability: 140 passed
  - Organizational Memory: 83 passed
  - Root Cause Analysis: 30 passed
  - Incident Management: 56 passed
  - Confidence Uncertainty & Authorization: 171 passed
  - **Total: 711 passed, 0 failed.**

---

## 14. Deferred Capabilities

1. **Autonomous Policy Mutation:** Self-modifying policy engines remain strictly forbidden.
2. **Model Weight Fine-Tuning:** Dynamic training of model weights is deferred.
3. **Autonomous Action Approval:** Human-in-the-loop governance remains mandatory for all operational actions.
4. **LangGraph Identity Context Propagation:** Tool registration deferred until request-scoped security context is added to LangGraph `ToolNode`.
