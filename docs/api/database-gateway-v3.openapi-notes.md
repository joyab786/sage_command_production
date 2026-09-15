# SageCommand V3 — Database Connection Gateway OpenAPI Notes

**Date:** 2026-09-14  
**Version:** SageCommand V3.0  
**OpenAPI Specification:** 3.1.0  
**Target Module:** `backend/api/database_routes.py` mounted at `/api/v3/database`  

---

## 1. OpenAPI Model Architecture

All models are generated using Pydantic V2 schemas defined in `backend/data/schemas/database_contract.py`.

### 1.1 Registered Schemas
- `DatabaseConnection`: Primary core resource model. All fields are strongly typed with explicit validation.
- `DatabaseConnectionListItem`: Concise projection for paginated collection listings.
- `CreateConnectionRequest` / `CreateConnectionResponse` (HTTP 201 Created)
- `TestConnectionRequest` / `TestConnectionResponse` (HTTP 200 OK)
- `GetConnectionResponse` (HTTP 200 OK)
- `ListConnectionsResponse` (HTTP 200 OK)
- `HealthCheckResponse` (HTTP 200 OK)
- `SchemaDiscoveryResponse` (HTTP 200 OK, with `SchemaMetadata`, `TableMetadata`, `ColumnMetadata`)
- `SampleDataRequest` / `SampleDataResponse` (HTTP 200 OK, max 10 rows, PII masked)
- `DisconnectResponse` (HTTP 200 OK)
- `RevokeResponse` (HTTP 200 OK)
- `ErrorResponse` (HTTP 400, 401, 403, 404, 408, 409, 422, 429, 500, 501, 503)

---

## 2. Parameter Annotations & Examples

### 2.1 Request Headers
- `X-Request-ID`: Extracted from incoming HTTP request. Sanitized to alphanumeric with `-` and `_`, maximum 64 characters. Returned in all success and error responses.
- `Idempotency-Key`: Supported on `POST /api/v3/database/connections`. Caches connection responses per tenant for 300 seconds to prevent accidental duplicate connection pooling.

### 2.2 Security Schemas
All endpoints require HTTP Bearer authentication:
- `security_scheme = HTTPBearer(auto_error=False)`
- Role clearance: `manager` for connection creation, disconnection, revocation; `operator` for testing, metadata inspection, schema discovery, health checks, and sampling.

---

## 3. Legacy Compatibility

- The legacy `/connect-live-db` endpoint remains accessible on the root router and delegates directly to `db_gateway.create_connection()` to prevent frontend disruption.
- The V3 canonical endpoints under `/api/v3/database/*` provide the official contract for all future V3 API consumers, agent integrations, and microservices.
