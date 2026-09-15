# SageCommand V3 — Production Security Hardening Architecture

## 1. Overview
SageCommand V3 introduces a comprehensive, enterprise-grade production security architecture designed specifically for AI-driven industrial operations. This architecture hardens REST endpoints, WebSocket nervous system connections, database engines, LLM interaction boundaries, and audit logging pipelines.

---

## 2. Core Security Components

### 2.1 Configuration Management (`backend/core/config.py`)
Centralized security settings driven by environment variables with secure production defaults:
- `SAGE_ENV`: Set to `production` or `development`.
- `SAGE_AUTH_ENABLED`: Toggles authentication enforcement (default `true` in production).
- `SAGE_AUTH_PROVIDER`: Pluggable authentication provider selection (`development` vs `jwt`).
- `SAGE_ALLOWED_ORIGINS`: Strict list of CORS allowed origins (replaces wildcards).
- `SAGE_MAX_REQUEST_SIZE`: Hard ceiling for HTTP and WS request payloads (default 10 MB).
- `SAGE_RATE_LIMIT`: Request quota ceiling per window (default 60 req/min).

### 2.2 Identity & Role-Based Access Control (`backend/core/auth.py`)
- **`Identity` Model**: Represents caller identity context containing `user_id`, `tenant_id`, `roles`, `permissions`, and `session_id`.
- **`AuthenticationProvider` Interface**:
  - `DevAuthenticationProvider`: Local development mode provider supporting mock tokens (`operator_token`, `manager_token`).
  - `JWTAuthenticationProvider`: Enterprise JWT/OIDC token verification provider validating signatures, expiration, and issuer claims.
- **`require_role(role)` Dependency**: Enforces strict role checks on API endpoints. Returns HTTP 403 Forbidden on role mismatch.

### 2.3 Credential Redaction (`backend/governance/redaction.py`)
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

---

## 3. Verification & Compliance
All security modules are validated by the automated test suite `backend/test_v3_security.py` (42 tests, 100% pass rate).
