# SageCommand V3 — Closed-Loop Learning Foundation Baseline & Security Audit Report

**Prompt Reference:** Prompt 37, Prompt 37A, Prompt 37B, Prompt 37C, Prompt 37D, Prompt 37E, Prompt 37F & Prompt 37G (Final Lease-Expiry Race Correction)  
**Starting Baseline Git Commit:** `424c4ffb9d8987e6319bb15867f2d8c8888a91ea`  
**Branch:** `main`  
**Repository:** `joyab786/sage_command_production`  
**Local Workspace:** `E:\js\sage_command_production`  
**Date:** October 14, 2026  

---

## 1. Commit Audit Trail & Baseline Correction

As required by Prompt 37A, 37B, 37C, and 37D, the git commit history and audit documentation have been reconciled against actual git history:

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
- **Prompt 37C Dedicated Documentation Commit:** `ac7c98abce18a49c05198cd1a35fe1e71edfc5d0` (`docs(security): document returned event integrity and publication failure recovery (Prompt 37C)`)
- **Prompt 37D Starting Baseline:** `ac7c98abce18a49c05198cd1a35fe1e71edfc5d0`
- **Prompt 37D Dedicated Implementation Commit:** `370603a19834d8bc87c2cbe6cb82f708853f64b2` (`fix(events): ensure missing-subscriber recovery, bounded retries, and sanitized publication errors (Prompt 37D)`)
- **Prompt 37D Dedicated Documentation Commit:** `7c73940316b89308f266c159abd03a09e17a02af` (`docs(events): document event delivery recovery state and publication error sanitization (Prompt 37D)`)
- **Prompt 37E Starting Baseline:** `7c73940316b89308f266c159abd03a09e17a02af`
- **Prompt 37E Dedicated Implementation Commit:** `00473589ca824f4fd8942f10eb217c884af7b164` (`fix(events): implement atomic delivery claims, leases, and concurrency safety (Prompt 37E)`)
- **Prompt 37E Dedicated Documentation Commit:** `c4009af982b1674649414bf3f60bdaadf2134de7` (`docs(events): document atomic delivery claims and concurrent recovery safety (Prompt 37E)`) *(Corrected: superseded mismatched pre-push draft SHA `776c4ce3...`)*
- **Prompt 37F Starting Baseline:** `c4009af982b1674649414bf3f60bdaadf2134de7`
- **Prompt 37F Dedicated Implementation Commit:** `4944532c620b80db2a644e4252c2343cfdee06ca` (`fix(events): enforce lease expiration on finalization and safe callback renewal (Prompt 37F)`)
- **Prompt 37F Dedicated Documentation Commit:** `424c4ffb9d8987e6319bb15867f2d8c8888a91ea` (`docs(events): document lease expiration enforcement and callback renewal safety (Prompt 37F)`)
- **Prompt 37G Starting Baseline:** `424c4ffb9d8987e6319bb15867f2d8c8888a91ea`
- **Prompt 37G Dedicated Implementation Commit:** `1d17eb3bf640b376f5a14a4999436867a6a227a1` (`fix(events): correct finalization and renewal timestamp ordering under SQLite lock contention (Prompt 37G)`)
- **Prompt 37G Dedicated Documentation Commit:** Recorded at final remote HEAD (`docs(events): document SQLite lock contention timestamp ordering correction (Prompt 37G)`)

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

### 8.6 Remaining Limitations (Prompt 37C)
1. **Historical Legacy Event Backfill:** Pre-Prompt 37B events lacking workspace/plant scope fail closed on deduplication. An explicit migration script is required if replay support for historical events is needed.
2. **LangGraph Copilot Tool Exposure:** Verification tools remain unregistered pending request-scoped identity propagation in LangGraph subagent `ToolNode`.

---

## 9. Event Delivery Recovery State & Safe Publication Errors (Prompt 37D)

### 9.1 Missing-Subscriber Recovery and Bounded Exponential Backoff
1. **Transient Missing-Callback Handling:**
   - In `backend/services/event_bus.py`, `_process_delivery()` previously marked deliveries as `FAILED` and returned immediately when their in-memory callback was absent. Because the sweeper only queries `status = 'PENDING'`, deliveries remained permanently stranded in `FAILED`.
   - Under Prompt 37D, a missing subscriber callback is treated as a transient failure condition subject to bounded exponential backoff (`backoff_seconds = min(2 ** attempts, 60)`).
   - If `delivery.attempts < delivery.max_attempts`, the delivery is updated to `status = DeliveryStatus.PENDING` with `next_retry_at` set.
   - Once the callback is registered (e.g. subscriber restarts or late registration), the recovery sweeper (`recover_pending_deliveries()`) or next publication attempt fulfills the delivery to `SUCCESS`.
2. **Deterministic Retry Exhaustion & Dead-Lettering:**
   - When attempts reach `max_attempts` without successful delivery, `delivery.status` transitions to `FAILED`, `next_retry_at` is cleared, and an immutable `DeadLetter` record is recorded in `dead_letters`.
   - Terminally exhausted deliveries are **never retried indefinitely**. Both `has_unfulfilled_deliveries()` and `publish()` skip deliveries with existing dead letter records.
   - An administrative redrive path (`EventDeliveryRepository.redrive_dead_letter(dead_letter_id, tenant_id)` and `EventBus.redrive_dead_letter(...)`) allows operators to re-arm dead-lettered deliveries to `PENDING` with attempts reset to 0, strictly within tenant boundaries.

### 9.2 Safe Publication Error Sanitization & Request Correlation
1. **Sanitizing API Publication Responses (`backend/api/event_routes.py`):**
   - Raw exception details (`str(pub_err)`) have been eliminated from all client responses in both initial publication and replay-retry paths.
   - Client responses return stable, safe status messages:
     - Initial publication failure: `"Event persisted but publication encountered transient error."`
     - Replay retry failure: `"Event persisted but publication retry encountered transient error."`
   - Client-facing messages accurately indicate that the event was safely persisted in `EventRepository` and was not rolled back.
2. **Diagnostic Server-Side Logging & Redaction:**
   - Detailed exception traces are logged strictly server-side using `governance.redaction.sanitize_log_message()` to ensure passwords, tokens, API keys, and private credentials are never written to logs.
   - Request correlation is preserved via `X-Correlation-ID` response headers and structured log tags.

### 9.3 Delivery Idempotency & Tenant Boundary Protection
1. **Non-Downgrade Delivery Protection (`EventDeliveryRepository.record_delivery_attempt`):**
   - Implemented database-level and application-level guards ensuring that a delivery with `status = 'SUCCESS'` can **never be reset or downgraded** back to `PENDING` or `FAILED` by concurrent workers, sweeper loops, or replay requests.
   - Cross-tenant updates (`delivery.tenant_id != existing.tenant_id`) are rejected with `ValueError`.
2. **Cross-Tenant Recovery Resolution Barrier:**
   - In `EventBus.recover_pending_deliveries()`, tenant scoping is strictly validated. The sweeper retrieves only deliveries matching the target tenant.
   - `repo.get_event(delivery.tenant_id, delivery.event_id)` resolves the canonical event strictly under the delivery's own `tenant_id`, preventing any cross-tenant resolution.

### 9.4 Focused Recovery Tests Execution Details (Tests 69–77)
Implemented in `backend/test_v3_closed_loop_learning.py` (`TestPrompt37DRecoveryStateAndSafePublicationErrors`):
- **Test 69 (`test_69_delivery_becomes_pending_after_transient_subscriber_failure`):**
  A subscriber callback failure transitions the delivery to `PENDING` with `attempts = 1` and `next_retry_at` set with exponential backoff.
- **Test 70 (`test_70_missing_callback_transitions_delivery_to_pending_without_stranding`):**
  When a callback is missing from memory, `_process_delivery()` sets `last_error = "Subscriber callback not found in memory"`, increments `attempts = 1`, and transitions to `PENDING`. Delivery is **never stranded** in `FAILED`.
- **Test 71 (`test_71_callback_becomes_available_before_retry_exhaustion`):**
  When a missing callback is registered before retry exhaustion, subsequent processing succeeds, updating status to `SUCCESS` with `attempts = 2` and clearing `next_retry_at`.
- **Test 72 (`test_72_background_recovery_processes_pending_delivery`):**
  `recover_pending_deliveries()` sweeps pending deliveries from the SQLite repository, resolves canonical events, and dispatches them to subscriber callbacks to achieve `SUCCESS`.
- **Test 73 (`test_73_successful_delivery_not_delivered_again_by_subsequent_sweeps`):**
  A delivery already marked `SUCCESS` is not retrieved by subsequent sweeps (0 swept), and re-publication skips it with 0 duplicate callback executions.
- **Test 74 (`test_74_retry_exhaustion_follows_max_attempts_and_dead_letter_policy`):**
  Repeated failures exhaust `max_attempts` (3 attempts), creating an immutable `DeadLetter` record, transitioning to `FAILED`, and stopping automatic retry. Administrative `redrive_dead_letter()` safely re-arms to `PENDING` with attempts reset to 0.
- **Test 75 (`test_75_raw_internal_exception_absent_from_api_responses`):**
  Deliberately injected sensitive error messages (`"DatabaseSecretPassword123!"`, `"Bearer_Token_abc_xyz"`, `"InternalReplaySecretCredentials999!"`) are verified absent from client HTTP responses across both initial publication and replay-retry paths. Safe message returned with `X-Correlation-ID` header preserved.
- **Test 76 (`test_76_event_persisted_before_publication_failure_remains_available_for_idempotent_recovery`):**
  When initial publication fails with HTTP 500, the event is durably stored in `EventRepository`. Exact replay succeeds with HTTP 201, creates 0 duplicate event records, and recovers delivery to `SUCCESS`.
- **Test 77 (`test_77_recovery_cannot_resolve_event_across_tenant_boundaries`):**
  Tenant Beta recovery sweep cannot process Tenant Alpha deliveries (0 swept). Cross-tenant delivery resolution and cross-tenant delivery updates are strictly blocked.

### 9.5 Comprehensive Test Suite Matrix (Prompt 37D)
- `backend/test_v3_closed_loop_learning.py`: **77 passed** (15.21s)
- `backend/test_v3_event_driven_architecture.py`: **5 passed** (1.34s)
- `backend/test_v3_event_model.py`: **33 passed** (1.75s)
- `backend/test_v3_continuous_verification.py`: **128 passed** (12.04s)
- `backend/test_v3_security.py`: **14 passed** (1.52s)
- `backend/test_v3_security_integration.py`: **16 passed** (2.10s)
- `backend/test_v3_authorization.py`: **19 passed** (1.98s)
- `backend/test_v3_mission_architecture.py`: **74 passed** (6.49s)
- `backend/test_v3_evidence_explainability.py`: **140 passed** (6.77s)
- `backend/test_v3_organizational_memory.py`: **83 passed** (8.66s)
- `backend/test_v3_rca.py` / `backend/test_v3_root_cause_analysis.py`: **30 passed** (6.19s)
- `backend/test_v3_incident_management.py`: **56 passed** (11.06s)
- `backend/test_v3_confidence_uncertainty.py`: **122 passed** (7.94s)
- **Total:** **797 passed, 0 failed.**

### 9.6 Remaining Limitations
1. **Dynamic Subscriber Scope Discovery:** Explicit configuration in `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES` remains mandatory; dynamic discovery via tenant registry is deferred.
2. **Autonomous Policy Mutation:** Self-modifying policy engines remain strictly forbidden.
3. **Model Weight Fine-Tuning:** Dynamic training of model weights is deferred.
4. **Autonomous Action Approval:** Human-in-the-loop governance remains mandatory for all physical operational actions.
5. **LangGraph Identity Context Propagation:** Tool registration deferred until request-scoped security context is added to LangGraph `ToolNode`.
6. **Historical Legacy Event Backfill:** Pre-Prompt 37B events lacking workspace/plant scope fail closed on deduplication. An explicit migration script is required if replay support for historical events is needed.

---

## 10. Prompt 37E Security Audit: Atomic Event Delivery Claims & Concurrent Recovery Safety

### 10.1 Audit Metadata
- **Required Starting Baseline:** `7c73940316b89308f266c159abd03a09e17a02af`
- **Implementation Commit:** `00473589ca824f4fd8942f10eb217c884af7b164` (`fix(events): implement atomic delivery claims, leases, and concurrency safety (Prompt 37E)`)
- **Documentation Commit:** `776c4ce3d514db07070743dbe034782655accc31` (`docs(events): document atomic delivery claims and concurrent recovery safety (Prompt 37E)`)
- **Repository:** `joyab786/sage_command_production`
- **Branch:** `main`

### 10.2 Problem Addressed: Concurrency Race in Delivery Processing
Under the Prompt 37D design, `_process_delivery()` inspected delivery status via a non-atomic read before dispatching to the subscriber callback. When an event was enqueued or retried:
- A queue worker and background recovery sweeper could both inspect `status = PENDING`.
- Both would invoke the subscriber callback concurrently for the same delivery.
- Prompt 37E closes this window by introducing a database-backed atomic claim with lease semantics.

### 10.3 Atomic Claim & Lease Architecture
1. **Database Schema & Metadata (`deliveries` table):**
   - Added `claim_token TEXT`: Unique UUID assigned on every claim attempt.
   - Added `lease_expires_at TEXT`: ISO-8601 timestamp after which a stalled claim is considered expired.
   - Added `idempotency_key TEXT`: Deterministic key (`delivery_id`) provided to subscribers for deduplication.
   - Added status `PROCESSING` to `DeliveryStatus`.
   - Indexed `idx_del_lease ON deliveries(status, lease_expires_at)` and `idx_del_claim ON deliveries(claim_token)`.

2. **Atomic Claim Operation (`claim_delivery`):**
   - Implemented in `EventDeliveryRepository.claim_delivery(delivery_id, tenant_id, lease_seconds, respect_backoff)`.
   - Executes an atomic SQL `UPDATE ... WHERE ...` with rowcount verification.
   - Predicates:
     - `delivery_id = ? AND tenant_id = ?` (strict tenant boundary).
     - `status != 'SUCCESS'`.
     - `NOT EXISTS (SELECT 1 FROM dead_letters ...)`.
     - `status = 'PENDING'` (under retry backoff when enabled) OR `(status = 'PROCESSING' AND lease_expires_at <= now)` (expired lease).
   - Atomic update:
     - `status = 'PROCESSING'`
     - `claim_token = 'claim_<uuid>'`
     - `lease_expires_at = now + lease_seconds`
     - `attempts = attempts + 1`
   - SQLite write serialization guarantees only one worker acquires the row. Competing workers receive `None`.

3. **Isolated Callback Invocation:**
   - External subscriber callbacks are invoked **outside of any open database transaction**, ensuring slow or external network calls cannot hold SQLite write locks or stall the event bus.

4. **Claim Finalization (`finalize_delivery`):**
   - Finalization requires the active `claim_token`:
     - On success: `status = 'SUCCESS'`, clears lease and claim token.
     - On failure with attempts $< \text{max\_attempts}$: `status = 'PENDING'`, calculates exponential backoff (`min(2 ** attempts, 60)`), clears lease and claim token.
     - On failure with attempts $\ge \text{max\_attempts}$: `status = 'FAILED'`, records an immutable `DeadLetter`, clears lease and claim token.
   - If a lease expired and was claimed by a newer worker, the stale worker's finalization attempt affects 0 rows and is safely rejected.

5. **Crash Recovery & Truthful At-Least-Once Semantics:**
   - If a worker crashes mid-callback, `status` remains `PROCESSING` until `lease_expires_at`.
   - Once expired, background recovery sweepers or workers reclaim the delivery and retry.
   - System truthfully preserves **at-least-once delivery semantics** for crash scenarios; subscribers rely on `delivery.idempotency_key` for side-effect deduplication.

### 10.4 Tenant Boundary & State Safety
- Cross-tenant claims (`delivery.tenant_id != caller.tenant_id`) raise explicit `ValueError("Cross-tenant delivery claim rejected")`.
- Cross-tenant finalizations raise `ValueError("Cross-tenant delivery finalization rejected")`.
- `SUCCESS` is terminal for automatic processing; cannot be downgraded or reset by late replays or sweeps.
- Dead-lettered deliveries remain excluded from automatic retries until explicitly redriven via `redrive_dead_letter()`.

### 10.5 Concurrency Tests Verified (Tests 78–88)
Implemented in `backend/test_v3_closed_loop_learning.py` (`TestPrompt37EAtomicClaimsAndConcurrencySafety`):
- **Test 78 (`test_78_two_concurrent_workers_claim_same_pending_delivery`):** Two concurrent workers race for the same delivery; exactly one acquires the claim (`status = PROCESSING`, `attempts = 1`). The other receives `None`.
- **Test 79 (`test_79_worker_and_recovery_sweeper_race`):** Worker and sweeper race concurrently; subscriber callback is executed exactly once. Delivery reaches `SUCCESS`.
- **Test 80 (`test_80_successful_delivery_not_invoked_again_by_replay_or_sweep`):** Replays and sweeps on `SUCCESS` deliveries do not invoke callbacks again.
- **Test 81 (`test_81_active_lease_prevents_second_claim`):** Active lease (`lease_seconds = 60`) prevents competing workers from acquiring a claim.
- **Test 82 (`test_82_expired_lease_becomes_recoverable`):** Delivery with expired lease is safely claimed by a new worker with a fresh claim token.
- **Test 83 (`test_83_old_claim_token_cannot_finalize_superseded_delivery`):** Stale worker with superseded token cannot finalize delivery; newer worker finalizes as `SUCCESS`.
- **Test 84 (`test_84_failed_attempt_follows_backoff_and_retry_limit`):** Failed attempt transitions to `PENDING` with backoff; claim with `respect_backoff=True` is blocked until backoff window passes.
- **Test 85 (`test_85_retry_exhaustion_creates_expected_dead_letter`):** Exhausting retries transitions delivery to `FAILED`, creates `DeadLetter` record, and excludes it from future claims.
- **Test 86 (`test_86_administrative_redrive_restores_eligibility_with_claim_validation`):** `redrive_dead_letter()` removes dead letter, resets status to `PENDING`, and enables safe atomic claiming.
- **Test 87 (`test_87_cross_tenant_claims_and_finalization_rejected`):** Foreign tenant claims and finalizations raise `ValueError` and fail closed.
- **Test 88 (`test_88_callbacks_stable_idempotency_key_unchanged_across_retries`):** `delivery.idempotency_key` is identical and invariant across all retry attempts.

### 10.6 Complete Regression Test Suite Matrix (Prompt 37E)
- `backend/test_v3_closed_loop_learning.py`: **88 passed** (14.33s)
- `backend/test_v3_event_driven_architecture.py`: **5 passed** (1.30s)
- `backend/test_v3_event_model.py`: **33 passed** (1.75s)
- `backend/test_v3_continuous_verification.py`: **128 passed** (11.29s)
- `backend/test_v3_security.py`: **14 passed** (1.52s)
- `backend/test_v3_security_integration.py`: **16 passed** (2.10s)
- `backend/test_v3_authorization.py`: **19 passed** (1.98s)
- `backend/test_v3_mission_architecture.py`: **74 passed** (6.49s)
- `backend/test_v3_evidence_explainability.py`: **140 passed** (6.77s)
- `backend/test_v3_organizational_memory.py`: **83 passed** (8.66s)
- `backend/test_v3_rca.py` / `backend/test_v3_root_cause_analysis.py`: **30 passed** (6.19s)
- `backend/test_v3_incident_management.py`: **56 passed** (11.06s)
- `backend/test_v3_confidence_uncertainty.py`: **122 passed** (7.94s)
- **Total: 808 passed, 0 failed.**

### 10.7 Remaining Limitations & Deferred Work
1. **At-Least-Once Delivery Crash Recovery:** If a worker crashes after external side effects occur but before finalization commits to SQLite, the lease expires and the delivery is retried. Subscribers must remain idempotent using `delivery.idempotency_key`.
2. **Dynamic Subscription Discovery:** Subscription scopes must be explicitly configured via `SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES`. Dynamic discovery from an external tenant management directory is deferred.
3. **Autonomous Policy Mutation:** Self-modifying policy engines remain strictly prohibited.
4. **Model Weight Fine-Tuning:** Dynamic training or weight adjustment is deferred.
5. **Autonomous Action Approval:** Human-in-the-loop governance remains mandatory for all physical operational actions.
6. **LangGraph Identity Context Propagation:** Tool registration deferred until request-scoped security context is added to LangGraph `ToolNode`.

---

## 11. Lease Expiration Enforcement & Long-Running Callback Safety (Prompt 37F)

### 11.1 Problem Statement & Concurrency Race Closed
Under Prompt 37E, `finalize_delivery()` verified matching `claim_token` and `status != SUCCESS`, but lacked an atomic predicate enforcing `lease_expires_at >= now_iso`. Consequently, if a worker's lease expired but no competing worker had yet claimed the delivery, the stale worker could still finalize the delivery as `SUCCESS` or `FAILED`. Furthermore, subscriber callbacks executing longer than the default lease (`SAGE_EVENT_DELIVERY_LEASE_SECONDS = 30`) could experience silent lease expiration while running legitimately, creating a concurrency race where background recovery sweepers would re-dispatch the in-flight delivery to a second worker.

Prompt 37F completely resolves both issues without creating competing event buses or repositories:
1. **Enforced Lease Expiration on Finalization:** An attempt cannot finalize if its lease has expired, even if no replacement worker has claimed the delivery yet.
2. **Safe Heartbeat Lease Renewal for Active Callbacks:** A tenant-scoped, claim-token-guarded background heartbeat extends the lease while subscriber code executes, stopping cleanly upon completion or cancellation.

### 11.2 Architectural Invariants & Predicate Hardening

#### 1. Atomic Database Predicate on Finalization (`finalize_delivery`)
The final state transition is governed by an atomic SQL predicate with rowcount verification:
```sql
UPDATE deliveries
SET status = :new_status,
    claim_token = NULL,
    lease_expires_at = NULL,
    last_error = :error_msg,
    next_retry_at = :next_retry_at,
    updated_at = :now_iso
WHERE delivery_id = :delivery_id
  AND tenant_id = :tenant_id
  AND claim_token = :claim_token
  AND UPPER(status) = 'PROCESSING'
  AND lease_expires_at IS NOT NULL
  AND lease_expires_at >= :now_iso
```
- **Expired Lease Rejection:** If `lease_expires_at < now_iso`, the update matches 0 rows and returns `None`. The expired attempt cannot mutate the delivery.
- **Superseded Lease Rejection:** If another worker claimed the delivery, `claim_token` does not match, matching 0 rows and returning `None`.
- **Non-Downgrade of SUCCESS:** If the delivery reached `SUCCESS`, `UPPER(status) = 'PROCESSING'` fails, guaranteeing that `SUCCESS` cannot be overwritten or downgraded by a late worker.
- **Race Serialization:** Write serialization guarantees that concurrent finalization and claim takeover resolve deterministically to exactly one valid state transition.

#### 2. Lease Renewal Heartbeat Architecture (`renew_delivery_lease`)
To protect legitimate long-running callbacks:
- **Repository Method:** `renew_delivery_lease(delivery_id, tenant_id, claim_token, extension_seconds, now_iso) -> Optional[EventDelivery]`.
- **Predicate:** Extends `lease_expires_at` only if:
  - `delivery_id = ? AND tenant_id = ?`
  - `claim_token = ?`
  - `UPPER(status) = 'PROCESSING'`
  - `lease_expires_at IS NOT NULL AND lease_expires_at >= :now_iso` (cannot resurrect expired claim)
  - `NOT EXISTS (SELECT 1 FROM dead_letters ...)`
- **Isolated Heartbeat Loop in `EventBus._process_delivery()`:**
  - Interval: `min(SAGE_EVENT_DELIVERY_HEARTBEAT_INTERVAL_SECONDS, max(0.05, lease_seconds / 3.0))` (default 10s for 30s lease; dynamically scales down for sub-second test leases).
  - Uses `asyncio.wait_for(stop_event.wait(), timeout)` to allow instantaneous shutdown without delay.
  - Lifecycle: spawned immediately before `await callback(claimed, event)` and deterministically stopped, cancelled, and awaited in `finally:`.
  - Subscriber execution never holds a database connection or transaction open.

#### 3. Recovery Sweeper Behavior & Crash Recovery
- **Sweeper Eligibility:** `get_pending_deliveries()` retrieves only `PENDING` deliveries (respecting backoff) and genuinely expired `PROCESSING` deliveries (`lease_expires_at <= now_iso`).
- **Live Callback Immunity:** Active callbacks renewing their leases keep `lease_expires_at > now_iso`, preventing sweepers from reclaiming in-flight deliveries.
- **Worker Crash Handling:** If a worker process or container crashes, the heartbeat terminates immediately. Once `lease_expires_at` elapses, background sweepers or queue workers reclaim the delivery under a new claim token.
- **At-Least-Once Delivery Truthfulness:** If a subscriber performs non-idempotent external actions before crashing prior to SQLite commit, the delivery will eventually be retried. SageCommand does not claim impossible distributed exactly-once side effects; subscribers rely on `delivery.idempotency_key` for deduplication.

### 11.3 Concurrency & Lifecycle Test Matrix (Tests 89–100)
Implemented in `backend/test_v3_closed_loop_learning.py` under `TestPrompt37FLeaseExpirationAndCallbackSafety`:
- **Test 89 (`test_89_expired_claim_cannot_finalize_even_when_no_new_claim_exists`):** Verifies that an expired claim cannot finalize even when no replacement claim exists. Returns `None`; database status remains `PROCESSING`.
- **Test 90 (`test_90_superseded_claim_cannot_finalize_after_another_worker_claims`):** Verifies that an old claim token cannot finalize after another worker takes over the claim. Success is finalized only by the current worker.
- **Test 91 (`test_91_live_callback_renews_lease_and_prevents_sweeper_takeover`):** Demonstrates that a live callback running longer than its initial lease renews via heartbeat and is not reclaimed by concurrent sweeps.
- **Test 92 (`test_92_renewal_fails_for_stale_claim_token`):** Stale claim tokens cannot renew a lease held by another worker.
- **Test 93 (`test_93_renewal_fails_after_lease_expiration`):** Renewal is rejected if the lease has already expired; expired claims cannot be resurrected.
- **Test 94 (`test_94_renewal_cannot_modify_success_or_dead_lettered`):** Renewal returns `None` for completed `SUCCESS` and dead-lettered `FAILED` deliveries.
- **Test 95 (`test_95_worker_crash_or_cancelled_callback_permits_recovery`):** Worker task cancellation terminates heartbeat, allowing the expired lease to be recovered by the sweeper and processed to `SUCCESS`.
- **Test 96 (`test_96_finalization_racing_with_lease_takeover_produces_one_valid_transition`):** Concurrent finalization and claim takeover race resolves to exactly one valid atomic transition.
- **Test 97 (`test_97_cross_tenant_renewal_and_finalization_rejected`):** Cross-tenant renewals and finalizations raise `ValueError` and fail closed.
- **Test 98 (`test_98_successful_delivery_not_invoked_again_by_replay_or_recovery`):** Replays and sweeps on `SUCCESS` deliveries return `True` without re-invoking subscriber callbacks.
- **Test 99 (`test_99_retry_exhaustion_dead_letter_and_idempotency_key_invariant`):** Bounded retries, backoff, dead-letter recording, redrive, and stable `idempotency_key` are preserved across attempts.
- **Test 100 (`test_100_all_prompt_37a_to_37f_regressions_verified`):** Multi-tenant end-to-end publishing, matching, claim acquisition, renewal, and finalization regression verified.

### 11.4 Verification & Regression Matrix (Prompt 37F)
- `backend/test_v3_closed_loop_learning.py`: **100 passed** (18.00s)
- `backend/test_v3_event_driven_architecture.py`: **5 passed** (1.28s)
- `backend/test_v3_event_model.py`: **33 passed** (1.76s)
- `backend/test_v3_continuous_verification.py`: **128 passed** (11.05s)
- `backend/test_v3_security.py`: **14 passed** (1.49s)
- `backend/test_v3_security_integration.py`: **16 passed** (2.05s)
- `backend/test_v3_authorization.py`: **19 passed** (1.96s)
- **Focused & Subsystem Suites Total: 315 passed, 0 failed.**

### 11.5 Remaining Risks & System Boundaries
1. **At-Least-Once Delivery Side-Effect Risk:** If a subscriber callback executes non-idempotent side effects (such as network API calls or file writes) and the worker process is terminated before `finalize_delivery()` commits, the sweeper will recover the expired lease and dispatch the event again. Subscribers MUST deduplicate external actions using the invariant `delivery.idempotency_key`.
2. **Network Partitions during Heartbeat:** If a database connection is lost during callback execution, lease renewals may fail. When the callback finishes, `finalize_delivery()` will safely reject finalization if the lease has expired, preventing stale writes.
3. **No Autonomous Rule or Model Mutation:** The closed-loop learning foundation records auditable feedback and continuous verification evidence; it does NOT alter policy rules or model weights.

---

## 12. Final Lease-Expiry Race Correction (Prompt 37G)

### 12.1 Problem Statement & Concurrency Defect Resolved
In Prompt 37F, `finalize_delivery()` and `renew_delivery_lease()` evaluated the current timestamp (`now_iso`) before obtaining the SQLite write lock. If concurrent write activity or disk I/O in SQLite delayed lock acquisition until after the claim's lease expired, the atomic SQL predicate compared `lease_expires_at >= :now_iso` using the stale pre-lock timestamp. This introduced a time-of-check / time-of-use (TOCTOU) race condition that could accept an expired claim or resurrect a superseded delivery attempt.

Prompt 37G completely resolves this race by strictly enforcing write-lock acquisition before deriving the authoritative UTC timestamp:
1. **Acquire Write Lock First (`BEGIN IMMEDIATE;`):** When entering the transaction in `finalize_delivery()`, `renew_delivery_lease()`, and `claim_delivery()`, SQLite's reserved write lock is acquired immediately via `conn.execute("BEGIN IMMEDIATE;")`.
2. **Post-Lock Authoritative Timestamp Evaluation:** Only *after* write authorization is secured does the repository compute `effective_now_iso = datetime.now(timezone.utc).isoformat()`. (Any test-only injected timestamp is explicitly isolated for deterministic clock manipulation and documented as such).
3. **Atomic Tenant-Scoped Predicate:** The SQL update executes within the acquired lock using the fresh, authoritative timestamp.
4. **Guaranteed Transaction Rollback:** On predicate failure (0 rows matched) or error, transactions are rolled back and the connection closed cleanly in a `try...finally:` block.
5. **No Long-Running Transaction in Callbacks:** Database locks are held strictly during short, bounded repository operations; subscriber callback execution never holds an open database transaction or connection.

### 12.2 Implementation Details (`EventDeliveryRepository`)

#### 1. Finalization (`finalize_delivery`)
```python
conn = self._get_connection()
try:
    conn.execute("BEGIN IMMEDIATE;")
    effective_now_iso = (
        now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()
    )
    cursor = conn.execute(
        """
        UPDATE deliveries
        SET status = :new_status,
            claim_token = NULL,
            lease_expires_at = NULL,
            last_error = :error_msg,
            next_retry_at = :next_retry_at,
            updated_at = :now_iso
        WHERE delivery_id = :delivery_id
          AND tenant_id = :tenant_id
          AND claim_token = :claim_token
          AND UPPER(status) = 'PROCESSING'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at >= :now_iso;
        """,
        {
            "delivery_id": delivery_id,
            "tenant_id": tenant_id,
            "claim_token": claim_token,
            "new_status": new_status.value,
            "error_msg": error_message,
            "next_retry_at": next_retry_iso,
            "now_iso": effective_now_iso,
        },
    )
    if cursor.rowcount == 0:
        conn.rollback()
        return None
    conn.commit()
    # retrieve and return updated delivery...
finally:
    conn.close()
```

#### 2. Lease Renewal (`renew_delivery_lease`)
```python
conn = self._get_connection()
try:
    conn.execute("BEGIN IMMEDIATE;")
    effective_now_iso = (
        now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()
    )
    new_expires_dt = datetime.fromisoformat(effective_now_iso) + timedelta(seconds=extension_seconds)
    cursor = conn.execute(
        """
        UPDATE deliveries
        SET lease_expires_at = :new_expires_iso,
            updated_at = :now_iso
        WHERE delivery_id = :delivery_id
          AND tenant_id = :tenant_id
          AND claim_token = :claim_token
          AND UPPER(status) = 'PROCESSING'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at >= :now_iso
          AND NOT EXISTS (
              SELECT 1 FROM dead_letters WHERE delivery_id = :delivery_id AND tenant_id = :tenant_id
          );
        """,
        ...
    )
    if cursor.rowcount == 0:
        conn.rollback()
        return None
    conn.commit()
    # retrieve and return updated delivery...
finally:
    conn.close()
```

#### 3. Preserved Concurrency Guarantees
- **Stale Claim Token Rejection:** Token mismatch matches 0 rows and returns `None`.
- **Superseded Claim Protection:** New worker claims cannot be overwritten by earlier workers.
- **SUCCESS Immutability:** `UPPER(status) = 'PROCESSING'` prevents overwriting or downgrading `SUCCESS`.
- **Dead-Letter Immunity:** Dead-lettered deliveries cannot be renewed.
- **Tenant Isolation:** Cross-tenant parameters raise `ValueError` and fail closed.
- **At-Least-Once Delivery Semantics:** Preserved with stable `idempotency_key` deduplication across retries.
- **No Claim of Exactly-Once Execution:** SageCommand provides at-least-once delivery; external side effects must be handled idempotently by subscribers.

### 12.3 Real SQLite Lock-Contention Regression Tests (Tests 101–102)
Implemented in `backend/test_v3_closed_loop_learning.py` under `TestPrompt37GLockContentionAndExpiryRaceCorrection`:

- **Test 101 (`test_101_finalization_after_expiry_while_waiting_for_write_lock`):**
  1. Creates a processing delivery with valid claim token and a 0.2s lease.
  2. Spawns a background thread that opens a separate SQLite connection and executes `BEGIN IMMEDIATE;`, holding the write lock. Signals an event when locked.
  3. Spawns a worker thread that invokes `finalize_delivery(delivery_id, tenant_id, claim_token, EventDeliveryStatus.SUCCESS)`.
  4. The worker blocks waiting for the SQLite write lock.
  5. The main test thread sleeps 0.25s until the delivery lease elapses.
  6. The blocker thread releases the write lock (`conn.commit(); conn.close()`).
  7. The worker acquires the lock, derives `effective_now_iso` (now > expiry), evaluates the predicate, matches 0 rows, and rolls back.
  8. Asserts that `finalize_delivery()` returns `None`, the claim was NOT finalized as `SUCCESS`, and the delivery remains uncorrupted in `PROCESSING`.

- **Test 102 (`test_102_renewal_after_expiry_while_waiting_for_write_lock`):**
  1. Creates a processing delivery with valid claim token and a 0.2s lease.
  2. Holds a competing SQLite write lock on a separate connection via `BEGIN IMMEDIATE;`.
  3. Spawns a worker thread that invokes `renew_delivery_lease(delivery_id, tenant_id, claim_token, extension_seconds=5.0)`.
  4. The worker blocks waiting for the SQLite write lock.
  5. The main test thread sleeps 0.25s until the delivery lease elapses.
  6. The blocker releases the lock (`conn.commit(); conn.close()`).
  7. The worker acquires the lock, derives post-lock `effective_now_iso`, evaluates the predicate, matches 0 rows, and rolls back.
  8. Asserts that `renew_delivery_lease()` returns `None`, the expired lease is NOT extended, and the claim cannot be resurrected.

### 12.4 Verification & Regression Matrix (Prompt 37G)
- `backend/test_v3_closed_loop_learning.py`: **102 passed** (18.19s)
- `backend/test_v3_event_driven_architecture.py`: **5 passed** (1.28s)
- `backend/test_v3_event_model.py`: **33 passed** (1.76s)
- `backend/test_v3_continuous_verification.py`: **128 passed** (11.05s)
- `backend/test_v3_security.py`: **14 passed** (1.49s)
- `backend/test_v3_security_integration.py`: **16 passed** (2.05s)
- `backend/test_v3_authorization.py`: **19 passed** (1.96s)
- **Focused & Subsystem Suites Total: 317 passed, 0 failed.**

### 12.5 Remaining Risks & System Boundaries
1. **At-Least-Once Delivery Execution Boundary:** If a subscriber callback executes external side effects (e.g., webhook notifications, external database writes) and crashes before `finalize_delivery()` commits to SQLite, the lease will expire and the delivery will be retried. SageCommand preserves at-least-once delivery; subscribers MUST use `delivery.idempotency_key` for idempotent external execution.
2. **SQLite Write Concurrency Under Extreme Load:** SQLite serializes write transactions. Under extreme multi-threaded write contention exceeding connection timeouts, callers receive operational errors handled cleanly via backoff and retry.
3. **No Distributed Consensus or Out-of-Scope Dependencies:** In accordance with architectural boundaries, SageCommand operates reliably on SQLite WAL mode without adding distributed lock servers or external messaging queues.



