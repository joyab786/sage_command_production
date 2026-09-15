# SAGECOMMAND V3 — DETERMINISTIC EXECUTION GATEWAY ARCHITECTURE

## 1. Executive Summary & Architectural Role

The **Execution Gateway** (Prompt 10) establishes the single server-authoritative, deterministic final write boundary for SageCommand OS V3. Prior to Prompt 10, all physical mutation endpoints (`/api/v3/actions/{id}/execute`, `/api/v3/transactions/{id}/execute`, `/api/v3/transactions/{id}/rollback`) returned hardcoded HTTP 405 Method Not Allowed responses to safeguard the system during foundational development.

With Prompt 10, the Execution Gateway is the **ONLY** component in the entire platform authorized to execute operational mutations and modify persistent business state. All agents, copilots, WebSocket handlers, and REST controllers must submit execution requests through this gateway.

### Cardinal Architectural Invariant

$$\text{Authentication} \neq \text{Authorization} \neq \text{Policy} \neq \text{Approval} \neq \text{Transaction Plan} \neq \text{Execution} \neq \text{Verification} \neq \text{Rollback} \neq \text{Audit}$$

```text
PROPOSED ACTION / INCIDENT MITIGATION
       ↓
ACTION SCHEMA VALIDATION (Prompt 05)
       ↓
RBAC + ABAC AUTHORIZATION (Prompt 07)
       ↓
DETERMINISTIC POLICY ENGINE (Prompt 06)
       ↓
HUMAN-IN-THE-LOOP / TWO-PERSON APPROVAL (Prompt 05 / 10)
       ↓
TRANSACTION PLANNING & DRIFT VALIDATION (Prompt 09)
       ↓
═══════════════════════════════════════════════════════════════════════
  EXECUTION GATEWAY — MULTI-GATE WRITE BOUNDARY (Prompt 10)
  [Gate 01] Cryptographic Identity & Multi-tenant Context Extraction
  [Gate 02] RBAC / ABAC Permission Revalidation (action.execute / transaction.execute)
  [Gate 03] Target Scope & Boundary Matching (Tenant / Workspace / Plant)
  [Gate 04] Deterministic State Machine Validation
  [Gate 05] Cryptographic Hash & Expiry / Staleness Verification
  [Gate 06] Two-Person Rule Approval Verification (Proposer != Approver)
  [Gate 07] Immediate Pre-Execution Policy Re-Evaluation
  [Gate 08] Deterministic Idempotency Verification & Replay Protection
  [Gate 09] Concurrency Lock Acquisition (Resource / Target Mutex)
  [Gate 10] Parameterized Database Write Adapter & Simulation Defense
═══════════════════════════════════════════════════════════════════════
       ↓                                                     ↓
ATOMIC PHYSICAL MUTATION                             IMMUTABLE AUDIT RECORD
(Session DB Gateway, Zero Raw SQL)                 (Tamper-Evident SHA-256 Ledger)
```

---

## 2. Multi-Gate Execution Pipeline

Every execution request passes through ten sequential security and integrity gates before any write operation is committed. A failure at any gate halts execution immediately (fails closed):

### Gate 1: Cryptographic Identity & Multi-tenant Extraction
- Extracts authenticated identity from cryptographic JWT verification (`get_current_identity`).
- Fails closed if identity is missing, expired, or tampered.
- Strictly bounds execution context to `identity.tenant_id` and `identity.workspace_id`.

### Gate 2: RBAC & ABAC Permission Revalidation
- Enforces strict role and capability checks using `AuthorizationService.evaluate_access`:
  - Action execution requires `action.execute` (granted to `OPERATOR`, `PLANT_MANAGER`, `SAFETY_MANAGER`).
  - Transaction execution requires `transaction.execute` (granted to `OPERATOR`, `PLANT_MANAGER`, `SAFETY_MANAGER`).
  - Transaction rollback requires `transaction.rollback` (strictly restricted to `PLANT_MANAGER`, `SAFETY_MANAGER`).
- Admin users (`ADMINISTRATOR`) without operational roles are explicitly blocked from executing industrial writes.

### Gate 3: Target Scope & Isolation Matching
- Validates that the executing identity's tenant and workspace match the target action/transaction.
- Cross-tenant execution attempts trigger high-severity audit alerts (`CROSS_TENANT_EXECUTION_ATTEMPT`) and raise HTTP 403.
- Plant-level scoping (`plant_id`) is strictly enforced when defined.

### Gate 4: State Machine Guarding
- Actions must reside in `APPROVED` or `READY` status to execute.
- Transitions action lifecycle: `APPROVED/READY` $\to$ `EXECUTING` $\to$ `SUCCEEDED` (or `FAILED`).
- Transactions must reside in `READY`, `PLANNED`, or `AWAITING_EXECUTION`.
- Transitions transaction lifecycle: `READY` $\to$ `EXECUTING` $\to$ `COMMITTED` (or `FAILED`).
- Attempting to execute an already completed action/transaction returns idempotent cached results or raises HTTP 409.

### Gate 5: Cryptographic Hash & Expiry Verification
- Recomputes canonical SHA-256 fingerprint over action/transaction parameters.
- Rejects tampered payloads with HTTP 400 (`INTEGRITY_VIOLATION`) and transitions action to `STALE`.
- Verifies TTL expiration (`expires_at`). Expired actions/transactions are transitioned to `EXPIRED` and rejected.

### Gate 6: Dual Governance & Two-Person Verification
- When `requires_approval=True`, enforces that the action was approved by an authorized manager.
- Strictly enforces the **Two-Person Rule**: Proposer cannot approve their own action (`proposer_id != approver_id`).
- Actions awaiting approval cannot bypass human signoff.

### Gate 7: Policy Engine Revalidation
- Invokes `PolicyEngine.evaluate_action()` immediately prior to execution to detect policy drifts.
- Re-evaluates risk levels, constraints, blackout windows, and safety limits.
- If policy evaluation denies the action or requires re-approval, execution is blocked with HTTP 403 (`POLICY_DENIED`).

### Gate 8: Idempotency & Deduplication
- Checks client-supplied `idempotency_key` against the gateway's idempotency cache.
- Duplicate requests return the exact previous `ExecutionResult` without re-executing writes.
- Prevents double-execution of financial transfers, order placements, or equipment actuations.

### Gate 9: Concurrency Locking
- Acquires non-blocking threading locks per resource identifier (`f"{tenant_id}:{target.resource_id}"`).
- If another worker or thread is currently executing against the same resource, raises HTTP 409 (`CONCURRENT_EXECUTION`).
- Automatically releases locks in `finally` blocks upon completion or failure.

### Gate 10: Parameterized Database Write Adapter & Simulation Defense
- **Zero Raw SQL**: The gateway strictly rejects arbitrary SQL strings. All physical writes are dispatched through parameterized domain adapters:
  - `UPDATE_INVENTORY`: Parameterized updates against the `inventory` table.
  - `SET_MACHINE_STATUS`: Parameterized updates against machine status.
  - `DISPATCH_ORDER` / `GENERIC_WRITE`: Strongly validated structured parameters.
- **Simulation Mode Defense**: When `data_mode="SIMULATION"`, `dry_run=True`, or the target database is in simulation mode:
  - The adapter performs dry-run calculations only.
  - Zero rows are modified (`affected_rows = 0`).
  - Physical database tables remain completely untouched.

---

## 3. Transaction Execution & Rollback Engine

### 3.1 Transaction Execution
When executing a transaction plan (`POST /api/v3/transactions/{id}/execute`):
1. Revalidates all preconditions declared in the `TransactionPlan` (e.g. inventory levels, equipment states).
2. Verifies business invariants (e.g. non-negative stock, valid ranges).
3. Acquires transaction-level concurrency locks.
4. Executes underlying operational actions via the deterministic write adapter.
5. Transitions transaction state: `READY` $\to$ `EXECUTING` $\to$ `COMMITTED`.
6. Emits tamper-evident `TRANSACTION_COMMITTED` audit event to the append-only ledger.

### 3.2 Transaction Rollback
When rolling back a committed transaction (`POST /api/v3/transactions/{id}/rollback`):
1. Restricts caller to privileged roles (`PLANT_MANAGER`, `SAFETY_MANAGER`).
2. Validates transaction status: Must be `COMMITTED`, `FAILED`, or `ROLLBACK_PENDING`.
3. Verifies `RollbackCapability`:
   - If marked `NOT_SUPPORTED` or `IRREVERSIBLE`, rollback is rejected with HTTP 400 (`ROLLBACK_NOT_SUPPORTED`).
   - If `SUPPORTED` or `PARTIALLY_SUPPORTED`, the rollback engine proceeds.
4. Executes compensating actions in reverse topological order.
5. Transitions transaction state: `COMMITTED` $\to$ `ROLLING_BACK` $\to$ `ROLLED_BACK`.
6. Emits `TRANSACTION_ROLLED_BACK` audit event.

---

## 4. API Endpoints & Interfaces

| Method | Path | Required Permission | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v3/actions/{action_id}/execute` | `action.execute` | Execute approved action via gateway |
| `POST` | `/api/v3/actions/{action_id}/approve` | `action.approve` | Approve action under two-person rule |
| `POST` | `/api/v3/transactions/{transaction_id}/execute` | `transaction.execute` | Execute transaction plan via gateway |
| `POST` | `/api/v3/transactions/{transaction_id}/rollback` | `transaction.rollback` | Roll back transaction via compensating engine |

### WebSocket Real-time Execution
In `backend/api/websocket.py`:
- `execute` message commands are dispatched directly to `execution_gateway.execute_action`.
- `approve` message commands revalidate permissions, check the two-person rule, and transition actions to `APPROVED`.
- Execution results are broadcasted to connected clients with authoritative execution IDs and timestamps.

---

## 5. Audit & Provenance

Every invocation of the Execution Gateway records cryptographic audit events in the `AuditLedgerService`:
- `ACTION_EXECUTING` / `ACTION_EXECUTED` / `ACTION_EXECUTION_FAILED`
- `TRANSACTION_EXECUTING` / `TRANSACTION_COMMITTED` / `TRANSACTION_EXECUTION_FAILED`
- `TRANSACTION_ROLLING_BACK` / `TRANSACTION_ROLLED_BACK` / `TRANSACTION_ROLLBACK_FAILED`

All audit records compute SHA-256 integrity fingerprints over canonical serialized payloads including actor, tenant, action ID, affected rows, and execution duration.
