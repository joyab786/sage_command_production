# ⚠️ SageCommand V3 — Architectural Risk Register

This document details systemic architectural risks discovered during the initial inspection of SageCommand V2/V3. These items represent security, concurrency, reliability, and isolation vulnerabilities to be systematically addressed in future V3 roadmap prompts (starting with **Prompt 02: Production Security Hardening**).

---

## 📋 Summary Risk Matrix

| Risk ID | Risk Category | Severity | Description | Target Remediation Prompt |
| :--- | :--- | :--- | :--- | :--- |
| **RISK-01** | Data Integrity | **CRITICAL** | Global Mutable Database State (`DynamicDB` singleton) shared across sessions | Prompt 03 (Data Layer Isolation) |
| **RISK-02** | Security | **CRITICAL** | Unrestricted DB Connection String Injection via `/connect-live-db` REST endpoint | Prompt 02 (Security Hardening) |
| **RISK-03** | Security / Guardrail | **HIGH** | LLM-Generated SQL Execution against production database engine | Prompt 02 (Security Hardening) |
| **RISK-04** | API Security | **HIGH** | Unrestricted CORS Policy (`allow_origins=["*"]`) on FastAPI backend | Prompt 02 (Security Hardening) |
| **RISK-05** | Authentication | **CRITICAL** | Complete Absence of Authentication Tokens / JWT Middleware | Prompt 02 (Security Hardening) |
| **RISK-06** | Authorization | **HIGH** | Role-Based Access Control (RBAC) missing from REST endpoints | Prompt 02 (Security Hardening) |
| **RISK-07** | Secrets Handling | **MEDIUM** | Hardcoded Demo API Key fallback in `backend/core/llm.py` | Prompt 02 (Security Hardening) |
| **RISK-08** | Provenance | **MEDIUM** | Synthetic Factory Simulation Telemetry mixed into primary production DB | Prompt 04 (Provenance Engine) |
| **RISK-09** | Concurrency | **HIGH** | SQLite Database File Locks (`database is locked`) under concurrent writes | Prompt 03 (Data Layer Isolation) |
| **RISK-10** | Session Isolation | **HIGH** | Insecure session thread identifier based on `id(websocket)` memory addresses | Prompt 03 (Session Management) |
| **RISK-11** | Multi-Tenant | **CRITICAL** | Hot-swapping DB engine affects ALL active user sessions globally | Prompt 03 (Multi-Tenancy) |
| **RISK-12** | Resiliency | **MEDIUM** | Unhandled background task exceptions terminating simulation loop | Prompt 05 (Task Reliability) |
| **RISK-13** | WebSocket | **MEDIUM** | Unexpected WebSocket disconnection leaves active LangGraph thread interrupted | Prompt 05 (Socket Lifecycle) |
| **RISK-14** | Task Lifecycle | **LOW** | Background task tasks launched without explicit cancellation context | Prompt 05 (Task Lifecycles) |
| **RISK-15** | Persistence | **MEDIUM** | SQLite Saver checkpoint database shared across multi-user execution streams | Prompt 03 (Session Management) |
| **RISK-16** | Race Conditions | **HIGH** | Concurrent simulation writes during evaluator node SQL synthesis | Prompt 03 (Concurrency Control) |
| **RISK-17** | Infrastructure | **MEDIUM** | Single worker Uvicorn development binding (`127.0.0.1:8000`) | Prompt 06 (Production Readiness) |

---

## 🔍 Detailed Risk Audits

### 1. Global Mutable Database State & Multi-Tenant Interference (RISK-01, RISK-11)
- **Discovery**: `dynamic_db = DynamicDB(engine)` is instantiated as a global singleton module instance in [`backend/services/db_service.py`](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/services/db_service.py).
- **Vulnerability**: When User A calls `/connect-live-db` or `/upload-db`, `dynamic_db.update_engine(new_engine)` replaces the SQLAlchemy engine globally for **all** connected WebSocket sessions. User B will immediately lose their database context and execute queries against User A's uploaded database.
- **Remediation**: Transition from global singleton to session-scoped / tenant-scoped database connection manager.

### 2. Connection String Injection & Unauthenticated Endpoints (RISK-02, RISK-05, RISK-06)
- **Discovery**: `/connect-live-db` accepts arbitrary SQLAlchemy connection strings without validation or authentication credentials.
- **Vulnerability**: An unauthenticated malicious user could pass malicious connection strings (e.g. `sqlite:////etc/shadow` or internal enterprise PostgreSQL credentials) or trigger server-side resource exhaustion.
- **Remediation**: Implement JWT authentication headers, URI whitelist verification, and credential encryption.

### 3. Unrestricted CORS & Secrets Exposure (RISK-04, RISK-07)
- **Discovery**: `server.py` sets `allow_origins=["*"]`, enabling any web origin to send requests to the Cortex. `backend/core/llm.py` contains fallback `"DEMO_API_KEY"` strings.
- **Vulnerability**: Cross-Origin Resource Sharing attacks can exfiltrate telemetry data from client browsers. Hardcoded fallback keys could be abused if checked into public repositories.
- **Remediation**: Restrict CORS origins via environment configuration (`ALLOWED_ORIGINS`) and enforce mandatory API key validation on startup.

### 4. SQL Execution from LLM-Generated Strings (RISK-03)
- **Discovery**: Evaluator agent generates raw SQL strings (`sql_query`) which are executed directly by `execution_node` against the production database engine.
- **Vulnerability**: Even with regex-based `validate_sql_query` guardrails, complex or obfuscated SQL statements generated by an LLM could cause unintended table modifications or performance degradation.
- **Remediation**: Transition to structured action models (`StructuredAction`) with parameterized ORM transactions rather than raw SQL text execution.

### 5. Data Provenance & Simulation Labeling (RISK-08)
- **Discovery**: Factory simulator (`backend/services/simulator.py`) directly mutates `dynamic_datacore.sqlite`.
- **Vulnerability**: Operators cannot distinguish whether a stock anomaly was triggered by a real hardware sensor failure or a synthetic background simulation event.
- **Remediation**: Tag all telemetry feeds with `DataProvenance` metadata (`is_simulated: True`).

### 6. SQLite File Locking & Concurrency (RISK-09, RISK-15, RISK-16)
- **Discovery**: SQLite databases (`dynamic_datacore.sqlite` and `sage_memory.sqlite`) operate with default file lock mechanisms.
- **Vulnerability**: Simultaneous writes from background simulation loops and multi-agent execution nodes cause `sqlite3.OperationalError: database is locked` failures.
- **Remediation**: Configure WAL mode (`PRAGMA journal_mode=WAL;`), implement connection pooling, or transition production checkpointers to PostgreSQL / Redis.
