# SageCommand V3 — STRIDE Security Threat Model

## 1. Overview
This document outlines the STRIDE Threat Model for SageCommand V3, an AI Operating System for Industrial Operations. Industrial operations involve direct interaction with critical datacores, real-time telemetry streams, vision diagnostics, and high-risk control actions. The security posture adheres to the core principle:

> **"LLMs may reason, but deterministic security systems must enforce."**

---

## 2. System Boundaries & Data Flow Vectors
- **Boundary A: Web Client / UI (Next.js 16)** $\rightarrow$ **FastAPI Gateway (HTTP / WebSocket)**
- **Boundary B: FastAPI Gateway** $\rightarrow$ **LangGraph Agent Nervous System (Copilot, Discovery, Vision, Security)**
- **Boundary C: LangGraph Nodes / Tools** $\rightarrow$ **SQL Database Engine (PostgreSQL, MySQL, SQLite)**
- **Boundary D: Agent System** $\rightarrow$ **LLM Provider API (Groq / Google Gemini)**

---

## 3. STRIDE Threat Matrix

| Threat Category | Identifier | Description & Risk Vector | V3 Deterministic Mitigation | Verification Status |
| :--- | :--- | :--- | :--- | :--- |
| **Spoofing Identity** | `T-SPOOF-01` | Unauthorized user connects to REST API or WebSocket endpoint without valid credentials. | Pluggable `AuthenticationProvider` (`DevAuthenticationProvider` for local, `JWTAuthenticationProvider` for production). WS handshake token inspection. | **VERIFIED** (`test_v3_security.py`) |
| **Tampering Data** | `T-TAMP-01` | LLM or malicious user injects multi-statement SQL (`SELECT; DROP TABLE`) or unsafe DDL statements. | `check_multi_statement_sql` AST parsing blocks multi-statements; `validate_sql_query` enforces word-bounded keyword blocking (`DROP`, `ALTER`, `TRUNCATE`) and system catalog protection (`pg_catalog`, `sqlite_master`). | **VERIFIED** (`test_v3_security.py`) |
| **Repudiation** | `T-REP-01` | Operator executes high-risk database mutation or state rollback without audit trail. | `log_security_event` captures structured JSON audit logs (timestamp, user_id, action, status, client_ip) with zero credential logging. | **VERIFIED** (`test_v3_security.py`) |
| **Information Disclosure** | `T-INFO-01` | Database connection strings or LLM API keys leaked in WebSocket messages, REST errors, or logs. | `sanitize_connection_string` & `sanitize_log_message` replace passwords/keys with `[REDACTED]`. `safe_production_exception_handler` prevents traceback leakage. | **VERIFIED** (`test_v3_security.py`) |
| **Denial of Service** | `T-DOS-01` | Attacker overwhelms server with oversized WebSocket/HTTP payloads or API request floods. | `RequestSizeLimiterMiddleware` enforces `SAGE_MAX_REQUEST_SIZE` (10MB). `SlidingWindowRateLimiter` enforces request quotas per identity/IP. | **VERIFIED** (`test_v3_security.py`) |
| **Elevation of Privilege** | `T-ELEV-01` | Operator role approves high-risk execution actions requiring Manager clearance. | `require_role("manager")` dependency & WS `approve` command role verification block unauthorized execution past Human-in-the-Loop gates. | **VERIFIED** (`test_v3_security.py`) |

---

## 4. Threat Mitigation Architectural Rules

1. **Deterministic Execution Control**: LLM output is parsed as intent, never trusted for direct raw execution without schema validation and guardrail checks.
2. **Zero Insecure Connection Strings**: All database URIs passed via REST or config are validated against scheme whitelists (`postgresql`, `mysql`, `sqlite`) and immediately parsed into safe `ConnectionInfo` models.
3. **Defense in Depth**: Security headers (`CSP`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`) are applied at the middleware layer for all responses.
