# API & WebSocket Documentation

## REST Endpoints

### `POST /trigger-anomaly`
Manually injects a randomized factory anomaly into the simulated state.
**Response:**
```json
{
  "status": "success",
  "anomaly": {
    "type": "Supply Chain Disruption",
    "details": "Shipment delayed by 48 hours."
  }
}
```

### `POST /connect-live-db`
Hot-swaps the AI's internal database query tools to point to a new live connection.
**Payload:**
```json
{
  "connection_string": "postgresql://user:pass@host/dbname"
}
```
**Response:**
```json
{
  "status": "success",
  "message": "Live tether established. Detected 5 tables.",
  "tables": ["inventory", "orders", "logistics"]
}
```

### `POST /upload-db`
Uploads a `.csv`, `.db`, or `.sqlite` file. If a `.csv` is provided, the FastAPI backend automatically compiles it into a temporary SQLite database on the fly and hot-swaps the brain.
**Payload:** `multipart/form-data` containing the file.

---

## WebSocket Protocol (`/ws/sage`)

The frontend and backend communicate exclusively via JSON strings over a single persistent WebSocket connection.

### Frontend -> Backend Messages
- **Start Chat:** `{"command": "chat", "text": "Status report"}`
- **Start Scan:** `{"command": "scan"}`
- **Process Image:** `{"command": "diagnostics_upload", "image_data": "base64_string..."}`
- **Authorize Action:** `{"command": "resume_execution", "decision": "approve"}`

### Backend -> Frontend Messages
- **Node Active Telemetry:** `{"type": "node_active", "node": "evaluator"}`
- **Chat Response:** `{"type": "chat_response", "text": "Here is the status..."}`
- **Security Alert:** `{"type": "security_alert", "threat_level": "CRITICAL", "details": "SQL Injection attempt detected."}`
- **Guardrail Intercept:** 
```json
{
  "type": "guardrail_interrupt",
  "payload": {
    "action": "UPDATE inventory SET stock = 0",
    "justification": "Emergency stock depletion."
  }
}
```
