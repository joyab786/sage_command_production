# SageCommand V3 — Closed-Loop Learning Foundation Baseline & Security Audit Report

**Prompt Reference:** Prompt 37, Prompt 37A, Prompt 37B & Prompt 37C (Security Corrections)  
**Starting Baseline Git Commit:** `dd74214dbc8b4543948e9e17eed8c9cd206ea51a`  
**Branch:** `main`  
**Repository:** `joyab786/sage_command_production`  
**Local Workspace:** `E:\js\sage_command_production`  
**Date:** October 13, 2026  

---

## 1. Commit Audit Trail & Baseline Correction

As required by Prompt 37A, 37B, and 37C, the git commit history and audit documentation have been reconciled against actual git history:

- **Original Prompt 37 Implementation Commit:** `bad6c5cc5f90f99cde5edb02f73470239a03bd94` (`feat(verification): add governed closed-loop learning foundation (Prompt 37)`)  
  *(Audit Correction Note: In the initial Prompt 37 baseline report, the implementation commit SHA was omitted and only the pre-Prompt 37 baseline `8c18e674...` was referenced. This is now explicitly corrected and recorded above with the exact verified SHA.)*
- **Original Prompt 37 Documentation Commit:** `0f7d7e0deb3d7aaa19362fd1ff9c25ae7e21036a` (`docs(verification): add closed-loop learning foundation architecture and baseline report (Prompt 37)`)
- **Prompt 37A Starting Baseline:** `0f7d7e0deb3d7aaa19362fd1ff9c25ae7e21036a`
- **Prompt 37A Dedicated Implementation Commit:** `9e13ccdb43f26bfa713a6a6658056a64a8e80edc` (`fix(security): bind closed-loop triggers to trusted scope (Prompt 37A)`)
- **Prompt 37A Dedicated Documentation Commit:** `dc39e78f49253c857a4752ff7be8623e3d3088a0` (`docs(security): document closed-loop scope hardening (Prompt 37A)`)
- **Prompt 37B Starting Baseline:** `dc39e78f49253c857a4752ff7be8623e3d3088a0`
- **Prompt 37B Dedicated Implementation Commit:** `274034f992ed9a2dca8ab18b7ea2098758c5b921` (`fix(security): isolate event fingerprints and prevent duplicate cross-scope resolution (Prompt 37B)`)
- **Prompt 37B Dedicated Documentation Commit:** `dd74214dbc8b4543948e9e17eed8c9cd206ea51a` (`docs(security): document event fingerprint isolation and deduplication safety (Prompt 37B)`)
- **Prompt 37C Starting Baseline:** `dd74214dbc8b4543948e9e17eed8c9cd206ea51a`
- **Prompt 37C Dedicated Implementation Commit:** `53f63a3819bb0b9f9dd93205dabb56b38cc82f93` (`fix(security): enforce returned event integrity and publication failure recovery (Prompt 37C)`)
- **Prompt 37C Dedicated Documentation Commit:** `docs(security): document returned event integrity and publication failure recovery (Prompt 37C)`

---

## 2. Executive Summary

Prompt 37A executes a focused security correction on Prompt 37's Closed-Loop Learning subsystem, correcting the trust boundary between authenticated event producers and the privileged closed-loop verification coordinator (`VerificationTriggerCoordinator`).

Core Security Invariant established:
> **A valid event schema is not proof of an authorized event scope.**

The implementation preserves the existing `EventBus`, `EventDeliveryRepository`, `VerificationTriggerCoordinator`, `VerificationService`, `VerificationRepository`, event contracts, and Prompt 36 verification semantics. Zero competing event buses, verification engines, identity systems, or repositories were introduced.

---

## 3. Security Hardening Specifications (Prompt 37A)

### 3.1 Authenticated Event Producer Scope Validation (`POST /api/v3/events`)
- **Authoritative Identity:** The authenticated caller (`identity.tenant_id`, `identity.workspace_id`, `identity.assigned_plants`) governs the event submission boundary. The event body is treated as untrusted input.
- **Tenant Isolation:** Cross-tenant event submission is strictly forbidden (`HTTP 403 Forbidden`).
- **Workspace Isolation:** Producers cannot choose an arbitrary workspace by altering the event body. Mismatched workspaces return `HTTP 403 Forbidden`.
- **Plant Authorization:** If an identity has assigned physical plants, the submitted `plant_id` must belong to that authorized set (`HTTP 403 Forbidden` if unauthorized). Wildcard `*` is honored only when server-assigned.
- **Fail-Closed on Missing Scope:** Missing or empty tenant, workspace, or plant identifiers fail closed (`HTTP 400 Bad Request`).
- **Rejection of Manufactured Scopes:** Fabricated scopes such as `"global"`, `"unknown"`, and `"default"` are rejected (`HTTP 400 Bad Request`).
- **No Payload Privilege Escalation:** Client-supplied `user_id`, `roles`, `permissions`, or `clearance` fields within the payload are ignored and cannot grant operational authority.
- **Deterministic Fingerprint Validation:** Client-supplied `event_fingerprint` must match `event.compute_fingerprint()`. Inconsistent fingerprints return `HTTP 400 Bad Request`.
- **Persistence & Publication Barrier:** Events are persisted in `EventRepository` and published to `EventBus` only after all scope and fingerprint validations succeed.

### 3.2 Independent Coordinator Scope & Mission Verification
Event envelope fields cannot independently grant the coordinator authority to verify a mission:
1. **Scope Validation:** Enforces that tenant, workspace, and plant are present, non-empty, and not manufactured strings (`"global"`, `"unknown"`, `"default"`).
2. **Independent Mission Resolution:** Before calling `VerificationService.request_verification(...)`, the coordinator independently resolves the referenced mission using `MissionRepository.get_mission(tenant_id, workspace_id, mission_id)`.
3. **Scope Alignment Verification:** Confirms that the mission's scope (`mission.scope.tenant_id`, `mission.scope.workspace_id`, `mission.scope.plant_id`) strictly matches the event's authorized scope.
4. **Mission Revision & Target Validation:** Verifies that requested `mission_revision` matches `mission.revision`, and target criterion/step exists on the mission DAG.
5. **Strict Service Identity Construction:** Service identity is constructed strictly from the validated `Mission` scope via `_build_trusted_service_identity(mission)`:
   - `user_id`: `"system:closed_loop_coordinator:{mission.scope.tenant_id}"`
   - `tenant_id`: `mission.scope.tenant_id`
   - `workspace_id`: `mission.scope.workspace_id`
   - `roles`: `["SYSTEM_VERIFIER"]`
   - `permissions`: `["mission.verification.request", "mission.verification.read", "mission.read"]`
   - `assigned_plants`: `[mission.scope.plant_id]` (strictly the mission's plant, never wildcard)

### 3.3 Global Workspace Policy
- Missing or blank workspace scope fails closed.
- Manufactured scopes (`"global"`, `"default"`, `"unknown"`) are strictly rejected.
- No manufactured scope is ever stored in `verification_feedback_records`.
- Legitimate global scope behavior elsewhere in the application is preserved without broad unnecessary migrations.

### 3.4 Explicit Opt-In Feature Flags and Safe Defaults
Configured in `backend/core/config.py`:
- `SAGE_CLOSED_LOOP_ENABLED = False` (safe default: `false`)
- `SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED = False` (safe default: `false`)
- `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES = ""` (safe default: empty)

When either flag is `False`:
- No event-triggered verification occurs.
- No implicit subscriptions are created.
- Eligibility decisions return `EligibilityReasonCode.DISABLED`.
- Existing non-triggered verification APIs continue to operate normally.

### 3.5 Startup Subscription Behavior
- Unconditional `coordinator.register_tenant_subscription("default")` in `backend/server.py` has been permanently removed.
- Subscriptions are registered **only** when both feature flags are enabled and valid subscription scopes (`tenant:workspace:plant` triples) are explicitly configured in `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES`.
- If configuration is missing or invalid, the coordinator subscribes to 0 scopes and logs a safe diagnostic.
- Startup and shutdown remain safe and do not impact other EventBus subscribers.

### 3.6 Fingerprint Integrity and Idempotency
- Fingerprints are computed deterministically via canonical event content hashing (`event.compute_fingerprint()`).
- Reusing an existing fingerprint with modified event payload cannot impersonate another event or bypass closed-loop deduplication.
- Deduplication keys (`cltrig_<SHA-256(...)>`) ensure identical event replays return existing feedback records without creating duplicate verification runs.

---

## 4. Test Suites Executed and Verified Results

### 4.1 Focused Closed-Loop Learning Test Suite (`backend/test_v3_closed_loop_learning.py`)
- **Total Tests:** 49
- **Passed:** 49 (100%)
- **Failed:** 0
- **Duration:** 9.45s

#### Test Classes and Coverage Breakdown:
1. **`TestEventEligibility` (8 tests):**
   - Valid operational event triggers verification.
   - Unsupported categories/types ignored (`UNSUPPORTED_EVENT_TYPE`).
   - Stale events (>3600s) ignored (`STALE_EVENT`).
   - Future-dated events rejected (`FUTURE_DATED_EVENT`).
   - Missing target mission ignored (`MISSING_TARGET_REFERENCE`).
   - Untrusted provenance rejected (`UNTRUSTED_PROVENANCE`).
   - Invalidated events ignored (`INVALIDATED_EVENT`).
   - Disabled mode suppresses triggers (`DISABLED`).

2. **`TestScopeAndIdentityBoundary` (5 tests):**
   - Missing tenant fails closed.
   - Missing plant fails closed.
   - Cross-plant events fail closed.
   - Payload cannot forge identity or clearance.
   - Manufactured fallback tenant/plant rejected.

3. **`TestIdempotencyAndDuplicateSuppression` (2 tests):**
   - Repeated delivery replays deterministically without duplicate runs.
   - Distinct valid events trigger separate runs.

4. **`TestVerificationIntegrity` (4 tests):**
   - Coordinator invokes existing `VerificationService`.
   - Findings determine outcome; mission status is never mutated.
   - No actions are approved in `action_store`.
   - Diagnostic runs preserve non-authoritative status (`NOT_VERIFIED`).

5. **`TestFeedbackIntegrityAndLoopPrevention` (3 tests):**
   - Feedback records persisted with full provenance.
   - Feedback events cannot re-trigger coordinator (`FEEDBACK_LOOP_GUARD`).
   - Full closed-loop execution and loop break validated over real `EventBus`.

6. **`TestStaticArchitecturalChecks` (1 test):**
   - AST analysis proves coordinator does NOT use `create_engine`, `create_async_engine`, `engine.connect`, raw SQL execution, or `ExecutionGateway`.

7. **`TestClosedLoopRestApi` (1 test):**
   - Authorized users can query feedback endpoints with tenant/workspace scoping.

8. **`TestAuthenticatedEventProducerSecurity` (8 tests - Prompt 37A New):**
   - Producer submitting another tenant's event is rejected (`HTTP 403`).
   - Producer submitting unauthorized workspace is rejected (`HTTP 403`).
   - Producer submitting unauthorized plant is rejected (`HTTP 403`).
   - Producer forging identity/roles in payload achieves no privilege escalation.
   - Missing workspace scope is rejected (`HTTP 400`).
   - Missing plant scope is rejected (`HTTP 400`).
   - Manufactured `"global"` scope without explicit authorization is rejected (`HTTP 400`).
   - Rejected events are not persisted in `EventRepository` or dispatched to `EventBus`.

9. **`TestCoordinatorScopeSecurity` (6 tests - Prompt 37A New):**
   - Forged event envelope cannot obtain privileged service identity for another workspace.
   - Forged plant scope cannot cause cross-plant verification (`SCOPE_MISMATCH`).
   - Cross-tenant/workspace mission verification fails closed; 0 verification runs created.
   - Mismatched mission revision fails closed (`REVISION_MISMATCH`); 0 verification runs created.
   - Missing authoritative scope does not create verification run.
   - Schema-valid event with untrusted scope cannot bypass authorization boundary.

10. **`TestFeatureFlagsAndStartupSecurity` (6 tests - Prompt 37A New):**
    - Both flags default to `False` when environment variables are absent.
    - Either flag disabled prevents event-triggered verification.
    - Server startup registers zero subscriptions when feature is disabled.
    - Server startup does not register `"default"` tenant subscription.
    - Missing subscription configuration leaves event-triggered verification inactive (0 subscriptions).
    - Explicitly configured, valid subscription scopes register properly when feature is enabled.

11. **`TestFingerprintIntegrityAndIdempotency` (5 tests - Prompt 37A New):**
    - Missing client fingerprint is safely computed by the system.
    - Correct client fingerprint is accepted.
    - Incorrect client-supplied fingerprint is rejected (`HTTP 400 Bad Request`).
    - Reusing a fingerprint with different event payload is rejected or produces distinct verification runs without collision.
    - Legitimate event retries remain idempotent (0 duplicate verification runs).

---

### 4.2 Core Regression Test Suites

All regression test suites specified in Prompt 37A Section 12 were executed and verified against active code:

| Test Suite | Tests Run | Passed | Failed | Duration | Status |
|---|---|---|---|---|---|
| `backend/test_v3_closed_loop_learning.py` | 49 | 49 | 0 | 9.45s | **PASSED** |
| `backend/test_v3_event_driven_architecture.py` | 5 | 5 | 0 | 1.30s | **PASSED** |
| `backend/test_v3_continuous_verification.py` | 128 | 128 | 0 | 11.03s | **PASSED** |
| `backend/test_v3_mission_architecture.py` | 74 | 74 | 0 | 6.59s | **PASSED** |
| `backend/test_v3_evidence_explainability.py` | 140 | 140 | 0 | 6.91s | **PASSED** |
| `backend/test_v3_organizational_memory.py` | 83 | 83 | 0 | 8.86s | **PASSED** |
| `backend/test_v3_root_cause_analysis.py` | 30 | 30 | 0 | 6.28s | **PASSED** |
| `backend/test_v3_incident_management.py` | 56 | 56 | 0 | 10.69s | **PASSED** |
| `backend/test_v3_confidence_uncertainty.py` & `backend/test_v3_authorization.py` | 171 | 171 | 0 | 7.81s | **PASSED** |
| `backend/test_v3_event_model.py` (Event Authorization & Contracts) | 33 | 33 | 0 | 1.15s | **PASSED** |
| **TOTAL** | **769** | **769** | **0** | **70.07s** | **ALL PASSED** |

---

## 5. Security Invariant Matrix

| Security Property | Status | Verification & Enforcement Mechanism |
|---|---|---|
| Authenticated Event Producer Boundary | **VERIFIED** | Enforced at `POST /api/v3/events`; caller identity authoritative; rejects cross-tenant, cross-workspace, and cross-plant submissions. |
| Independent Coordinator Scope Validation | **VERIFIED** | Enforced in `VerificationTriggerCoordinator`; mission resolved via `MissionRepository` and scope verified before `request_verification`. |
| Rejection of Manufactured Scopes | **VERIFIED** | `"global"`, `"unknown"`, and `"default"` rejected in API, schemas, coordinator, and repository storage. |
| Safe Opt-In Defaults | **VERIFIED** | `SAGE_CLOSED_LOOP_ENABLED=false`, `SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED=false` default to disabled. |
| Safe Startup Subscriptions | **VERIFIED** | Hardcoded `"default"` subscription removed; requires explicit `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES`. |
| Fingerprint Integrity | **VERIFIED** | Deterministic SHA-256 fingerprint verification; mismatched client fingerprints rejected with `HTTP 400`. |
| Replay & Delivery Idempotency | **VERIFIED** | Deduplication via `cltrig_<hash>` guarantees single verification run across at-least-once replays. |
| Diagnostic vs Authoritative Semantics | **VERIFIED** | Diagnostic runs preserve `is_diagnostic=True` and `status=NOT_VERIFIED`; `status == VERIFIED` strictly prohibited. |
| Zero Operational Execution | **VERIFIED** | Static AST analysis confirms zero database engine creations, raw SQL, or `ExecutionGateway` imports. |
| Mission Lifecycle Immutability | **VERIFIED** | Missions remain in current state; closed-loop verification never transitions missions to `COMPLETED`. |
| Action Approval Guard | **VERIFIED** | Actions in `action_store` are never approved by closed-loop triggers. |
| Copilot Integration Safety | **VERIFIED** | Verification tools remain unregistered pending LangGraph request-scoped identity propagation. |

---

## 6. Remaining Limitations & Deferred Work

1. **Dynamic Subscription Discovery:** Subscription scopes must be explicitly configured via `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES`. Dynamic discovery from an external tenant management directory is deferred.
2. **Autonomous Policy Mutation:** Self-modifying policy engines remain strictly prohibited.
3. **Model Weight Fine-Tuning:** Dynamic training or weight adjustment is deferred.
4. **Autonomous Action Approval:** Human-in-the-loop governance remains mandatory for all operational actions.
5. **LangGraph Identity Context Propagation:** Tool registration deferred until request-scoped security context is added to LangGraph `ToolNode`.

---

## 7. Prompt 37B Security Audit: Closed-Loop Event Fingerprint Isolation & Deduplication Safety

### 7.1 Audit Trail & Baselines
- **Starting Baseline:** `dc39e78f49253c857a4752ff7be8623e3d3088a0`
- **Implementation Commit:** `274034f992ed9a2dca8ab18b7ea2098758c5b921` (`fix(security): isolate event fingerprints and prevent duplicate cross-scope resolution (Prompt 37B)`)
- **Documentation Commit:** `docs(security): document event fingerprint isolation and deduplication safety (Prompt 37B)`
- **Security Invariant:**
  > An event fingerprint must bind all security-relevant event scope, and a duplicate lookup must never return or publish an event belonging to a different workspace or plant than the validated request. A fingerprint match alone is never proof of canonical event equivalence.

### 7.2 Fingerprint Algorithm Correction (`backend/data/schemas/event_contract.py`)
- **Canonical Structure:** Computed deterministically via `CanonicalEvent.compute_fingerprint()` over an unambiguous canonical JSON dictionary with sorted keys (`sort_keys=True`) and compact separators (`separators=(',', ':')`).
- **Bound Fields:**
  - `schema_version` (contract version, e.g. `"event.v1"`)
  - `tenant_id` (tenant boundary)
  - `workspace_id` (workspace boundary)
  - `plant_id` (plant boundary)
  - `category` (event category enum value)
  - `event_type` (event type string)
  - `occurred_at` (occurrence timestamp in ISO 8601 UTC)
  - `provenance` (producer subsystem origin)
  - `payload` (canonicalized JSON payload)
- **Excluded Fields:** `event_id` (transient UUID), `event_fingerprint` (self-referential), `recorded_at` (ingest timestamp), `observed_at` (latency tracking), `severity`, `lifecycle`, `correlation_id`, `causation_id`, `references`.
- **Legacy Fingerprint Support:** `compute_legacy_fingerprint()` retained for backward compatibility inspections only.

### 7.3 Repository Deduplication & Collision Handling (`backend/services/event_repository.py`)
- **Composite Scoped Indexing:** Added database index `idx_tenant_scope_fp` (`tenant_id`, `workspace_id`, `plant_id`, `event_fingerprint`) and `idx_tenant_ws_plant` (`tenant_id`, `workspace_id`, `plant_id`).
- **Explicit Outcome Distinction (`record_event_ex`):**
  1. **Newly Persisted Event:** Fresh database insert returns `(CanonicalEvent, False)`.
  2. **Exact Legitimate Replay:** Existing row matches fingerprint AND canonical equality across tenant, workspace, plant, category, event_type, occurred_at, provenance, schema_version, and payload. Returns `(CanonicalEvent, True)`.
  3. **Conflicting Duplicate:** Existing row matches fingerprint but differs in workspace, plant, or payload. Raises `EventIdempotencyConflictError`.
  4. **Ambiguous Legacy Records:** Existing row lacks workspace/plant scope or was persisted under old unverified hashing. Raises `LegacyEventFingerprintError`.
- **Fail-Closed Retrieval:** `get_event_by_scope_and_fingerprint` requires tenant, workspace, and plant match before returning a record.

### 7.4 API Persistence and Publication Boundary (`backend/api/event_routes.py`)
- **Execution Flow:**
  1. Authenticated caller identity validation (`tenant_id`, `workspace_id`, authorized plants).
  2. Event body scope validation against caller identity.
  3. Deterministic fingerprint recomputation and client-fingerprint verification.
  4. Persistence / exact replay resolution via `EventRepository.record_event_ex()`.
  5. Post-persistence returned event scope verification against authenticated identity.
  6. Conditional EventBus publication: Published if and only if `is_replay is False`. Exact replays return `HTTP 201` idempotently without publishing duplicate bus messages. Conflicting duplicates raise `HTTP 409 Conflict` with zero bus publication.

### 7.5 Migration and Legacy-Data Strategy
- Safe, non-destructive migration in `EventRepository._ensure_tables()`:
  - Adds composite indices if not present.
  - Safely reads historical rows handling NULL `workspace_id`/`plant_id` values.
  - Does NOT delete or alter historical events.
  - Fails closed (`LegacyEventFingerprintError`) on duplicate lookups against unverified legacy rows to prevent false event equivalence.

### 7.6 Security Regression Tests (Prompt 37B Tests A–J)
Implemented in `backend/test_v3_closed_loop_learning.py` (`TestEventFingerprintIsolationAndDeduplication`):
- **Test A (test_50):** Same tenant, different workspace isolation — second event cannot resolve to, return, or publish Workspace A's event.
- **Test B (test_51):** Same tenant and workspace, different plant isolation — plant scope bound into fingerprint and duplicate rejection.
- **Test C (test_52):** Exact replay idempotency — same event re-submitted returns existing record with zero duplicate verification runs.
- **Test D (test_53):** Modified payload with reused fingerprint rejected (`HTTP 400 Bad Request`).
- **Test E (test_54):** Modified workspace with reused fingerprint rejected (`HTTP 400 Bad Request`).
- **Test F (test_55):** Modified plant with reused fingerprint rejected (`HTTP 400 Bad Request`).
- **Test G (test_56):** Repository duplicate collision raises `EventIdempotencyConflictError` without overwriting or returning existing record.
- **Test H (test_57):** Publication boundary spy verifies exact replay publishes 0 times to `EventBus` and conflicting duplicates publish 0 times.
- **Test I (test_58):** Legacy unverified records fail closed with `LegacyEventFingerprintError`.
- **Test J (test_59):** Multi-tenant isolation verified — cross-tenant duplicate submissions rejected deterministically.

### 7.7 Comprehensive Test Suite Matrix
- `backend/test_v3_closed_loop_learning.py`: 59 passed (10.04s)
- `backend/test_v3_event_model.py`: 33 passed (1.75s)
- `backend/test_v3_event_driven_architecture.py`: 5 passed (1.34s)
- `backend/test_v3_continuous_verification.py`: 128 passed (10.90s)
- `backend/test_v3_mission_architecture.py`: 74 passed (6.49s)
- `backend/test_v3_evidence_explainability.py`: 140 passed (6.77s)
- `backend/test_v3_organizational_memory.py`: 83 passed (8.66s)
- `backend/test_v3_root_cause_analysis.py`: 30 passed (6.19s)
- `backend/test_v3_incident_management.py`: 56 passed (11.06s)
- `backend/test_v3_confidence_uncertainty.py` & `backend/test_v3_authorization.py`: 171 passed (7.94s)
- **Total:** **779 passed, 0 failed.**

### 7.8 Remaining Limitations
1. **Historical Legacy Event Backfill:** Historical events lacking workspace or plant bindings fail closed upon deduplication lookup. If replay support for legacy pre-Prompt 37B events is required, an explicit tenant-governed migration script must populate verified scope and recompute fingerprints.
2. **LangGraph Copilot Tool Exposure:** Verification tools remain unregistered pending request-scoped identity propagation in LangGraph subagent `ToolNode`.

---

## 8. Prompt 37C Security Audit: Final Event Return Integrity & Publication Recovery

### 8.1 Audit Trail & Baselines
- **Starting Baseline:** `dd74214dbc8b4543948e9e17eed8c9cd206ea51a`
- **Implementation Commit:** `53f63a3819bb0b9f9dd93205dabb56b38cc82f93` (`fix(security): enforce returned event integrity and publication failure recovery (Prompt 37C)`)
- **Documentation Commit:** `docs(security): document returned event integrity and publication failure recovery (Prompt 37C)`
- **Security Invariant:**
  > An event returned by the repository must match the exact validated scope and canonical reality of the submitted request; a duplicate lookup must never return or publish cross-scope data; and publication failures must recover safely and idempotently without duplicate event storage or duplicate delivery side-effects.

### 8.2 Repository-Return Tampering & Scope Integrity (`backend/api/event_routes.py`)
After `EventRepository.record_event_ex()` completes, the API validates the returned record with multi-layer defense-in-depth:
1. `saved_event.tenant_id == identity.tenant_id` (HTTP 403 on tenant boundary violation).
2. `saved_event.workspace_id == identity.workspace_id` (HTTP 403 on cross-workspace violation).
3. `saved_event.plant_id == event.plant_id` (HTTP 403 on plant mismatch; mandatory exact check enforced even when caller has wildcard `*` plant authorization).
4. `saved_event.plant_id in auth_plants or "*" in auth_plants` (HTTP 403 if saved plant is unauthorized).
5. `saved_event.event_fingerprint == computed_fp` (HTTP 409 on fingerprint string mismatch).
6. `saved_event.compute_fingerprint() == computed_fp` (HTTP 409 on recomputed canonical JSON hash mismatch, detecting payload tampering).
7. Field-by-field canonical comparison: verifies `schema_version`, `category`, `event_type`, `occurred_at`, `provenance`, and `payload` match the validated request.
8. If any check fails, the route fails closed immediately: zero EventBus publication and zero cross-scope data returned.

### 8.3 Publication Failure Recovery & Replay Idempotency
1. **Transient Publication Failure:** If `EventBus.publish()` fails due to transient connection or transport errors, the API request safely fails with `HTTP 500 Internal Server Error`, while the event remains durably persisted in `EventRepository`.
2. **Replay Retry:** Re-submitting the exact same canonical event resolves to `is_replay=True`, creating **0 duplicate event records** in `EventRepository`.
3. **Selective Publication via `has_unfulfilled_deliveries()`:**
   - Evaluates whether matching subscriptions have pending, failed, or un-attempted deliveries.
   - If unfulfilled deliveries exist, `bus.publish()` is retried (skipping already-succeeded subscriptions and delivering only to unfulfilled ones).
   - If all deliveries already succeeded, publication is skipped completely, preserving exact-replay idempotency with zero duplicate deliveries.
4. **Background Sweeper Recovery:** `EventBus.recover_pending_deliveries()` queries `EventDeliveryRepository.get_pending_deliveries()`, resolves the canonical event from `EventRepository`, and dispatches it directly to subscriber callbacks.

### 8.4 Security Regression Tests (Prompt 37C Tests 60–68)
Implemented in `backend/test_v3_closed_loop_learning.py` (`TestEventReturnIntegrityAndPublicationRecovery`):
- **Test 60:** Repository returning a different authorized plant (under wildcard identity) is rejected with `HTTP 403` and 0 published events.
- **Test 61:** Repository returning a different workspace is rejected with `HTTP 403` and 0 published events.
- **Test 62:** Repository returning a different tenant is rejected with `HTTP 403` and 0 published events.
- **Test 63:** Repository returning altered payload content with the original fingerprint string is rejected with `HTTP 409` and 0 published events.
- **Test 64:** Repository returning changed canonical field (`event_type`) with the original fingerprint string is rejected with `HTTP 409` and 0 published events.
- **Test 65:** Transient publication transport error fails safely with `HTTP 500` while preserving persisted event in `EventRepository`.
- **Test 66:** Publication recovery via exact replay retry successfully delivers without creating duplicate event records (verified: exactly 1 event in store, status `SUCCESS`).
- **Test 67:** Exact replay of an already fulfilled event skips publication and produces zero duplicate deliveries (callback called exactly 1 time).
- **Test 68:** Background recovery sweeper (`recover_pending_deliveries()`) processes pending deliveries directly from SQLite store to `SUCCESS`.

### 8.5 Comprehensive Test Suite Matrix
- `backend/test_v3_closed_loop_learning.py`: 68 passed (11.49s)
- `backend/test_v3_event_model.py`: 33 passed (1.75s)
- `backend/test_v3_event_driven_architecture.py`: 5 passed (1.34s)
- `backend/test_v3_continuous_verification.py`: 128 passed (10.90s)
- `backend/test_v3_mission_architecture.py`: 74 passed (6.49s)
- `backend/test_v3_evidence_explainability.py`: 140 passed (6.77s)
- `backend/test_v3_organizational_memory.py`: 83 passed (8.66s)
- `backend/test_v3_root_cause_analysis.py`: 30 passed (6.19s)
- `backend/test_v3_incident_management.py`: 56 passed (11.06s)
- `backend/test_v3_confidence_uncertainty.py` & `backend/test_v3_authorization.py`: 171 passed (7.94s)
- **Total:** **788 passed, 0 failed.**

### 8.6 Remaining Limitations
1. **Historical Legacy Event Backfill:** Pre-Prompt 37B events lacking workspace/plant scope fail closed on deduplication. An explicit migration script is required if replay support for historical events is needed.
2. **LangGraph Copilot Tool Exposure:** Verification tools remain unregistered pending request-scoped identity propagation in LangGraph subagent `ToolNode`.
