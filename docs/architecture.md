# 🧠 SageCommand V3 — System Architecture & Technical Topology

> **System**: SageCommand V3 Enterprise Autonomous & Operational Intelligence OS  
> **Status**: Production Release (V3.0)  
> **Target Audience**: System Architects, Lead Engineers, DevSecOps, and Operations Leadership  

---

## 📌 1. Executive Summary & V3 Architectural Paradigm

**SageCommand OS V3** is an enterprise-grade AI Operating System engineered for industrial automation, high-throughput supply chain networks, and smart factory floor operations. 

While legacy AI agents operate as unconstrained chat interfaces with direct tool access, SageCommand V3 enforces a **strict decoupling of probabilistic AI reasoning from deterministic execution and governance**. The system ensures that while generative AI models (Groq Llama 3.3 70B, Google Gemini 2.0 Flash) synthesize operational insights, predict risks, and formulate complex recovery strategies, **no database write, machine command, or financial transaction can ever occur without traversing deterministic security guardrails, policy verification engines, and cryptographic audit ledgers.**

### Key Architectural Invariants
1. **Deterministic Final Write Boundary**: Every state modification passes through a 10-gate `Execution Gateway` validating cryptographic hashes, two-person rules, and idempotency.
2. **Fail-Closed Zero-Trust Security**: Authentication, session scopes, and tenant boundaries fail closed; client headers can never escalate privileges.
3. **Multi-Database Domain Isolation**: Domain services operate on dedicated, write-ahead-logged (WAL) SQLite databases to eliminate lock contention.
4. **Guarded Autonomy (L0–L4)**: System actions operate under parameterized autonomy levels with real-time kill-switches and manual intervention overrides.
5. **Continuous Closed-Loop Learning**: Execution outcomes are systematically monitored by a Continuous Verification Engine and evaluated by an Outcome Learning service to recalibrate future decision confidence.

---

## 🗺️ 2. High-Level System Architecture & Topology

```
                                 ┌──────────────────────────────────────────────┐
                                 │         HUMAN OPERATOR / COO CONSOLE         │
                                 │   Next.js 16 • React Flow • Obsidian Bento   │
                                 └──────────────────────┬───────────────────────┘
                                                        │
                              WSS /ws/sage (JSON)       │  HTTPS REST (/api/v3/*)
                              Bi-directional Telemetry  │  Bearer JWT / Session ID
                                                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                             FASTAPI CORTEX GATEWAY (server.py)                                         │
│   • SecurityHeadersMiddleware (CSP, HSTS) • RequestSizeLimiter (10MB) • Production Exception Handler (Sanitized 500s)   │
│   • Dynamic CORS Isolation • Identity Context & JWT Decryption Provider (core/auth.py)                                │
└───────────────────┬────────────────────────────────────────────────────────────────────────────────┬───────────────────┘
                    │                                                                                │
                    ▼                                                                                ▼
┌──────────────────────────────────────────────┐                         ┌──────────────────────────────────────────────┐
│        LANGGRAPH MULTI-AGENT PIPELINE        │                         │           INTERNAL DURABLE EVENT BUS         │
│  Directed Cyclic Graph with SqliteSaver Checkpoint                     │  In-Memory Queue + SQLite Lease Repository   │
│                                              │                         │  At-Least-Once Delivery • Dead Letter Queue  │
│  ┌────────────────────────────────────────┐  │                         └──────────────────────┬───────────────────────┘
│  │ Security Agent (DEFCON Inspection)     │  │                                                │
│  ├────────────────────────────────────────┤  │                                                │ Event Triggers
│  │ Copilot Agent (Tool Augmented Chat)    │  │                                                ▼
│  ├────────────────────────────────────────┤  │                         ┌──────────────────────────────────────────────┐
│  │ Observe & Detect (Telemetry Anomalies) │  │                         │       CLOSED-LOOP LEARNING COORDINATOR       │
│  ├────────────────────────────────────────┤  │                         │  Outcome Evaluation Service (Prompt 39)      │
│  │ Risk Analysis (Blast Radius & Exposure)│  │                         │  Continuous Verification Engine (Prompt 36)  │
│  ├────────────────────────────────────────┤  │                         └──────────────────────────────────────────────┘
│  │ Strategy Worker (Multi-Option Synthesis│  │
│  ├────────────────────────────────────────┤  │
│  │ Web Researcher (Tavily Market Context) │  │
│  ├────────────────────────────────────────┤  │
│  │ Evaluator Node (Best Option Scoring)   │  │
│  ├────────────────────────────────────────┤  │
│  │ Human-in-the-Loop Interrupt Gate       │  │
│  └───────────────────┬────────────────────┘  │
│                      │                       │
│                      ▼ (Authorized Actions)  │
│  ┌────────────────────────────────────────┐  │
│  │ Execution Node                         │  │
│  └───────────────────┬────────────────────┘  │
└──────────────────────┼───────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       10-GATE DETERMINISTIC EXECUTION GATEWAY                                          │
│  Gate 1: Auth & Identity  │ Gate 2: RBAC/ABAC Revalidation │ Gate 3: Scope Match │ Gate 4: State Machine (PENDING)    │
│  Gate 5: SHA-256 Staleness│ Gate 6: HITL Two-Person Rule   │ Gate 7: Policy Check│ Gate 8: Idempotency Key De-dup      │
│  Gate 9: Concurrency Lock │ Gate 10: Physical Transaction Execution (Two-Phase Commit & Compensating Rollback Plan)    │
└──────────────────────┬─────────────────────────────────────────────────────────────────────┬───────────────────────────┘
                       │                                                                     │
                       ▼                                                                     ▼
┌──────────────────────────────────────────────┐                         ┌──────────────────────────────────────────────┐
│          ENTERPRISE DOMAIN SERVICES          │                         │             STORAGE INFRASTRUCTURE           │
│  • Industrial Ontology (Taxonomy & Hierarchy)│                         │  • sage_memory.sqlite (LangGraph Checkpoints)│
│  • Operational Knowledge Graph (Topology)    │                         │  • dynamic_datacore.sqlite (Live Operations) │
│  • Digital Twin (Physical State Mirror)      │                         │  • sage_audit_ledger.sqlite (Hash Chained)   │
│  • Predictive Maintenance & RUL Forecasting  │                         │  • sage_transactions.sqlite (Rollback Plans) │
│  • Multi-Modal Sensor Fusion (Vibration, Temp│                         │  • sage_incidents.sqlite & sage_rca.sqlite   │
│  • Financial Impact & Sustainability Scenarios                         │  • sage_autonomy.sqlite & sage_missions.db   │
│  • Decision Engine & SOP RAG Ingestion       │                         │  • External PostgreSQL / MySQL (DB Gateway)  │
└──────────────────────────────────────────────┘                         └──────────────────────────────────────────────┘
```

---

## 🔄 3. The 12-Stage Continuous Operational Loop

SageCommand V3 operates around a continuous, self-healing closed loop across 12 distinct functional stages:

```mermaid
graph LR
    S1[1. OBSERVE] --> S2[2. UNDERSTAND]
    S2 --> S3[3. DETECT]
    S3 --> S4[4. PREDICT]
    S4 --> S5[5. ANALYZE]
    S5 --> S6[6. SIMULATE]
    S6 --> S7[7. OPTIMIZE]
    S7 --> S8[8. GOVERN]
    S8 --> S9[9. APPROVE]
    S9 --> S10[10. EXECUTE]
    S10 --> S11[11. VERIFY]
    S11 --> S12[12. LEARN]
    S12 -->|Continuous Feedback| S1

    style S1 fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff
    style S8 fill:#3b0764,stroke:#a855f7,stroke-width:2px,color:#fff
    style S9 fill:#450a0a,stroke:#ef4444,stroke-width:2px,color:#fff
    style S10 fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#fff
    style S12 fill:#1e1b4b,stroke:#6366f1,stroke-width:2px,color:#fff
```

### Stage Breakdown
1. **OBSERVE (`sensor_fusion`, `db_gateway`, `digital_twin`)**: Continuously samples multi-modal telemetry (time-series metrics, vibration spectra, temperatures, raw SQL tables).
2. **UNDERSTAND (`ontology_service`, `knowledge_graph`)**: Maps raw asset tags to canonical industrial taxonomies and contextualizes relationships within the operational knowledge graph.
3. **DETECT (`anomaly_detection`, `data_quality`)**: Detects anomalous behavior, signal drift, and missing sensor samples using statistical variance and rule-based detectors.
4. **PREDICT (`predictive_maintenance`, `demand_forecasting`)**: Forecasts asset remaining useful life (RUL), machine failure horizons, and supply/order fluctuations.
5. **ANALYZE (`rca_service`, `blast_radius`, `sla_customer_risk`)**: Traces root causes via graph traversal, maps cascading disruption across downstream plants, and evaluates contractual SLA risk.
6. **SIMULATE (`what_if_simulation`, `digital_twin_service`)**: Executes non-destructive discrete-event simulations to test "what-if" operational adjustments before physical deployment.
7. **OPTIMIZE (`optimization_service`, `strategy_worker`)**: Solves multi-objective optimization problems (cost vs. uptime vs. carbon emissions) using constraint satisfaction solvers.
8. **GOVERN (`policy_engine`, `rbac`, `guardrails`)**: Validates potential actions against enterprise business rules, environmental caps, and user permission boundaries.
9. **APPROVE (`autonomy_service`, HITL Intercept)**: If action exceeds autonomy thresholds (or requires L0/L1 human authorization), execution pauses for cryptographic two-person authorization.
10. **EXECUTE (`execution_gateway`, `transaction_service`)**: Executes ACID transactions against target databases through session-isolated database gateways, capturing pre-image rollback snapshots.
11. **VERIFY (`continuous_verification_engine`)**: Evaluates post-execution telemetry against expected outcome assertions to confirm physical convergence.
12. **LEARN (`outcome_evaluation`, `organizational_memory`)**: Measures outcome drift, scores decision efficacy, recalibrates model confidence, and stores episodic lessons in organizational memory.

---

## 🤖 4. Multi-Agent Orchestration Network (LangGraph)

The cognitive layer of SageCommand V3 is orchestrated by a stateful directed cyclic graph built on **LangGraph**:

```mermaid
graph TD
    User([Human Command / Prompt]) --> SecurityAgent[Security Agent: DEFCON 1]
    
    SecurityAgent -->|Threat Detected| SecurityLockdown[CRITICAL_THREAT Event / Terminate]
    SecurityAgent -->|Clean Payload| Supervisor[Supervisor Router]

    Supervisor -->|Query / Chat| Copilot[Strategic Copilot Agent]
    Supervisor -->|Anomaly Trigger / Scan| ObserveDetect[Observe & Detect Agent]

    ObserveDetect --> RiskAnalysis[Risk Analysis Agent]
    RiskAnalysis --> StrategyWorker[Strategy Worker Node]
    StrategyWorker --> WebResearcher[Web Researcher Node: Tavily]
    WebResearcher --> Evaluator[Evaluator Agent Node]

    Evaluator --> InterruptGate{Human-in-the-Loop Gate<br/>(interrupt_before)}
    
    InterruptGate -->|Authorized by Manager| ExecutionNode[Execution Node]
    InterruptGate -->|Aborted by Operator| AbortNode[Abort & Log State]

    ExecutionNode --> ExecutionGateway[10-Gate Execution Gateway]
    ExecutionGateway --> TargetDB[(Target Database)]

    Copilot -->|Read Schema / Query| TargetDB
```

### Agent Roles & Behavioral Contracts
* **Security Agent (`security_agent`)**: First line of defense. Scans raw text for SQL injections, command injections, prompt override attacks, and oversized payloads (>2500 characters). Automatically triggers DEFCON 1 lockdown upon malicious detection.
* **Supervisor Agent (`supervisor_agent`)**: Central orchestrator. Inspects incoming `SageState` and delegates execution between conversational tasks and automated scanning pipelines.
* **Copilot Agent (`copilot_agent`)**: Conversational operational partner. Equipped with deterministic tools (`list_database_tables`, `query_database`, `tavily_search`) for interactive querying.
* **Observe & Detect (`observe_detect_agent`)**: Connects to the active SQL telemetry engine to discover inventory depletion, sensor thresholds, or shipment bottlenecks.
* **Risk Analysis (`risk_analysis_agent`)**: Computes blast radius depth, financial exposure ranges, and downstream plant vulnerabilities.
* **Strategy Worker (`strategy_worker_node`)**: Formulates 2–3 distinct operational mitigation strategies with associated costs and implementation timelines.
* **Web Researcher (`web_researcher_node`)**: Scans real-world external news, weather reports, and supplier lead times using Tavily Search API.
* **Evaluator Agent (`evaluator_agent_node`)**: Synthesizes internal telemetry and external web findings, scores options using multi-criteria trade-offs, and prepares the final execution plan.
* **Execution Node (`execution_node`)**: Intercepted before invocation by LangGraph's `interrupt_before=["execution"]`. Resumes only upon explicit authorized approval.

---

## 🛡️ 5. The 10-Gate Execution Gateway & Rollback Engine

The `Execution Gateway` ([backend/services/execution_gateway.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/services/execution_gateway.py)) represents the deterministic security core of SageCommand V3:

| Gate | Name | Function & Validation Rules |
|:---:|:---|:---|
| **1** | **Authentication & Identity** | Validates authenticated `Identity` context; verifies session token is active and unexpired. |
| **2** | **Operational Authorization** | Re-evaluates RBAC and ABAC clearance (`action.execute` or `transaction.execute`) against tenant, workspace, and assigned plant. |
| **3** | **Scope & Tenant Match** | Validates that action target (`tenant_id`, `plant_id`) strictly matches caller's assigned scope. |
| **4** | **State Machine Transition** | Confirms action state is strictly `PENDING_APPROVAL` or `APPROVED`; prevents re-executing already committed or aborted actions. |
| **5** | **Cryptographic Staleness** | Re-computes SHA-256 payload hash to ensure plan was not altered in-flight after approval. |
| **6** | **Two-Person Rule Enforcement** | For critical/high-risk actions, verifies approver ID differs from creator ID, satisfying compliance segregation of duties. |
| **7** | **Policy Engine Revalidation** | Runs current live telemetry against hard business policies; aborts if operational limits have been crossed while awaiting approval. |
| **8** | **Idempotency Detection** | Checks execution ledger for duplicate idempotency keys within TTL window to prevent double execution. |
| **9** | **Concurrency Lock** | Acquires session-scoped mutex lock to prevent concurrent write collisions on the target asset. |
| **10** | **Physical Write & Rollback Pre-Image** | Captures snapshot of affected rows, commits atomic write, and generates a verified `CompensatingRollbackPlan`. |

---

## 🔌 6. Asynchronous Real-Time WebSocket Pipeline (`/ws/sage`)

The WebSocket nervous system connects the Next.js frontend with the asynchronous LangGraph orchestrator:
* **Duplex Protocol**: Bi-directional streaming of commands (`chat`, `scan`, `diagnostics_upload`, `approve`, `get_history`, `rollback`).
* **Active Node Telemetry**: Emits `{ "type": "node_active", "node": "evaluator" }` as the LangGraph state machine traverses vertices, animating the interactive React Flow visual graph in real-time.
* **Guardrail Intercept Payloads**: Pushes execution proposals to the user interface with full reasoning breakdown, financial impact estimate, and SQL diff before execution.
* **Fail-Closed WebSocket Authentication**: Handshake strictly inspects query param/header Bearer token; rejects unauthenticated sockets with WebSocket error code `1008 (Policy Violation)`.

---

## 🗄️ 7. Multi-Database Storage Architecture

To achieve zero read/write contention under high operational load, SageCommand V3 organizes state across dedicated SQLite databases operating in **Write-Ahead Logging (WAL)** mode:

```text
backend/
├── dynamic_datacore.sqlite             # Live Operational Data (Inventory, Orders, Telemetry)
├── sage_memory.sqlite                  # LangGraph Thread Checkpoints (SqliteSaver)
├── sage_audit_ledger.sqlite            # Tamper-Evident Hash-Chained Audit Ledger
├── sage_transactions.sqlite            # Two-Phase Transaction Plans & Rollback Logs
├── sage_ontology.sqlite                # Industrial Taxonomies & Asset Classes
├── sage_knowledge_graph.sqlite         # Enterprise Entity Relationships & Edges
├── sage_digital_twin.sqlite            # Real-Time Telemetry Mirror & History
├── sage_data_quality.sqlite            # Quality Metrics & Anomaly Profiles
├── sage_event_delivery.sqlite          # Durable Event Bus Queue & Leases
├── sage_incidents.sqlite               # Incident Records & Lifecycle Logs
├── sage_rca.sqlite                     # Root-Cause Graphs & Attribution Models
├── sage_blast_radius.sqlite            # Dependency Depth Trees & Impact Forecasts
├── sage_predictive_maintenance.sqlite  # Asset Health Trends & RUL Forecasts
├── sage_demand_forecasting.sqlite      # Time-Series Demand & Seasonality Data
├── sage_supplier_risk.sqlite           # Supplier Reliability & Disruption Scores
├── sage_sla_customer_risk.sqlite       # Customer Contracts & SLA Exposure Logs
├── sage_financial_impact.sqlite        # Financial Loss Models & Cost Exposures
├── sage_sustainability.sqlite          # Carbon Footprint & Energy Consumption Logs
├── sage_sensor_fusion.sqlite           # Multi-Modal Sensor Observations & Cross-Correlations
├── sage_what_if_simulation.sqlite      # Simulation Scenarios & Perturbation Results
├── sage_optimization.sqlite            # Solved Optimization Problems & Pareto Fronts
├── sage_decision_engine.sqlite         # Multi-Criteria Scoring & Trade-Off Matrices
├── sage_evidence_explainability.sqlite # Evidence Provenance Graphs & Explanation Traces
├── sage_confidence_uncertainty.sqlite  # Uncertainty Bounds & Confidence Scores
├── sage_sop_rag.sqlite                 # Chunked Industrial SOPs & Semantic Indices
├── sage_organizational_memory.sqlite   # Episodic Memory & Historical Precedents
├── sage_missions.sqlite                # Multi-Step Autonomous Mission Plans
├── sage_verification.sqlite            # Post-Execution Telemetry Reconciliation
└── sage_autonomy.sqlite                # Autonomy Level Grants & Delegation Matrix
```

---

## 🌐 8. Production Frontend Architecture

Built on **Next.js 16**, **React 19**, **Tailwind CSS**, and **Framer Motion**:
* **Obsidian Cyberpunk Aesthetic**: Engineered with `#020202` deep void backgrounds, neon cyan (`#00f3ff`) and neon purple (`#b026ff`) accents, glassmorphic cards, and crisp micro-animations.
* **React Flow Neural Map**: Visualizes the 9-node agent graph dynamically with pulsating edges and node activation glow based on WebSocket streaming events.
* **37 Modular Interactive Consoles**: Dedicated modals for each domain capability (Blast Radius, Sensor Fusion, What-If Simulation, Autonomy Governance, Outcome Learning, Digital Twin, etc.).
* **Framer Motion RBAC Toggle**: Real-time role switching between Operator and Manager modes, updating permission contexts instantly across all UI components.
