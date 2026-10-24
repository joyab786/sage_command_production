# 📖 SageCommand V3 — Operator & Administrator User Manual

> **System**: SageCommand V3 Enterprise Autonomous & Operational Intelligence OS  
> **Interface**: Obsidian Cyberpunk Command Center (Next.js 16 / React 19)  
> **Target Audience**: Plant Managers, Operations Leads, System Administrators, and Shift Supervisors  

---

## 🖥️ 1. Navigating the Obsidian Command Console

The SageCommand V3 user interface is organized into a modular bento grid designed for high-density industrial telemetry monitoring and fast decision-making.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                       OMNI HEADER                                      │
│  [SAGE OS V3]  [DEFCON 5: NORMAL]  [LIVE UPLINK]  [MOUNT FILE]  [CORE SCAN]  [OP / MGR]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                       METRICS ROW                                      │
│  [ ACTIVE DB: 1 ]  [ ANOMALIES: 3 ]  [ BLAST RADIUS: 4 ]  [ AUTONOMY: L2 ]  [ LAT: 12ms]│
├────────────────────────────────────────┬───────────────────────────────────────────────┤
│                                        │                                               │
│       NEURAL FLOW GRAPH (React Flow)   │             STRATEGIC COPILOT CONSOLE         │
│                                        │                                               │
│   • Visual 9-Node Agent Topology       │   • Natural Language Industrial Dialogue      │
│   • Pulsating Active Edges             │   • SQL Schema & Context Augmented Answers    │
│   • Real-Time WebSocket Streaming      │   • Suggested Operational Commands            │
│   • Interactive Modal Launchers        │                                               │
│                                        │                                               │
├────────────────────────────────────────┴───────────────────────────────────────────────┤
│                                   EXECUTION FEED & TELEMETRY                           │
│  • Terminal Log Stream                                                                 │
│  • Human-in-the-Loop Guardrail Intercept Cards (Authorize / Abort)                     │
│  • Transaction Rollback Compensating Action Trigger                                   │
│  • Hardware Vision Diagnostic Incident Cards                                           │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 2. Getting Started & Initial Connection

### Step 1: Launching the Applications
1. Ensure the FastAPI backend server is running: `http://localhost:8000`.
2. Ensure the Next.js development server is active: `http://localhost:3000`.
3. Open your browser to `http://localhost:3000`. The console will display `[SYSTEM] > Neural Tether Initializing...` in the lower execution feed. Once established, the telemetry indicator will glow emerald green (`ONLINE`).

### Step 2: Database Tethering (Live Uplink)
SageCommand V3 operates by attaching its analytical brain directly to your production or replica database clusters:
1. Click the **LIVE UPLINK** button in the OmniHeader.
2. In the modal, provide your database connection string:
   * **PostgreSQL**: `postgresql://user:password@pg-cluster.internal:5432/production_floor`
   * **MySQL**: `mysql+pymysql://user:password@mysql-db:3306/plant_inventory`
   * **SQLite**: `sqlite:///./dynamic_datacore.sqlite`
3. Click **Establish Tether**. The Database Gateway verifies network policies, establishes SSL, and introspects table schemas without interrupting the background agent loop.

### Step 3: Mounting Flat Files (CSV / SQLite)
If your operational data originates from legacy ERP dumps or machine logs:
1. Click **MOUNT FILE** in the OmniHeader.
2. Select your `.csv` or `.sqlite` file.
3. The backend automatically parses the columns, creates relational tables in `dynamic_datacore.sqlite`, and mounts the database instantly.

---

## ⚡ 3. Executing Operational Workflows

### 1. Initiating an Autonomous Core Scan
To prompt the multi-agent system to scan the entire connected infrastructure for supply chain delays, inventory depletion, or sensor anomalies:
1. Click the **CORE SCAN** button in the OmniHeader.
2. Observe the **Neural Flow Graph**:
   * The `Observe & Detect` node illuminates cyan.
   * Telemetry streams to `Risk Analysis` and `Strategy Worker`.
   * `Web Researcher` queries Tavily for external market context.
   * `Evaluator` synthesizes the optimal mitigation plan.
3. If an anomaly is identified, an anomaly summary badge will appear in the Metrics Row, and a detailed incident card will be pushed to the Execution Feed.

### 2. Conversing with the Strategic Copilot
You can interact directly with your operational copilot via the right-hand panel:
* **Check Inventory**: `"List all components in Plant 01 with stock levels under 20%."`
* **Analyze Bottlenecks**: `"Which suppliers have the highest lead-time variance this quarter?"`
* **Evaluate Maintenance**: `"Are any CNC milling machines showing vibration anomalies?"`
* **Run Scenarios**: `"What is the financial impact if Line 3 experiences a 48-hour shutdown?"`

The copilot utilizes tool-augmented generation to inspect schemas, execute parameterized read-only queries, and verify external market factors before answering.

### 3. Human-in-the-Loop (HITL) Guardrail Intercept
Whenever the AI determines that a write operation is required (e.g., ordering parts, updating machine speeds, altering price matrices):
1. **Hard Halt**: LangGraph automatically pauses the pipeline using `interrupt_before=["execution"]`.
2. **Evaluation Card**: A glowing amber card appears in the Execution Feed displaying:
   * The exact proposed SQL query / API mutation.
   * A plain-English operational justification.
   * Estimated financial impact and risk tier (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
   * Two-person rule approver requirements.
3. **Role Check**: You must be toggled into the **Manager** role in the OmniHeader.
4. **Action**:
   * Click **AUTHORIZE**: The plan is submitted to the 10-Gate Execution Gateway, validated against active policies, and committed to the physical database.
   * Click **ABORT**: The execution thread terminates safely with zero database mutations recorded.

### 4. Transaction Rollback & Compensating Actions
If post-execution telemetry indicates unexpected sensor divergence or an operational mistake:
1. Click the **TRANSACTIONS** button on the console to open the **Transaction Plan Modal**.
2. Locate the executed transaction record.
3. Inspect the recorded pre-image row snapshot.
4. Click **ROLLBACK**. The Execution Gateway executes the pre-compiled compensating operations and returns the database to its exact prior state.

### 5. Multi-Modal Vision Diagnostics
When physical machinery or parts on the factory floor suffer damage:
1. In the Execution Feed or Header, select **HARDWARE VISION**.
2. Upload or drag-and-drop a photograph of the damaged component (gearbox, turbine blade, conveyor belt).
3. The Vision Diagnostics agent calls Google Gemini 2.0 Flash to diagnose the failure mode, assign a severity rating (`MINOR`, `MODERATE`, `CRITICAL`), and generate a maintenance work order proposal.

### 6. Time Travel & State Checkpointing
To audit how the AI reached a specific conclusion or inspect past execution snapshots:
1. Click **TIMELINE** in the OmniHeader to open the **Timeline Modal**.
2. The modal displays every historical LangGraph thread checkpoint persisted in `sage_memory.sqlite`.
3. Select any historical step to inspect the state variables, agent outputs, and sensor readings present at that exact moment in time.

---

## 🎛️ 4. Interactive Domain Modal Consoles Directory

The Obsidian Command Center provides 37 specialized modals accessible via header buttons, metric chips, or graph nodes:

| Modal Console | Purpose & Operator Action |
|:---|:---|
| **Anomaly Modal** | Displays statistical z-scores, affected telemetry channels, and allows triggering high-frequency anomaly scans. |
| **Blast Radius Modal** | Visualizes dynamic CSS pulse rings illustrating upstream and downstream cascading plant dependencies. |
| **Root-Cause Analysis (RCA)** | Displays interactive 5-Whys graph traversals attributing equipment failure to specific root causes. |
| **Digital Twin Modal** | Real-time 3D/2D sensor mirror displaying live temperature, pressure, RPM, and vibration metrics for physical machines. |
| **Data Quality Modal** | Displays sensor completeness ratios, signal latency, and flags drifting or uncalibrated IoT sensors. |
| **Predictive Maintenance** | Displays remaining useful life (RUL) degradation curves and failure horizon forecasts. |
| **Sensor Fusion Modal** | Cross-correlates multi-modal sensor signals (acoustic, thermal, power, and vibration) to catch early degradation. |
| **What-If Simulation** | Enables operators to perturb parameters (e.g., fuel cost +20%, machine downtime 3 days) and preview projected outcomes. |
| **Optimization Modal** | Solves multi-objective optimization trade-offs (maximizing throughput while minimizing carbon emissions). |
| **Decision Engine Modal** | Ranks multiple candidate solutions using weighted utility scoring against organizational policy constraints. |
| **Evidence & Explainability** | Shows transparent citation chains, evidence documents, and logic traces supporting AI recommendations. |
| **Confidence & Uncertainty** | Visualizes epistemic vs. aleatoric uncertainty bounds and parameter sensitivity distributions. |
| **Autonomy Governance** | Displays active L0–L4 autonomy grants, auto-approval thresholds, and provides an instant emergency revocation kill-switch. |
| **Outcome Learning Modal** | Compares predicted vs. actual post-execution telemetry, measures metric drift, and displays model calibration adjustments. |
| **Financial Impact Modal** | Breaks down downtime, scrap, penalty, and labor costs into deterministic financial exposure figures. |
| **Sustainability Modal** | Tracks Scope 1 and Scope 2 carbon emissions, energy efficiency ratings, and models green operating regimes. |
| **SLA Customer Risk Modal** | Monitors customer contracts, order fulfillment deadlines, and flags high-risk delivery breaches. |
| **Supplier Risk Modal** | Scores tier-1 and tier-2 suppliers based on historical delivery variance, quality reject rates, and geopolitical stability. |
| **Demand Forecasting** | Forecasts future inventory demand using time-series modeling with seasonal replenishment bands. |
| **Incident Management** | Full-lifecycle incident triage console managing severity classification, team dispatch, and post-mortems. |
| **Audit Ledger Modal** | Displays the tamper-evident SHA-256 hash-chained event ledger for regulatory compliance auditing. |
| **Knowledge Graph Modal** | Allows interactive exploration of enterprise physical and logical asset relationships. |
| **Ontology Modal** | Browses the canonical equipment classification hierarchy, asset taxonomies, and standardized failure modes. |

---

## 🔒 5. Roles & Security Clearances

The command center enforces Role-Based and Attribute-Based Access Control:
* **Operator Mode (`operator_token`)**:
  * Clearance Level: 1.
  * Permissions: View dashboards, run queries, trigger anomaly scans, inspect digital twins, view simulations.
  * Write Operations: Restricted; cannot authorize guardrail actions or execute database transactions.
* **Manager Mode (`manager_token`)**:
  * Clearance Level: 2.
  * Permissions: All operator permissions plus HITL Authorization, transaction execution, rollback approval, and mission creation.
* **Administrator Mode (`admin_token`)**:
  * Clearance Level: 3.
  * Permissions: Full system configuration, policy engine rule creation, autonomy grant management, and system shutdown.
* **Security Admin Mode (`security_token`)**:
  * Clearance Level: 3.
  * Permissions: DEFCON threat level override, audit ledger cryptographic verification, and security incident management.
