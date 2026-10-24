# 🔌 SageCommand V3 — Comprehensive API & WebSocket Reference

> **API Version**: 3.0.0 (Enterprise Production)  
> **Base URL**: `http://localhost:8000` (Dev) / `https://api.sagecommand.com` (Prod)  
> **WebSocket URL**: `ws://localhost:8000/ws/sage` (Dev) / `wss://api.sagecommand.com/ws/sage` (Prod)  
> **Authentication**: HTTP Bearer JWT or Server-Authoritative Dev Token  

---

## 🔐 Authentication, Headers & Security Protocols

### Required Request Headers
Every REST request must provide valid authentication and tenancy headers:

```http
Authorization: Bearer <JWT_OR_DEV_TOKEN>
X-Session-ID: session_abc123
X-Tenant-ID: tenant_default
X-Workspace-ID: workspace_default
X-Plant-ID: plant_01
Content-Type: application/json
```

### Authentication Invariants & Roles
* **JWT Tokens**: Cryptographically signed using algorithms defined in `SAGE_JWT_ALGORITHMS` (HS256/RS256). In production, token claims (`sub`, `tenant_id`, `roles`, `clearance_level`, `assigned_plants`) are strictly server-authoritative.
* **Session Isolation**: Sessions fail closed. A request with a missing session ID will be denied authorization on state-mutating endpoints.
* **Standard Development Role Tokens**:
  * `operator_token`: Clearance level 1; access to operational reads and low-risk scans.
  * `manager_token`: Clearance level 2; permission for `action.execute`, `transaction.execute`, and HITL approvals.
  * `admin_token`: Clearance level 3; full system administration and policy reconfiguration.
  * `security_token`: Clearance level 3; audit ledger queries and DEFCON security administration.

### Standard Response Envelope & Error Codes
* `200 OK` / `201 Created`: Successful query or entity creation.
* `400 Bad Request`: Payload validation error or malformed request parameters.
* `401 Unauthorized`: Missing, expired, or cryptographically invalid token.
* `403 Forbidden`: Role clearance, ABAC policy, or plant assignment failure.
* `404 Not Found`: Entity ID does not exist in the specified tenant/workspace scope.
* `409 Conflict`: Concurrency lock collision or duplicate idempotency key detected.
* `422 Unprocessable Entity`: Schema validation or business constraint violation.
* `500 Internal Server Error`: Sanitized production error (internal stack traces and DB credentials are redacted by middleware).

---

## 📡 Real-Time WebSocket Protocol (`/ws/sage`)

The WebSocket interface provides a persistent, full-duplex communication channel for real-time telemetry, agent state streaming, and Human-in-the-Loop approvals.

### Connection Handshake
* **URL**: `ws://localhost:8000/ws/sage?token=<TOKEN>&session_id=<SESSION_ID>`
* Unauthenticated connections are terminated immediately with status code `1008 (Policy Violation)`.

### Client-to-Server Commands (`Frontend -> Backend`)

#### 1. Interactive Chat (`chat`)
Sends an operator message to the `Strategic Copilot Agent`:
```json
{
  "command": "chat",
  "text": "What is the current inventory status of Turbine Bearings in Plant 01?"
}
```

#### 2. Trigger Autonomous Core Scan (`scan`)
Initiates the autonomous discovery pipeline:
```json
{
  "command": "scan"
}
```

#### 3. Upload Hardware Diagnostics Imagery (`diagnostics_upload`)
Uploads a Base64-encoded image for Gemini Multi-Modal damage assessment:
```json
{
  "command": "diagnostics_upload",
  "image_data": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
}
```

#### 4. Authorize Guardrail Action (`resume_execution`)
Authorizes or aborts an intercepted operational action:
```json
{
  "command": "resume_execution",
  "decision": "approve",
  "action_id": "act_8849bf20",
  "comments": "Approved by Shift Lead for Line 2 replenishment"
}
```

#### 5. Retrieve State History (`get_history`)
Retrieves LangGraph checkpoint history for Time Travel auditing:
```json
{
  "command": "get_history"
}
```

#### 6. Rollback Transaction (`rollback`)
Triggers an immediate compensating transaction rollback:
```json
{
  "command": "rollback",
  "transaction_id": "tx_9934fa12",
  "reason": "Unexpected sensor temperature spike detected post-execution"
}
```

### Server-to-Client Events (`Backend -> Frontend`)

* **Active Node Telemetry**: Emitted as LangGraph traverses vertices, lighting up nodes on the React Flow graph:
  ```json
  { "type": "node_active", "node": "evaluator" }
  ```
* **Chat Response Stream**: Conversational response from the Copilot agent:
  ```json
  { "type": "chat_response", "text": "Telemetry confirms 4 critical inventory shortages..." }
  ```
* **Guardrail Intercept Gate**: Pauses execution and displays the proposal modal:
  ```json
  {
    "type": "guardrail_interrupt",
    "payload": {
      "action_id": "act_7731da",
      "action": "UPDATE inventory SET stock_level = 250 WHERE sku = 'BRG-4002';",
      "justification": "Mitigate risk of line halt; order replenishment from secondary supplier.",
      "estimated_cost": "$4,250.00",
      "risk_level": "HIGH"
    }
  }
  ```
* **Security Intrusion Alert (DEFCON 1)**: Emitted when malicious input is detected:
  ```json
  {
    "type": "security_alert",
    "threat_level": "CRITICAL",
    "details": "Raw SQL injection attempt detected in chat payload."
  }
  ```
* **Blast Radius Telemetry**: Cascading failure graph metrics:
  ```json
  {
    "type": "blast_radius_data",
    "affected_nodes": 6,
    "downstream_plants": ["plant_01", "plant_03"],
    "financial_exposure": "$125,000.00"
  }
  ```

---

## 🌐 Complete REST API Endpoint Directory

### 1. Legacy & Convenience Routes ([backend/api/routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/routes.py))
* `GET /health` — System uptime and subsystem readiness.
* `POST /trigger-anomaly` — Injects a randomized operational anomaly into the simulation state.
* `POST /connect-live-db` — Hot-swaps the active SQLAlchemy engine to a live PostgreSQL, MySQL, or SQLite URI.
* `POST /upload-db` — Ingests a `.csv` or `.sqlite` file, dynamically compiling CSV rows into relational SQL tables.

### 2. Database Gateway & Connection Management ([backend/api/database_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/database_routes.py))
* `POST /api/v3/database/connect` — Establishes a verified, session-scoped database connection.
* `GET /api/v3/database/status` — Returns active connection metrics, pool stats, and latency.
* `GET /api/v3/database/schema` — Returns schema introspection, tables, column types, and foreign keys.
* `POST /api/v3/database/query` — Executes a parameterized, read-only SQL query subject to SQL guardrails.
* `DELETE /api/v3/database/disconnect` — Closes the active session database connection and returns resources to the pool.

### 3. Action API & Action Store ([backend/api/action_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/action_routes.py))
* `POST /api/v3/actions/propose` — Proposes a new operational action into the Action Store.
* `GET /api/v3/actions/{action_id}` — Retrieves action details, risk tier, and validation status.
* `POST /api/v3/actions/{action_id}/validate` — Runs action through the multi-stage Action Validator pipeline.
* `POST /api/v3/actions/{action_id}/execute` — Submits action to the 10-Gate Execution Gateway.
* `GET /api/v3/actions` — Lists actions filtered by status (`PENDING_APPROVAL`, `EXECUTED`, `ABORTED`).

### 4. Deterministic Policy Engine ([backend/api/policy_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/policy_routes.py))
* `POST /api/v3/policies/evaluate` — Evaluates proposed parameters against active business policies.
* `GET /api/v3/policies` — Lists all registered corporate operational, safety, and environmental policies.
* `POST /api/v3/policies` — Registers a new policy rule (Requires Administrator clearance).
* `GET /api/v3/policies/violations` — Lists historical policy violations with timestamps and actor IDs.

### 5. RBAC & ABAC Authorization Engine ([backend/api/authorization_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/authorization_routes.py))
* `POST /api/v3/authz/evaluate` — Deterministically evaluates whether an identity is authorized for an action.
* `GET /api/v3/authz/roles` — Returns available role hierarchies and assigned permission sets.
* `GET /api/v3/authz/permissions` — Returns current caller permissions within the active plant scope.

### 6. Tamper-Evident Audit Ledger ([backend/api/audit_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/audit_routes.py))
* `GET /api/v3/audit/events` — Queries audit ledger events with pagination, actor filters, and date ranges.
* `GET /api/v3/audit/events/{event_id}` — Retrieves cryptographic event details and SHA-256 state hash.
* `POST /api/v3/audit/verify-integrity` — Validates the cryptographic chain of custody across ledger blocks.

### 7. Transaction Plans & Rollback Engine ([backend/api/transaction_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/transaction_routes.py))
* `POST /api/v3/transactions/plan` — Generates a two-phase transaction execution and rollback plan.
* `GET /api/v3/transactions/{tx_id}` — Retrieves transaction status, affected row snapshots, and TTL.
* `POST /api/v3/transactions/{tx_id}/execute` — Commits transaction through the Execution Gateway.
* `POST /api/v3/transactions/{tx_id}/rollback` — Executes compensating rollback operations restoring pre-image state.

### 8. Industrial Domain Ontology ([backend/api/ontology_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/ontology_routes.py))
* `GET /api/v3/ontology/entities` — Lists ontology asset entities, hierarchy classes, and attributes.
* `GET /api/v3/ontology/entities/{entity_id}` — Retrieves specific asset taxonomy, failure modes, and relations.
* `POST /api/v3/ontology/entities` — Registers a new industrial asset class or equipment type.

### 9. Operational Knowledge Graph ([backend/api/knowledge_graph_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/knowledge_graph_routes.py))
* `GET /api/v3/knowledge-graph/nodes` — Lists nodes representing physical machines, plants, and suppliers.
* `GET /api/v3/knowledge-graph/edges` — Lists operational dependency edges with weight and latency attributes.
* `POST /api/v3/knowledge-graph/traverse` — Executes graph traversal (BFS/DFS) to trace dependencies up to depth N.
* `GET /api/v3/knowledge-graph/subgraph/{entity_id}` — Extracts localized subgraph centered on a specific asset.

### 10. Digital Twin Telemetry Mirror ([backend/api/digital_twin_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/digital_twin_routes.py))
* `GET /api/v3/digital-twin/state/{asset_id}` — Returns the real-time replicated state of an industrial asset.
* `GET /api/v3/digital-twin/snapshot/{asset_id}` — Retrieves a timestamped snapshot of all telemetry channels.
* `GET /api/v3/digital-twin/history/{asset_id}` — Returns historical telemetry series for trend analysis.

### 11. Data Quality Intelligence ([backend/api/data_quality_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/data_quality_routes.py))
* `POST /api/v3/data-quality/profile` — Generates a data quality profile across connected telemetry tables.
* `GET /api/v3/data-quality/assessment/{asset_id}` — Returns sensor data completeness, latency, and drift metrics.

### 12. Continuous Anomaly Detection ([backend/api/anomaly_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/anomaly_routes.py))
* `GET /api/v3/anomalies` — Lists detected anomalies categorized by severity (`LOW`, `MEDIUM`, `CRITICAL`).
* `GET /api/v3/anomalies/{anomaly_id}` — Retrieves anomaly fingerprint, z-score deviation, and affected telemetry.
* `POST /api/v3/anomalies/scan` — Manually triggers a high-frequency anomaly detection scan.

### 13. Event Model & Internal Event Bus ([backend/api/event_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/event_routes.py) & [event_bus_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/event_bus_routes.py))
* `POST /api/v3/events` — Publishes an event to the durable internal event bus.
* `GET /api/v3/event-bus/metrics` — Returns queue depth, active worker leases, and delivery throughput.
* `GET /api/v3/event-bus/dead-letter` — Lists failed events in the dead-letter queue requiring human triage.

### 14. Incident Management ([backend/api/incident_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/incident_routes.py))
* `GET /api/v3/incidents` — Lists active operational incidents with severity and triage stage.
* `GET /api/v3/incidents/{incident_id}` — Returns incident details, assigned team, and timeline logs.
* `PATCH /api/v3/incidents/{incident_id}` — Updates incident status (`TRIAGED`, `RESOLVING`, `CLOSED`).

### 15. Root-Cause Analysis (RCA) ([backend/api/rca_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/rca_routes.py))
* `POST /api/v3/rca/analyze` — Initiates an automated 5-Whys graph analysis for an incident.
* `GET /api/v3/rca/{analysis_id}` — Retrieves ranked root-cause candidates and confidence scores.

### 16. Blast-Radius Intelligence ([backend/api/blast_radius_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/blast_radius_routes.py))
* `POST /v3/blast-radius/analyze` — Calculates downstream cascading impact tree for a source asset.
* `GET /v3/blast-radius/{analysis_id}` — Retrieves cached blast radius results and affected node counts.

### 17. Predictive Maintenance ([backend/api/predictive_maintenance_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/predictive_maintenance_routes.py))
* `POST /v3/predictive-maintenance/analyze` — Forecasts equipment health, degradation, and RUL horizon.
* `GET /v3/predictive-maintenance/assessment/{id}` — Retrieves cached maintenance risk assessment.

### 18. Demand Forecasting ([backend/api/demand_forecasting_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/demand_forecasting_routes.py))
* `POST /api/v3/demand-forecasting/forecast` — Generates a probabilistic demand forecast for inventory SKUs.
* `GET /api/v3/demand-forecasting/{forecast_id}` — Retrieves forecast curves and replenishment thresholds.

### 19. Supplier Risk Intelligence ([backend/api/supplier_risk_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/supplier_risk_routes.py))
* `POST /api/v3/supplier-risk/assess` — Evaluates supplier delivery history, lead-time variance, and geopolitical risk.
* `GET /api/v3/supplier-risk/supplier/{supplier_id}` — Returns supplier reliability score card.

### 20. SLA & Customer Contract Risk ([backend/api/sla_customer_risk_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/sla_customer_risk_routes.py))
* `POST /api/v3/sla-customer-risk/analyze` — Predicts customer contract breach probabilities and penalties.
* `GET /api/v3/sla-customer-risk/customer/{customer_id}/summary` — Summarizes active order breach risks.

### 21. Financial Impact Intelligence ([backend/api/financial_impact_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/financial_impact_routes.py))
* `POST /api/v3/financial-impact/analyze` — Translates operational bottlenecks into deterministic financial exposures.
* `GET /api/v3/financial-impact/{assessment_id}` — Retrieves granular breakdown of downtime and labor costs.
* `GET /api/v3/financial-impact/summary` — Lists top financial exposures across the enterprise.

### 22. Sustainability Intelligence ([backend/api/sustainability_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/sustainability_routes.py))
* `POST /api/v3/sustainability/analyze` — Computes carbon footprint (Scope 1/2) and energy usage for a plant.
* `POST /api/v3/sustainability/scenario` — Models alternative green operating parameters.
* `GET /api/v3/sustainability/summary` — Returns enterprise-wide sustainability KPIs.

### 23. Multimodal Sensor Fusion ([backend/api/sensor_fusion_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/sensor_fusion_routes.py))
* `POST /api/v3/sensor-fusion/analyze` — Correlates cross-modal telemetry (vibration, acoustics, power, temperature).
* `GET /api/v3/sensor-fusion/{assessment_id}` — Retrieves multi-sensor correlation matrices.

### 24. What-If Simulation ([backend/api/what_if_simulation_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/what_if_simulation_routes.py))
* `POST /api/v3/what-if/simulate` — Runs discrete-event simulation of operational perturbations.
* `GET /api/v3/what-if/scenario/{scenario_id}` — Compares simulated baseline vs. perturbed outcomes.

### 25. Optimization Intelligence ([backend/api/optimization_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/optimization_routes.py))
* `POST /api/v3/optimization/solve` — Solves multi-objective optimization problem under hard constraints.
* `GET /api/v3/optimization/solution/{solution_id}` — Returns Pareto-optimal operational parameters.

### 26. Multi-Criteria Decision Engine ([backend/api/decision_engine_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/decision_engine_routes.py))
* `POST /api/v3/decisions/evaluate` — Evaluates multiple candidate actions using weighted scoring criteria.
* `GET /api/v3/decisions/{evaluation_id}` — Returns full option ranking and trade-off justification matrix.

### 27. Evidence & Explainability ([backend/api/evidence_explainability_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/evidence_explainability_routes.py))
* `GET /api/v3/explainability/explanation/{explanation_id}` — Retrieves reasoning graph, source citations, and evidence links.

### 28. Confidence & Uncertainty Intelligence ([backend/api/confidence_uncertainty_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/confidence_uncertainty_routes.py))
* `POST /api/v3/confidence/assess` — Computes confidence scores and epistemic/aleatoric uncertainty bounds.
* `GET /api/v3/confidence/{assessment_id}` — Retrieves confidence interval distributions.

### 29. SOP / RAG Document Ingestion ([backend/api/sop_rag_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/sop_rag_routes.py))
* `POST /api/v3/sop-rag/documents` — Ingests and chunks standard operating procedure documents.
* `POST /api/v3/sop-rag/search` — Retrieves relevant SOP clauses using hybrid semantic/keyword search.

### 30. Organizational Memory ([backend/api/organizational_memory_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/organizational_memory_routes.py))
* `POST /api/v3/memory/search` — Searches past operational incidents and historical lessons learned.
* `GET /api/v3/memory/entries/{entry_id}` — Retrieves full historical memory card and recorded outcome.

### 31. Autonomous Mission Architecture ([backend/api/mission_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/mission_routes.py))
* `POST /api/v3/missions/create` — Creates an autonomous multi-step mission plan with step dependencies.
* `GET /api/v3/missions/{mission_id}` — Returns mission execution progress and completed milestones.
* `POST /api/v3/missions/{mission_id}/cancel` — Aborts an ongoing autonomous mission.

### 32. Continuous Verification Engine ([backend/api/verification_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/verification_routes.py))
* `POST /api/v3/verification/run` — Triggers post-execution telemetry verification against target assertions.
* `GET /api/v3/verification/runs/{run_id}` — Returns verification status and physical reconciliation findings.
* `POST /api/v3/verification/feedback` — Submits human operator feedback on verification accuracy.

### 33. Autonomy Levels & Guarded Delegation ([backend/api/autonomy_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/autonomy_routes.py))
* `GET /api/v3/autonomy/grants` — Lists active autonomy grants across action types and risk tiers.
* `POST /api/v3/autonomy/evaluate` — Checks if an action is eligible for autonomous execution under active grants.
* `POST /api/v3/autonomy/revoke` — Instantly revokes autonomy grants (Emergency Kill-Switch).

### 34. Closed-Loop Outcome Evaluation ([backend/api/outcome_learning_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/outcome_learning_routes.py))
* `POST /api/v3/outcome-learning/evaluate` — Evaluates outcome divergence between predicted vs. actual telemetry.
* `GET /api/v3/outcome-learning/evaluations` — Lists historical outcome evaluations and efficacy scores.
* `GET /api/v3/outcome-learning/insights` — Returns model calibration adjustments and drift trends.
