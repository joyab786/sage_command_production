# SageCommand V3 — Production Security Hardening Architecture

## 1. Overview
SageCommand V3 introduces a comprehensive, enterprise-grade production security architecture designed specifically for AI-driven industrial operations. This architecture hardens REST endpoints, WebSocket nervous system connections, database engines, LLM interaction boundaries, and audit logging pipelines.

---

## 2. Core Security Components

### 2.1 Configuration Management (`backend/core/config.py`)
Centralized security settings driven by environment variables with secure production defaults:
- `SAGE_ENV`: Defaults to `production`. `IS_PRODUCTION` is true unless `SAGE_ENV` is explicitly `"development"` or `"test"`. Warnings are emitted at startup if unset, unrecognized, or running in development/test.
- `SAGE_AUTH_ENABLED`: Toggles authentication enforcement (default `true` in production; startup guard refuses to boot if disabled in production).
- `SAGE_AUTH_PROVIDER`: Pluggable authentication provider selection (`development` vs `jwt`). In production, only `jwt` is permitted; `DevAuthenticationProvider` and dev mock tokens are completely disabled.
- `SAGE_JWT_ALGORITHMS`: Restricted to `HS256` in production (RS256 removed until JWKS implemented; `"none"` algorithm is strictly prohibited).
- `SAGE_AUTH_SESSION_CLAIM`: Configurable JWT session claim (default `"session_id"`). When omitted, falls back to OIDC standard `"sid"`. Headers never override or inject session context for JWT identities.
- `SAGE_ALLOWED_ORIGINS`: Strict list of CORS allowed origins (replaces wildcards).
- `SAGE_MAX_REQUEST_SIZE`: Hard ceiling for HTTP and WS request payloads (default 10 MB).
- `SAGE_RATE_LIMIT`: Request quota ceiling per window (default 60 req/min).

### 2.2 Startup Guard & Lifespan Handler (`backend/server.py`, `backend/core/auth.py`)
- Replaces deprecated `@app.on_event("startup")` with a FastAPI `lifespan` handler.
- **Production Guard (`verify_production_boot_guards`)**: Refuses to boot unless:
  1. `SAGE_AUTH_ENABLED` is true.
  2. `SAGE_AUTH_PROVIDER` is `"jwt"`.
  3. `SAGE_AUTH_ISSUER` and `SAGE_AUTH_AUDIENCE` are non-empty strings.
  4. `SAGE_SECRET_KEY` is not the default development literal and is at least 32 bytes (256 bits).
  5. `SAGE_JWT_ALGORITHMS` does not permit `"none"` and uses only `HS256`.
  6. `DEV_MOCK_TOKENS` are unreachable and rejected.

### 2.3 Identity & Role-Based Access Control (`backend/core/auth.py`)
- **`Identity` Model**: Represents caller identity context containing `user_id`, `tenant_id`, `roles`, `permissions`, and `session_id`.
- **`AuthenticationProvider` Interface**:
  - `DevAuthenticationProvider`: Local development mode provider supporting mock tokens (`operator_token`, `manager_token`). Fails closed in production with HTTP 401.
  - `JWTAuthenticationProvider`: Enterprise JWT/OIDC token verification provider. In production, enforces strict decode options requiring and verifying `signature`, `exp`, `iss`, `aud`, and `sub`.
- **`require_role(role)` Dependency**: Enforces strict role checks on API endpoints. Returns HTTP 403 Forbidden on role mismatch.

### 2.4 Route Fail-Closed Hardening
- **Policy Evaluation & Simulation (`/api/v3/policies/evaluate`, `/simulate`)**: Rejects requests lacking session with HTTP 401 `MISSING_SESSION`. Never falls back to `"session_default"`.
- **Database Connection Management (`/api/v3/database/connections`)**:
  - `list_connections`: Missing session returns HTTP 400 `MISSING_SESSION` (does not return an empty 200).
  - `revoke_connection`: Requires active session and restricts revocation to the caller's session within tenant. Cross-session revocation by non-admin callers returns HTTP 403 `AUTHORIZATION_DENIED`. Administrators with clearance level 3 can execute audited admin overrides (`ADMIN_DATABASE_CONNECTION_REVOKED`).
  - All database endpoints (`get`, `health`, `schema`, `sample`, `disconnect`, `revoke`, `list`) fail closed with HTTP 400/401/403/404 and strictly zero 500s.

### 2.5 Credential Redaction (`backend/governance/redaction.py`)
- **`sanitize_connection_string`**: Uses regex substitution to replace plain passwords in database connection URIs (`postgresql://user:[REDACTED]@host:5432/db`) and key-value strings (`password=[REDACTED]`).
- **`parse_safe_connection_info`**: Extracts connection metadata into a safe `ConnectionInfo` model without retaining raw passwords.
- **`sanitize_log_message`**: Redacts passwords, JWT Bearer tokens, and API key query parameters from all error strings before logging or transmission over WebSockets.

### 2.4 SQL & URI Guardrails (`backend/governance/guardrails.py` & `backend/services/db_service.py`)
- **URI Scheme Whitelisting**: `validate_db_connection_uri` accepts only `postgresql://`, `mysql://`, and `sqlite://` schemes. Blocks arbitrary file/network protocol URIs (`file://`, `ftp://`, `http://`).
- **Multi-Statement SQL Protection**: `check_multi_statement_sql` parses SQL queries to detect and block semicolon-separated statement chaining.
- **Unsafe SQL & Catalog Protection**: `validate_sql_query` blocks destructive keywords (`DROP`, `ALTER`, `TRUNCATE`, `GRANT`) and prevents unauthorized access to internal system catalog tables (`pg_catalog`, `sqlite_master`, `information_schema`).

### 2.5 Security Middleware & Exception Handler (`backend/governance/middleware.py`)
- **`SecurityHeadersMiddleware`**: Injects modern HTTP defense headers on every response:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Content-Security-Policy: default-src 'self' ...`
- **`RequestSizeLimiterMiddleware`**: Rejects requests exceeding `SAGE_MAX_REQUEST_SIZE` with HTTP 413 Payload Too Large.
- **`safe_production_exception_handler`**: Catches unhandled exceptions, sanitizes sensitive data, assigns unique `request_id`, and prevents traceback leakages in production.

### 2.6 WebSocket Nervous System Hardening (`backend/api/websocket.py`)
- **Handshake Authentication**: Inspects query string `token` or authorization headers before establishing session.
- **Message Payload Limit**: Enforces payload size checks on incoming frame data.
- **Session Isolation**: Associates `Identity` context with `websocket.state`.
- **Human-in-the-Loop RBAC**: Enforces `manager` clearance on `approve` commands for high-risk actions.
- **Audit Logging**: Emits structured security events on connect, disconnect, rate limit, and authorization failures.

### 2.7 SSRF Guard, Network Policy & Driver Address Pinning (`backend/gateway/network_policy.py`, `backend/gateway/db_gateway.py`)
- **DNS Resolution & Multi-Record Inspection**: Resolves target hostnames to all `A` and `AAAA` records. If *any* resolved address belongs to a prohibited category, the target is rejected immediately.
- **Prohibited / Never-Allowlistable Networks**:
  - `169.254.0.0/16` and `fe80::/10` (Cloud / IPv6 link-local metadata)
  - `fd00:ec2::254/128` (AWS IMDSv6)
  - `100.100.100.200/32` (Alibaba Cloud metadata)
  - `0.0.0.0/8` and `::/128` (Unspecified addresses)
  - `224.0.0.0/4` and `ff00::/8` (Multicast ranges)
  - `240.0.0.0/4` (Reserved range)
  - Unusual IP representations (octal, hex, decimal integer literals) are rejected.
  - IPv4-mapped IPv6 (`::ffff:x.x.x.x`) and 6to4 (`2002::/16`) addresses are unwrapped to their underlying IPv4 addresses before policy checks.
- **Production Default for `SAGE_DB_ALLOWED_HOSTS`**:
  - The production default is **DENY** (empty list). Private IP ranges (RFC 1918 `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, RFC 6598 `100.64.0.0/10`, and RFC 4193 `fc00::/7`) and loopback (`127.0.0.0/8`, `::1`) are strictly blocked in production unless explicitly included in `SAGE_DB_ALLOWED_HOSTS`. Loopback is permitted only in `development` and `test` environments.
- **Driver Address Pinning Feasibility**:
  To eliminate DNS rebinding between policy verification and connection establishment, the gateway resolves and validates the address upfront:

| Database Driver / Engine | Address Pinning Feasibility | Implementation Details |
| :--- | :--- | :--- |
| **PostgreSQL** (`psycopg2` / `libpq`) | **FEASIBLE** (Implemented) | Supported via `connect_args["hostaddr"] = pinned_ip` while retaining original `host` for TLS SNI and server certificate validation. |
| **MySQL** (`pymysql` / `mysqlclient`) | **NOT FEASIBLE** (Dual host/hostaddr) | PyMySQL lacks separate `hostaddr` argument. Replacing `host` with IP breaks TLS SNI and certificate hostname matching. |
| **MSSQL** (`pyodbc` / FreeTDS) | **NOT FEASIBLE** (Dual host/hostaddr) | Standard ODBC connection strings lack distinct TCP hostaddr vs TLS SNI host parameter without custom driver configuration. |
| **SQLite** | **N/A** (Local Filesystem) | Operates on local filesystem paths; network socket pinning is not applicable. |

- **Uniform SSRF Error Handling**:
  Blocked, unreachable, and refused targets return an identical HTTP 503 response with error code `DATABASE_UNREACHABLE` and message `"Database host connection refused, blocked, or unreachable."` No internal IP addresses, resolved targets, or low-level driver stack traces are exposed to clients.
- **(Tenant, User) Rate Limiting**:
  - `/api/v3/database/connections/test`: 10 requests per minute per `(tenant, user)`.
  - `/api/v3/database/connections` and `/connect-live-db`: 10 requests per minute (shared limit) per `(tenant, user)`.
  - Exceeded rate limits return HTTP 429 Too Many Requests with a `Retry-After: <seconds>` header.
  - **Process-Local Limitation**: `SlidingWindowRateLimiter` operates in-memory within the active Python process. When running multi-worker deployments (e.g. Uvicorn `--workers > 1`), limits apply on a per-process basis. Production multi-node clusters should back this limiter with Redis.

---

## 3. Verification & Compliance
All security modules are validated by the automated test suites:
- `backend/test_v3_security.py` (42 tests)
- `backend/test_v3_session_fail_closed.py` (35 tests)
- `backend/test_v3_ssrf_guardrails.py` (12 tests, 36 subtests)
- Full backend suite: 2,585 passed tests.

