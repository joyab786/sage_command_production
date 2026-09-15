# SageCommand V3 — Database Connection Gateway Canonical API Contract

**Date:** 2026-09-14  
**Version:** SageCommand V3.0  
**Base URL:** `/api/v3/database`  
**Security Classification:** Highly Confidential / Industrial Operational Perimeter  

---

## 1. Overview & Core Architectural Rule

The **Database Connection Gateway** is the mandatory security perimeter between SageCommand and all external database infrastructure.

> **Core Architectural Rule:**  
> The Database Gateway controls connectivity. It does not control business actions.  
> The LLM can request information through approved tools, but it can never choose how credentials are obtained, which network targets are trusted, or which security policies apply.

Arbitrary SQL write execution is **strictly barred** at the gateway level. All state mutations and operational actions must proceed through the **Structured Action API (Prompt 05)**.

---

## 2. Authentication & Request Context

Every request to the Database Connection Gateway must be authenticated.

### 2.1 Headers
- `Authorization: Bearer <jwt_or_auth_token>` (Required)
- `X-Request-ID: <string>` (Optional, correlation tracking, max 64 alphanumeric characters)
- `Idempotency-Key: <string>` (Optional, supported on `POST /connections`)
- `X-Session-ID: <string>` (Optional, preserves session continuity across distributed requests)
- `X-Tenant-ID: <string>` (Optional, scoped tenant verification)

### 2.2 Server-Derived Context
The gateway derives:
- `request_id`
- `user_id`
- `tenant_id`
- `workspace_id`
- `session_id`
- `roles` and `permissions`

from the authenticated server-side context. Client-provided JSON body fields cannot override server-derived tenant or session boundaries.

---

## 3. Core Resource: `DatabaseConnection`

```json
{
  "connection_id": "conn_01JABC",
  "tenant_id": "tenant_001",
  "workspace_id": "workspace_001",
  "session_id": "session_001",
  "plant_id": "plant_001",

  "database_type": "POSTGRESQL",
  "database_name": "operations",

  "status": "CONNECTED",
  "access_mode": "READ_ONLY",
  "data_mode": "REAL",

  "capabilities": {
    "read": true,
    "write": false,
    "transactions": false,
    "schema_inspection": true
  },

  "created_at": "2026-09-14T10:00:00Z",
  "last_used_at": "2026-09-14T10:05:00Z"
}
```

### Prohibited Attributes
Under zero circumstances may any endpoint or log return:
- Plaintext password or hashed credentials
- API keys, access tokens, or private keys
- Raw infrastructure connection URIs containing embedded passwords
- Private TLS certificates or secret keys

---

## 4. Centralized Enums

### 4.1 `DatabaseType`
```text
POSTGRESQL | MYSQL | SQLSERVER | SQLITE
```

### 4.2 `ConnectionStatus`
```text
REQUESTED | VALIDATING | CONNECTING | CONNECTED | HEALTHY | IDLE |
CONNECTION_FAILED | UNAUTHORIZED | TIMEOUT | INVALID_CONFIGURATION |
UNHEALTHY | EXPIRED | DISCONNECTED | REVOKED
```

### 4.3 `AccessMode`
```text
READ_ONLY | READ_WRITE | ADMIN | SIMULATION
```
*(Default: `READ_ONLY`)*

### 4.4 `DataMode`
```text
REAL | SIMULATION | HYBRID
```

---

## 5. Canonical Error Contract

All error responses adhere strictly to the uniform envelope:

```json
{
  "success": false,
  "request_id": "req_01JXYZ",
  "error": {
    "code": "DATABASE_POLICY_BLOCKED",
    "message": "The requested database connection is not permitted."
  }
}
```

### 5.1 Standard Error Codes (`GatewayErrorCode`)
- `AUTHENTICATION_REQUIRED`, `AUTHENTICATION_FAILED`, `AUTHORIZATION_DENIED`
- `INVALID_REQUEST`, `INVALID_DATABASE_TYPE`, `INVALID_DATABASE_CONFIGURATION`
- `DATABASE_POLICY_BLOCKED`, `DATABASE_HOST_BLOCKED`, `DATABASE_PORT_BLOCKED`, `DATABASE_NETWORK_BLOCKED`
- `DATABASE_TLS_REQUIRED`, `DATABASE_TLS_FAILED`
- `DATABASE_CONNECTION_FAILED`, `DATABASE_AUTH_FAILED`, `DATABASE_TIMEOUT`, `DATABASE_UNREACHABLE`, `DATABASE_NOT_FOUND`, `DATABASE_PERMISSION_DENIED`
- `CONNECTION_NOT_FOUND`, `CONNECTION_REVOKED`, `CONNECTION_EXPIRED`, `CONNECTION_NOT_ACCESSIBLE`
- `SCHEMA_DISCOVERY_FAILED`, `SAMPLE_DATA_BLOCKED`, `SAMPLE_DATA_TOO_LARGE`
- `RATE_LIMITED`, `INTERNAL_ERROR`, `NOT_IMPLEMENTED`

### 5.2 HTTP Status Mapping
- `400` → `INVALID_REQUEST`, `INVALID_DATABASE_TYPE`, `DATABASE_TLS_REQUIRED`
- `401` → `AUTHENTICATION_REQUIRED`, `DATABASE_AUTH_FAILED`
- `403` → `AUTHORIZATION_DENIED`, `DATABASE_POLICY_BLOCKED`, `CONNECTION_NOT_ACCESSIBLE`
- `404` → `CONNECTION_NOT_FOUND`, `DATABASE_NOT_FOUND`
- `408` → `DATABASE_TIMEOUT`
- `409` → `CONNECTION_REVOKED`, `CONNECTION_EXPIRED`
- `422` → `INVALID_DATABASE_CONFIGURATION`
- `429` → `RATE_LIMITED`
- `500` → `INTERNAL_ERROR`
- `501` → `NOT_IMPLEMENTED`
- `503` → `DATABASE_UNREACHABLE`, `DATABASE_CONNECTION_FAILED`

---

## 6. Endpoints Specification

### 6.1 Create Connection
- **Method / Path:** `POST /api/v3/database/connections`
- **Role Required:** `manager`
- **Status:** `201 Created`
- **Headers:** `Idempotency-Key` (Optional), `X-Request-ID` (Optional)
- **Request Body:**
```json
{
  "database_type": "POSTGRESQL",
  "host": "db.example.com",
  "port": 5432,
  "database": "operations",
  "username": "sage_readonly",
  "password": "secret_password",
  "ssl": { "mode": "REQUIRED" },
  "access_mode": "READ_ONLY",
  "data_mode": "REAL",
  "plant_id": "plant_001"
}
```
- **Response:**
```json
{
  "success": true,
  "request_id": "req_01JXYZ",
  "connection": {
    "connection_id": "conn_01JABC",
    "tenant_id": "tenant_001",
    "workspace_id": "workspace_001",
    "session_id": "session_001",
    "plant_id": "plant_001",
    "database_type": "POSTGRESQL",
    "database_name": "operations",
    "status": "CONNECTED",
    "access_mode": "READ_ONLY",
    "data_mode": "REAL",
    "capabilities": {
      "read": true,
      "write": false,
      "transactions": false,
      "schema_inspection": true
    },
    "created_at": "2026-09-14T10:00:00Z",
    "last_used_at": "2026-09-14T10:00:00Z"
  }
}
```

### 6.2 Test Reachability
- **Method / Path:** `POST /api/v3/database/connections/test`
- **Role Required:** `operator`
- **Status:** `200 OK`
- **Purpose:** Validate transient reachability without persistent socket pooling or context registration.
- **Response:**
```json
{
  "success": true,
  "request_id": "req_01JXYZ",
  "result": {
    "reachable": true,
    "authenticated": true,
    "database_type": "POSTGRESQL",
    "latency_ms": 24.5
  }
}
```

### 6.3 List Connections
- **Method / Path:** `GET /api/v3/database/connections`
- **Role Required:** `operator`
- **Query Filters:** `workspace_id`, `plant_id`, `status`, `database_type`, `data_mode`, `limit` (default 20, max 100), `offset` (default 0).
- **Response:**
```json
{
  "success": true,
  "request_id": "req_01JXYZ",
  "connections": [
    {
      "connection_id": "conn_01JABC",
      "database_type": "POSTGRESQL",
      "status": "CONNECTED",
      "access_mode": "READ_ONLY",
      "data_mode": "REAL"
    }
  ],
  "total": 1
}
```

### 6.4 Get Connection Metadata
- **Method / Path:** `GET /api/v3/database/connections/{connection_id}`
- **Role Required:** `operator`
- **Response:** Safe `DatabaseConnection` resource.

### 6.5 Health Check
- **Method / Path:** `GET /api/v3/database/connections/{connection_id}/health`
- **Role Required:** `operator`
- **Response:**
```json
{
  "success": true,
  "request_id": "req_01JXYZ",
  "health": {
    "status": "HEALTHY",
    "latency_ms": 1.2,
    "checked_at": "2026-09-14T10:05:00Z"
  }
}
```

### 6.6 Schema Discovery
- **Method / Path:** `GET /api/v3/database/connections/{connection_id}/schema`
- **Role Required:** `operator`
- **Query Params:** `schema`, `table`, `limit` (default 50, max 100).
- **Response:**
```json
{
  "success": true,
  "request_id": "req_01JXYZ",
  "schema": {
    "tables": [
      {
        "name": "inventory",
        "columns": [
          { "name": "sku", "type": "VARCHAR", "nullable": false },
          { "name": "quantity", "type": "INTEGER", "nullable": false }
        ]
      }
    ]
  }
}
```

### 6.7 Sample Table Data
- **Method / Path:** `POST /api/v3/database/connections/{connection_id}/sample`
- **Role Required:** `operator`
- **Request Body:**
```json
{
  "table": "inventory",
  "limit": 10,
  "columns": ["sku", "quantity"]
}
```
- **Response:** Automatically redacts sensitive fields (`password`, `secret`, `token`, `api_key`, `ssn`) to `[REDACTED]`.

### 6.8 Disconnect Connection
- **Method / Path:** `POST /api/v3/database/connections/{connection_id}/disconnect`
- **Role Required:** `manager`
- **Response:**
```json
{
  "success": true,
  "request_id": "req_01JXYZ",
  "connection": {
    "connection_id": "conn_01JABC",
    "status": "DISCONNECTED"
  }
}
```

### 6.9 Revoke Connection (Admin / Security)
- **Method / Path:** `POST /api/v3/database/connections/{connection_id}/revoke`
- **Role Required:** `manager`
- **Response:**
```json
{
  "success": true,
  "request_id": "req_01JXYZ",
  "connection": {
    "connection_id": "conn_01JABC",
    "status": "REVOKED"
  }
}
```
*Note: Any subsequent request referencing this `connection_id` returns `409` (`CONNECTION_REVOKED`).*

### 6.10 Rotate Credentials (Reserved)
- **Method / Path:** `POST /api/v3/database/connections/{connection_id}/rotate-credentials`
- **Role Required:** `manager`
- **Status:** `501 Not Implemented`

---

## 7. Agent & LLM Integration Contract

### 7.1 `DatabaseTool` Abstraction
AI Agents never make raw HTTP calls or manage database credentials. Instead, agents interact through the `DatabaseTool` interface:

```text
Agent / Copilot
      ↓
DatabaseTool (tools/db_tools.py)
      ↓
DatabaseConnectionGateway
      ↓
Network / Policy Engine
      ↓
ConnectionManager
      ↓
Target Database
```

### 7.2 Safe LLM Representation
The LLM receives strictly non-confidential context:
```json
{
  "connection_id": "conn_01JABC",
  "database_type": "POSTGRESQL",
  "data_mode": "REAL",
  "access_mode": "READ_ONLY",
  "capabilities": {
    "read": true,
    "write": false,
    "schema_inspection": true
  }
}
```

---

## 8. Audit Event Contract

All gateway lifecycle operations emit immutable security audit events:
```json
{
  "event_type": "DATABASE_CONNECTION_ESTABLISHED",
  "timestamp": "2026-09-14T10:05:00Z",
  "actor": { "user_id": "mgr_456" },
  "scope": {
    "tenant_id": "tenant_alpha",
    "session_id": "session_alpha"
  },
  "resource": {
    "connection_id": "conn_01JABC",
    "database_type": "POSTGRESQL"
  },
  "result": "SUCCESS"
}
```
Audit logs strictly prohibit logging of plaintext passwords, connection URIs with embedded secrets, or decrypted payloads.
