# SageCommand V3 — Pre-Prompt-10 Security, Identity & Session Isolation Remediation Guide

**Milestone**: PRE-PROMPT-10 ARCHITECTURAL REMEDIATION  
**Status**: COMPLETE & VERIFIED  
**Deterministic Safety Principle**: "LLMs reason. Deterministic systems enforce. No execution without authoritative identity, isolated state, and cryptographic boundaries."

---

## 1. Executive Summary

Prior to implementing Prompt 10 (Execution Gateway), a comprehensive integration audit of Prompts 01–09 identified seven critical security and isolation vulnerabilities. These vulnerabilities allowed client-controlled identity headers to override verified identities, permitted read-only Copilot tools to execute mutating SQL statements without approval, leaked global database state across concurrent sessions, allowed legacy endpoints to mutate a global singleton, stored uploaded files in a shared unisolated directory, configured insecure wildcard CORS origins, and permitted WebSocket approvals to simulate mutation without gating.

This remediation addresses all seven blockers directly in the repository while preserving the existing V3 architecture and all valid operational capabilities. The Execution Gateway (`POST /api/v3/actions/{id}/execute`, `POST /api/v3/transactions/{id}/execute`, and `/rollback`) remains strictly disabled (returning HTTP 405), ensuring that no unvetted mutations can occur until Prompt 10 is implemented.

All 163 pre-existing tests continue to pass without regression, 16 new security integration tests pass cleanly (179 total tests passing, 0 failures, 0 errors), and the frontend compiles successfully with zero build errors.

---

## 2. Root Causes & Remediations

### VULN-001: Client Identity Header Spoofing (CRITICAL)
- **Root Cause**: `get_current_identity()` in `backend/core/auth.py` extracted client-supplied HTTP headers (`X-Clearance-Level`, `X-Assigned-Plants`, `X-Tenant-ID`, `X-Session-ID`) and directly mutated the resolved `Identity` object, even when a valid JWT token was provided. This allowed any unprivileged operator or external client to forge manager clearance or access other tenants by supplying headers. Furthermore, `JWTAuthenticationProvider` lacked cryptographic signature verification, failing open and parsing raw payload segments without signature validation, expiration checking, or algorithm pinning.
- **Fix**:
  1. Updated `Identity` model to track `is_server_authoritative: bool = Field(default=False)`.
  2. Implemented full cryptographic signature verification in `JWTAuthenticationProvider` using `PyJWT` with explicit algorithm allowlist (`HS256`, `RS256`), rejecting `"none"` algorithm, verifying expiration (`exp`), checking issuer and audience, and failing closed with HTTP 401 on any error.
  3. Hardened `DevAuthenticationProvider` with explicit server-managed token profiles (`manager_token`, `operator_token`, `admin_token`, `test_token_tenant_a`, `test_token_tenant_b`).
  4. Permanently deleted header overrides for `X-Clearance-Level` and `X-Assigned-Plants`.
  5. Enforced that whenever `identity.is_server_authoritative` is True or `IS_PRODUCTION` is True, client headers (`X-Tenant-ID`, `X-Session-ID`, `X-Workspace-ID`) are strictly ignored.

### VULN-002: Copilot SQL Mutation Bypass (CRITICAL)
- **Root Cause**: `validate_sql_query()` in `backend/governance/guardrails.py` only checked a blocklist of destructive keywords (`drop`, `delete`, `truncate`, `alter`, `grant`, `revoke`). `UPDATE` and `INSERT` were missing. Additionally, queries were not checked for comment obfuscation (`/* ... */`, `--`), statement chaining via semicolons, or mutating Common Table Expressions (`WITH ... INSERT/UPDATE`). Consequently, natural-language Copilot queries via `query_database` could mutate live inventory and shipments without human review or RBAC approval.
- **Fix**:
  1. Added `strip_sql_comments_and_literals()` to strip block comments, line comments, and string literals prior to keyword scanning.
  2. Multi-statement defense: Reject any query containing semicolon statement separators (`check_multi_statement_sql`).
  3. Enforce statement entry constraint: Queries MUST begin with `SELECT`, `WITH`, or `EXPLAIN`. Any other leading keyword immediately raises `PermissionError`.
  4. Expanded prohibited keywords to 24 mutating and administrative verbs: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `REPLACE`, `MERGE`, `UPSERT`, `GRANT`, `REVOKE`, `EXEC`, `EXECUTE`, `CALL`, `PRAGMA`, `ATTACH`, `DETACH`, `COMMIT`, `ROLLBACK`, `SET`, `LOCK`, `SAVEPOINT`, and `INTO` (blocking `SELECT ... INTO`).
  5. CTE Terminal Validation: Ensured that queries starting with `WITH` terminate in a read-only `SELECT` and do not contain mutation verbs.
  6. Maintained system catalog table protection (`sqlite_master`, `information_schema`, `sqlite_schema`, `pg_catalog`).

### VULN-003: Global `dynamic_db` in V3 Agents (HIGH)
- **Root Cause**: The 4 LangGraph agents (`backend/agents/supervisor.py`, `backend/agents/strategy.py`, `backend/agents/risk_analysis.py`, and `backend/agents/evaluator.py`) directly imported and queried `dynamic_db` from `services.db_service` to fetch schema tables and DDL for prompt construction. Because `dynamic_db` is a process-global mutable singleton, concurrent sessions or tenant database updates caused race conditions and cross-tenant schema leakage.
- **Fix**:
  1. Removed all `dynamic_db` imports across `supervisor.py`, `strategy.py`, `risk_analysis.py`, and `evaluator.py`.
  2. Integrated `DatabaseConnectionGateway.get_instance()` via `db_gateway.get_schema_context_for_llm(tenant_id, session_id)`.
  3. Extracted tenant and session IDs from the active LangGraph `SageOSState` (or bound ContextVar fallback) to resolve isolated schema metadata without referencing global state.

### VULN-004: Legacy Database Route Leakage (HIGH)
- **Root Cause**: Legacy endpoints `/connect-live-db` and `/upload-db` in `backend/api/routes.py` accepted unvalidated database connection strings and CSV files, and directly called `dynamic_db.update_engine_safely(new_engine)`. This mutated the global database engine for all active sessions in the application process.
- **Fix**:
  1. Decoupled both `/connect-live-db` and `/upload-db` from `dynamic_db.update_engine_safely`.
  2. Added RFC 7234 deprecation headers (`X-Deprecated: true`, `Warning: 299 - "Endpoint deprecated. Use /api/v3/database/connections instead."`).
  3. Re-routed `/connect-live-db` to register the connection into the session-scoped `db_gateway` under the caller's tenant and session ID.
  4. Updated frontend `handleLiveDbConnect` in `frontend/app/page.tsx` to call canonical V3 `/api/v3/database/connections` with `access_mode: "READ_ONLY"` and explicit `database_type`.

### VULN-005: Shared Upload Storage (MEDIUM)
- **Root Cause**: `/upload-db` stored uploaded SQLite and CSV files in a shared, unpartitioned file path (`DEFAULT_DB_PATH` = `data/factory.db`), allowing concurrent tenant uploads to overwrite each other's data files.
- **Fix**:
  1. Partitioned upload storage by tenant and session: `data/uploads/{tenant_id}/{session_id}/{filename}`.
  2. Sanitized file names with `os.path.basename` to prevent path traversal attacks.
  3. Bound created database engines strictly to the caller's session context in `db_gateway`.

### VULN-006: CORS Wildcard with Credentials (MEDIUM)
- **Root Cause**: `CORSMiddleware` in `backend/server.py` allowed `allow_origins=["*"]` while `allow_credentials=True` when `SAGE_CORS_ORIGINS` was empty or wildcarded. Web browsers and security specs (W3C CORS) prohibit wildcard origins when credentials are enabled due to CSRF and credential exposure risks.
- **Fix**:
  1. Hardened origin resolution: Prohibited `allow_origins=["*"]` when `allow_credentials=True`.
  2. In production, if wildcard is detected, origins are restricted to `None` (blocking cross-origin credentialed requests).
  3. Sanitized default development origins to explicit domains: `http://localhost:3000`, `http://127.0.0.1:3000`.

### VULN-007: WebSocket Mutation Bypass & Invariant Drift (MEDIUM)
- **Root Cause**: In `backend/api/websocket.py`, the `command == "approve"` handler performed immediate simulation updates without verifying session or tenant ownership, logged simulated action execution, and accepted a command called `rollback` which confused checkpoint reversion with transactional database rollback.
- **Fix**:
  1. Enforced session and tenant validation on WebSocket approval commands.
  2. Verified caller identity roles via RBAC before acknowledging approval commands.
  3. Emitted explicit audit logs indicating that execution is deferred to the Execution Gateway (no operational DB mutation executed via WebSocket).
  4. Aliased and documented state reversion as `revert_checkpoint` to prevent conflation with V3 transactional database rollback.

---

## 3. Architectural Changes

### 3.1 Identity Resolution Flow

#### Before Remediation:
```
Client Request -> Extracts Bearer Token -> DevAuthProvider returns Identity (clearance=1)
               -> Header Parser:
                    Reads X-Clearance-Level: 3  ==> OVERWRITES clearance to 3!
                    Reads X-Assigned-Plants: *  ==> OVERWRITES assigned_plants to *!
                    Reads X-Tenant-ID: tenant_b ==> OVERWRITES tenant_id to tenant_b!
               -> Request executes with spoofed privileges (VULN-001)
```

#### After Remediation:
```
Client Request -> Bearer Token -> JWTAuthenticationProvider
                                    ├── Verify HMAC/RSA Signature (fail closed)
                                    ├── Verify exp, nbf, iat
                                    ├── Verify alg in [HS256, RS256] (block 'none')
                                    └── Extract authoritative claims (tenant_id, roles, clearance_level)
                                    └── Set is_server_authoritative = True
               -> Identity Hook:
                    if identity.is_server_authoritative or IS_PRODUCTION:
                        RETURN identity immediately.
                        Headers (X-Clearance-Level, X-Assigned-Plants, X-Tenant-ID) are IGNORED.
```

### 3.2 Agent Database Schema Resolution

#### Before Remediation:
```
Agent Node (Supervisor/Strategy/Risk/Evaluator)
    └──> import dynamic_db from services.db_service
            └──> dynamic_db.get_table_info() (Process-Global Singleton - Cross-Tenant Leak)
```

#### After Remediation:
```
Agent Node (Supervisor/Strategy/Risk/Evaluator)
    ├── Reads state.get("tenant_id") and state.get("session_id")
    └── Calls DatabaseConnectionGateway.get_instance().get_schema_context_for_llm(tenant_id, session_id)
            └── Inspects ONLY the database connection owned by this tenant/session
```

### 3.3 SQL Guardrail Validation Pipeline

```
Raw Query String
    │
    ├── Layer 1: Semicolon / Multi-Statement Check
    │      └── If ';' present -> PermissionError: Statement chaining prohibited
    │
    ├── Layer 2: Comment & Literal Stripping
    │      └── Removes /* ... */ and -- comments, normalizes whitespace
    │
    ├── Layer 3: Statement Type Entry Enforcement
    │      └── First token MUST be in {"select", "with", "explain"}
    │      └── Prohibits leading UPDATE, INSERT, DROP, ALTER, etc.
    │
    ├── Layer 4: Prohibited Mutating Verbs Scan (Word-Bounded Regex)
    │      └── Blocks: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE,
    │                 REPLACE, MERGE, UPSERT, GRANT, REVOKE, EXEC, EXECUTE,
    │                 CALL, PRAGMA, ATTACH, DETACH, COMMIT, ROLLBACK, INTO
    │
    └── Layer 5: System Catalog Protection
           └── Blocks: sqlite_master, information_schema, sqlite_schema, pg_catalog
```

### 3.4 Upload Storage Structure

```
SageCommand_Production/
└── backend/
    └── data/
        └── uploads/
            ├── {tenant_A}/
            │   └── {session_1}/
            │       └── telemetry_upload.csv
            └── {tenant_B}/
                └── {session_2}/
                    └── isolated_factory.db
```

---

## 4. Security Invariants Established

| Invariant ID | Security Invariant | Enforcement Mechanism | Verification Test |
| :--- | :--- | :--- | :--- |
| **INV-01** | Client headers cannot escalate identity or cross tenants | `get_current_identity` ignores headers when `is_server_authoritative` or in production | `test_client_header_tenant_spoofing_prevented`, `test_client_header_clearance_spoofing_prevented` |
| **INV-02** | Cryptographic token validation with algorithm pinning | `PyJWT` decoding with strict algorithm whitelist (`HS256`, `RS256`), exp verification | `test_jwt_signature_verification_enforced`, `test_jwt_expired_token_rejected`, `test_jwt_none_algorithm_rejected` |
| **INV-03** | Copilot SQL queries are strictly read-only | `validate_sql_query` comment stripping, multi-statement check, SELECT/WITH-only entry | `test_copilot_sql_mutation_bypass` |
| **INV-04** | Agent schema queries isolated per tenant/session | Agents query `db_gateway.get_schema_context_for_llm` using state context | `test_agents_do_not_import_or_use_dynamic_db`, `test_cross_session_database_isolation` |
| **INV-05** | Legacy routes cannot mutate global state | `/connect-live-db` and `/upload-db` decoupled from `dynamic_db` | `test_legacy_routes_do_not_mutate_global_state`, `test_legacy_endpoints_emit_deprecation_headers` |
| **INV-06** | Upload storage isolated per tenant/session | File uploads saved to `uploads/{tenant_id}/{session_id}/` | `test_upload_storage_isolation` |
| **INV-07** | CORS credentials protected against wildcards | `server.py` rejects `*` origin when credentials enabled | `test_cors_wildcard_with_credentials_prohibited` |
| **INV-08** | WebSocket approval cannot execute DB mutations | WebSocket handler enforces RBAC and delegates execution | `test_websocket_approval_cannot_execute_mutations`, `test_websocket_checkpoint_reversion_renamed` |
| **INV-09** | Execution Gateway boundary preserved | `POST /actions/{id}/execute` & `POST /transactions/{id}/execute` return HTTP 405 | `test_execution_gateway_endpoints_remain_disabled` |

---

## 5. Verification Summary

- **Total Test Suites Run**: 12 test files across `backend/`.
- **Total Tests Executed**: 179
- **Passed**: 179 (100%)
- **Failures**: 0
- **Errors**: 0
- **Skipped**: 0
- **Frontend Build**: `npm --prefix frontend run build` succeeded with exit code 0.
