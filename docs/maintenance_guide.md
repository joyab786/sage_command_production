# 🛠️ SageCommand V3 — Operations & Maintenance Troubleshooting Guide

> **System**: SageCommand V3 Enterprise Autonomous & Operational Intelligence OS  
> **Target Audience**: Site Reliability Engineers, Database Administrators, and DevOps Operations Leads  

---

## 🗄️ 1. Multi-Database Storage Maintenance

SageCommand V3 utilizes a partitioned SQLite storage architecture operating in Write-Ahead Logging (WAL) mode to isolate domain services and eliminate database write contention.

### 1.1 Managing SQLite WAL Mode & Checkpointing
Under heavy operational loads, SQLite WAL files (`*-wal`) can grow if checkpoints are delayed by long-running transactions.
* **Inspect Current Journal Mode**:
  ```bash
  sqlite3 /var/data/sage/dynamic_datacore.sqlite "PRAGMA journal_mode;"
  # Expected: wal
  ```
* **Force a WAL Checkpoint (TRUNCATE mode)**:
  Run periodically or before backups to fold `-wal` files back into the primary `.sqlite` container:
  ```bash
  sqlite3 /var/data/sage/dynamic_datacore.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
  sqlite3 /var/data/sage/sage_audit_ledger.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
  ```

### 1.2 Resolving `sqlite3.OperationalError: database is locked`
* **Root Cause**: A process or thread is holding an exclusive write lock without closing the session, or multiple workers are attempting concurrent DDL mutations.
* **Remediation**:
  1. Ensure connection strings use `timeout=30.0` and `check_same_thread=False`:
     ```python
     engine = create_engine(db_uri, connect_args={"timeout": 30, "check_same_thread": False})
     ```
  2. Inspect running processes holding open file handles on the database:
     ```bash
     # Linux:
     lsof | grep .sqlite
     # Windows PowerShell:
     Get-Process | Where-Object { $_.Modules.FileName -like "*sqlite*" }
     ```
  3. If a lock persists due to an orphaned worker, gracefully terminate the offending thread or restart the FastAPI container. WAL journaling guarantees zero corruption upon container restart.

### 1.3 Online Database Backups (Zero-Downtime)
Never execute standard `cp` on active SQLite files while under load, as copying a moving WAL file may result in torn pages. Use SQLite's safe online backup API:
```bash
#!/bin/bash
BACKUP_DIR="/var/backups/sage/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

for db in /var/data/sage/*.sqlite; do
    dbname=$(basename "$db")
    echo "Backing up $dbname..."
    sqlite3 "$db" ".backup '$BACKUP_DIR/$dbname'"
done

echo "Backup complete: $BACKUP_DIR"
```

---

## 🛡️ 2. Audit Ledger & Cryptographic Integrity Verification

The `sage_audit_ledger.sqlite` maintains an append-only, tamper-evident hash chain linking every operational event with a SHA-256 digest:

$$H_i = \text{SHA-256}(H_{i-1} \parallel \text{Payload}_i \parallel \text{Timestamp}_i)$$

### 2.1 Verifying Cryptographic Chain of Custody
To verify that no audit records have been deleted, updated, or manipulated:
```bash
curl -X POST https://api.sagecommand.com/api/v3/audit/verify-integrity \
  -H "Authorization: Bearer security_token" \
  -H "X-Session-ID: admin_audit_session"
```
**Expected Response:**
```json
{
  "status": "VALID",
  "total_records_verified": 142850,
  "tamper_detected": false,
  "head_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "verification_time_ms": 34.2
}
```
If `tamper_detected: true` is returned, the endpoint will identify the exact block index where the hash sequence broke, pinpointing unauthorized tampering.

---

## 📬 3. Internal Event Bus & Dead-Letter Queue (DLQ) Maintenance

The durable event bus ([backend/services/event_bus.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/services/event_bus.py)) manages asynchronous inter-service communication via SQLite queue leases (`sage_event_delivery.sqlite`).

### 3.1 Monitoring Event Delivery Health
Query the internal event bus metrics endpoint:
```bash
curl https://api.sagecommand.com/api/v3/event-bus/metrics \
  -H "Authorization: Bearer manager_token"
```
**Key Metrics to Monitor**:
* `queue_depth`: Number of unhandled events pending dispatch (Healthy: < 100).
* `active_worker_leases`: Number of worker threads currently processing events.
* `dead_letter_count`: Events that exceeded `SAGE_EVENT_BUS_MAX_RETRIES` (Default: 3).

### 3.2 Inspecting and Replaying Dead-Letter Events
When downstream services fail or time out, un-deliverable events are moved to the DLQ:
1. **Retrieve DLQ Items**:
   ```bash
   curl https://api.sagecommand.com/api/v3/event-bus/dead-letter \
     -H "Authorization: Bearer admin_token"
   ```
2. **Replay DLQ Items**:
   After resolving the underlying database or network fault, re-queue dead-letter events for execution:
   ```bash
   curl -X POST https://api.sagecommand.com/api/v3/event-bus/dead-letter/replay \
     -H "Authorization: Bearer admin_token" \
     -d '{"event_ids": ["evt_9942a1", "evt_9942a2"]}'
   ```

---

## 🤖 4. Multi-LLM Inference Resilience & Failover Runbook

SageCommand V3 integrates a resilient multi-provider LLM pipeline in [backend/core/llm.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/core/llm.py):

```
                   ┌───────────────────────────────────┐
                   │       INCOMING AGENT QUERY        │
                   └─────────────────┬─────────────────┘
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │    PRIMARY: Groq (Llama 3.3 70B)  │
                   └─────────────────┬─────────────────┘
                                     │
                         Rate Limit / Error (5xx)
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │   SECONDARY: Google Gemini 2.0    │
                   └─────────────────┬─────────────────┘
                                     │
                         Missing / Exhausted Keys
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │   DEMO MODE: Deterministic Mock   │
                   └───────────────────────────────────┘
```

### 4.1 Diagnosing LLM Failover in Logs
When primary inference encounters an exception, the system logs:
```
[LLM Failover] Primary inference provider (Groq) failed with: RateLimitError(429).
[LLM Failover] Seamlessly falling back to Google Gemini 2.0 Flash...
```
* **If both providers fail**: The system activates deterministic fallback heuristics, preventing server crashes and returning structured degradation notices to the UI.
* **Remediation**:
  1. Inspect Groq usage quotas at `https://console.groq.com`.
  2. Inspect Google Cloud Vertex / AI Studio quotas.
  3. Rotate `GROQ_API_KEY` or `GEMINI_API_KEY` in `/backend/.env` and reload without stopping the running container (system reads env values on reload).

---

## 🔒 5. Session Fail-Closed Authentication Troubleshooting

SageCommand V3 enforces a **strict fail-closed session security model**:
* Client headers (`X-Clearance-Level`, `X-Assigned-Plants`) are permanently ignored for privilege escalation.
* For JWT tokens, `session_id` must originate from the cryptographically verified token claim. A client-provided `X-Session-ID` header cannot overwrite or manufacture a session for a JWT identity.
* In development mode (`dev_auth`), generic tokens without a session ID will receive `401 Unauthorized` or `403 Forbidden` on state-mutating endpoints.

### Common Auth Errors & Fixes
| Error Code | Detail Message | Root Cause & Resolution |
|:---|:---|:---|
| `401` | `"Authentication token required."` | Client omitted the `Authorization: Bearer <TOKEN>` header. |
| `401` | `"JWT token has expired."` | Token `exp` timestamp is in the past. Client must refresh token from IdP. |
| `401` | `"Unsupported or prohibited JWT algorithm: 'none'."` | Client attempted algorithm downgrade attack. Only allowlisted algorithms (`HS256`, `RS256`) are accepted. |
| `403` | `"Role clearance 'MANAGER' is required..."` | User identity lacks the required operational role. Switch to Manager profile in console. |
| `403` | `"TENANT_SCOPE_MISMATCH"` | Request is attempting to mutate an asset belonging to a different tenant ID. |
| `1008` | `WebSocket Policy Violation` | WebSocket handshake omitted the auth token or session ID parameter. |

---

## 🧹 6. Routine Maintenance Schedule

| Frequency | Task | Procedure |
|:---|:---|:---|
| **Hourly** | Event Bus Sweeper Check | Verify sweeper process is reclaiming abandoned event delivery leases. |
| **Daily** | WAL Checkpoint & Compaction | Execute `PRAGMA wal_checkpoint(TRUNCATE)` across all 30 SQLite containers. |
| **Weekly** | Audit Ledger Chain Verification | Run `/api/v3/audit/verify-integrity` to ensure ledger cryptographic health. |
| **Weekly** | Purge Expired Transaction Plans | Delete unexecuted transaction records where `created_at + ttl_seconds < now`. |
| **Monthly** | Database Optimization (`VACUUM`) | Rebuild database files to reclaim fragmented pages and optimize index b-trees. |
| **Monthly** | Full Disaster Recovery Drill | Restore SQLite backups to an isolated sandbox and execute verification suite. |
