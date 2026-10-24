# 📚 SageCommand V3 — Enterprise Documentation Suite

Welcome to the **SageCommand V3 Industrial Operations AI OS** documentation repository. This directory contains comprehensive technical specifications, operational manuals, API references, architectural baseline reports, and compliance documentation for SageCommand OS.

---

## 🗂️ Documentation Directory Structure

### 🏛️ Core Platform & System Documentation
* **[Master Architecture Specification](./architecture.md)** — High-level architecture, 12-stage continuous operational loop, agent topology, and system boundaries.
* **[V3 Target System Architecture Specification](./architecture-v3.md)** — Detailed technical specification of the decoupled V3 microservices and LangGraph orchestrator.
* **[Comprehensive API & WebSocket Documentation](./api_docs.md)** — Exhaustive catalog of all 37+ REST route modules, payload schemas, query parameters, and real-time WebSocket protocol (`/ws/sage`).
* **[Operator & Administrator User Manual](./user_manual.md)** — Step-by-step navigation manual for the Obsidian Command Center dashboard, interactive modals, and HITL authorization workflows.
* **[Production Deployment & Infrastructure Guide](./deployment_guide.md)** — Cloud deployment (Docker, Kubernetes, Railway, Vercel), reverse proxy setup, environment variable configuration, and security settings.
* **[Operations & Maintenance Troubleshooting Guide](./maintenance_guide.md)** — Runbook for SQLite database locks, WAL mode management, hash chain verification, event bus dead-letter recovery, and LLM failover.
* **[Release Changelog](./changelog.md)** — Comprehensive version history tracking the evolution from V1.0 to V2.0, and the V3.0 Enterprise Architecture release.
* **[System Test Reports & Quality Assurance](./test_reports.md)** — Verification results across the 45+ automated backend test suites, security test cases, and frontend build validations.
* **[Enterprise UAT Sign-Off Certificate](./uat_signoff.md)** — Formal User Acceptance Testing sign-off template and verification matrix for stakeholder deployment.

---

### 🛡️ Security, Governance & Audit Foundations
* **[Security Architecture & Threat Model](./security-v3.md)** — Zero-trust identity model, DEFCON threat levels, prompt injection defenses, and network perimeter policies.
* **[Security Threat Model & STRIDE Analysis](./security-threat-model-v3.md)** — STRIDE threat enumeration, attack surface analysis, and mitigation controls.
* **[Pre-Prompt 10 Security Baseline Report](./v3-pre-prompt10-security-baseline-report.md)** — Security remediation and baseline assessment for initial system hardening.
* **[Security Migration & Hardening Report](./v3-security-migration.md)** — Migration report detailing JWT integration, sanitization, and header isolation.
* **[Audit & Decision Ledger Specification](./audit-decision-ledger-v3.md)** — Tamper-evident, hash-chained append-only ledger (`sage_audit_ledger.sqlite`) with SHA-256 state tracking.
* **[Audit Ledger Baseline Report](./v3-audit-ledger-baseline-report.md)** — Performance and integrity benchmark for the audit ledger foundation.
* **[Policy Engine Specification](./policy-engine-v3.md)** — Deterministic operational rule evaluation, hard/soft constraint checking, and violation categorization.
* **[Policy Engine Baseline Report](./v3-policy-engine-baseline-report.md)** — Benchmark metrics and test results for policy evaluation throughput.
* **[RBAC & ABAC Access Control Specification](./rbac-abac-v3.md)** — Role-Based and Attribute-Based Access Control enforcing tenant isolation, assigned plants, and clearance levels.
* **[RBAC & ABAC Baseline Report](./v3-rbac-abac-baseline-report.md)** — Permission hierarchy tests, fail-closed validation, and regression suites.

---

### ⚡ Data, Database Gateway & Execution Pipelines
* **[Database Gateway Specification](./database-connection-gateway-v3.md)** — Isolated connection pooling, parameterized query execution, schema introspection, and network security policies.
* **[Database Gateway API Reference](./api/database-gateway-v3.md)** — Specific endpoint schemas for database tethering, query execution, and connection lifecycle.
* **[Database Architecture Specification](./database-architecture-v3.md)** — Multi-database SQLite architecture with WAL mode, domain-isolated databases, and schema contracts.
* **[Database Architecture Baseline Report](./v3-database-architecture-baseline.md)** — Database read/write benchmarks and connection durability metrics.
* **[Action API Specification](./action-api-v3.md)** — Structured operational action definitions, action registries, validator pipelines, and idempotency keys.
* **[Execution Gateway Specification](./v3-execution-gateway.md)** — 10-Gate deterministic final write boundary enforcing cryptographic integrity, approvals, and physical writes.
* **[Execution Gateway Baseline Report](./v3-execution-gateway-baseline-report.md)** — Multi-gate execution pipeline latency and concurrency validation.
* **[Transaction Plan & Rollback Engine](./transaction-rollback-v3.md)** — ACID transaction plans, two-phase commit, compensating rollback actions, and cryptographic state hashing.
* **[Transaction Rollback Baseline Report](./v3-transaction-rollback-baseline-report.md)** — Failure simulation and automated rollback benchmark results.

---

### 🧠 Domain Intelligence & Analytics Subsystems
* **[Industrial Domain Ontology](./v3-industrial-ontology.md)** — Equipment taxonomies, asset classes, failure modes, and spatial relationships.
* **[Operational Knowledge Graph](./v3-knowledge-graph.md)** — Topology modeling, dependency tracing, upstream/downstream graph traversal, and freshness tracking.
* **[Digital Twin Telemetry Mirror](./v3-digital-twin.md)** — Real-time telemetry state synchronization, physical asset mirroring, and state history.
* **[Data Quality Intelligence](./v3-data-quality.md)** — Telemetry validation, completeness, latency, anomaly profiling, and quality score computation.
* **[Continuous Anomaly Detection](./v3-anomaly-detection.md)** — Statistical z-score detection, adaptive thresholds, and multi-sensor telemetry scanning.
* **[Root-Cause Analysis (RCA)](./v3-root-cause-analysis.md)** — Automated 5-Whys graph traversal, candidate scoring, and telemetry correlation.
* **[Blast-Radius Intelligence](./v3-blast-radius-intelligence.md)** — Cascading failure propagation, dependency depth analysis, and affected node enumeration.
* **[Predictive Maintenance Intelligence](./v3-predictive-maintenance.md)** — Asset health scoring, remaining useful life (RUL) estimation, and degradation forecasting.
* **[Demand Forecasting Intelligence](./v3-demand-forecasting.md)** — Inventory consumption projection, replenishment modeling, and historical seasonality analysis.
* **[Supplier Risk Intelligence](./v3-supplier-risk.md)** — Supplier reliability scoring, lead-time variance tracking, and supply disruption warnings.
* **[SLA & Customer Risk Intelligence](./v3-sla-customer-risk.md)** — Contractual SLA violation prediction, order delay risk modeling, and penalty estimation.
* **[Financial Impact Intelligence](./v3-financial-impact.md)** — Analytical-only financial loss calculation, downtime cost quantification, and currency normalization.
* **[Sustainability Intelligence](./v3-sustainability.md)** — Carbon footprint modeling, energy consumption auditing, and green optimization scenarios.
* **[Multimodal Sensor Fusion](./v3-sensor-fusion.md)** — Cross-modal sensor correlation (temperature, vibration, acoustic, power) and sensor degradation detection.
* **[What-If Simulation Intelligence](./v3-what-if-simulation.md)** — Scenario perturbation, counterfactual modeling, and impact prediction without physical risk.
* **[Optimization Intelligence Foundation](./v3-optimization.md)** — Multi-objective optimization, constraint satisfaction, and Pareto frontier generation.
* **[Decision Engine Foundation](./v3-decision-engine.md)** — Multi-criteria decision evaluation, option trade-off matrix, and policy-compliant scoring.
* **[Evidence & Explainability Foundation](./v3-evidence-explainability.md)** — Transparent reasoning graphs, citation tracking, and explainable AI audit trails.
* **[Confidence & Uncertainty Intelligence](./v3-confidence-uncertainty.md)** — Epistemic and aleatoric uncertainty modeling, confidence intervals, and sensitivity analysis.
* **[Standard Operating Procedure (SOP) RAG](./v3-sop-rag.md)** — Semantic document ingestion, industrial SOP chunking, BM25/vector hybrid retrieval.
* **[Organizational Memory Foundation](./v3-organizational-memory-foundation.md)** — Episodic and semantic operational memory, past incident recall, and precedent retrieval.

---

### 🔄 Autonomous Execution & Closed-Loop Governance
* **[Mission Architecture Foundation](./v3-mission-architecture.md)** — Autonomous multi-step mission decomposition, prerequisite validation, and execution tracking.
* **[Continuous Verification Engine](./v3-continuous-verification-engine.md)** — Post-execution telemetry verification, sensor divergence detection, and reconciliation findings.
* **[Autonomy Levels & Guarded Delegation](./v3-autonomy-governance-baseline-report.md)** — L0–L4 autonomy governance, auto-approval parameter thresholds, and emergency revocation.
* **[Closed-Loop Learning Foundation](./v3-closed-loop-learning.md)** — Event-driven continuous learning loop connecting execution results back to operational intelligence.
* **[Closed-Loop Outcome Evaluation](./v3-closed-loop-outcome-evaluation.md)** — Pre-execution vs. post-execution drift evaluation, strategy efficacy scoring, and confidence tuning.
* **[Event-Driven Architecture & Event Bus](./v3-event-driven-architecture.md)** — In-memory & durable event bus, lease-based delivery, worker pool, and at-least-once delivery guarantees.
