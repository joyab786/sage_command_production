# SageCommand V3 — Decision Engine Foundation (Prompt 30)

> **Cardinal Invariant**:
> The Decision Engine produces governed analytical recommendations.
> It is an analytical decision-support component.
> It does NOT authorize, execute, or mutate operational systems.
> **DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED**

---

## 1. Executive Summary & Architecture

The **Decision Engine Foundation** is the analytical decision-support layer of the SageCommand V3 Industrial Intelligence OS. Positioned between analytical intelligence (Prompts 10–29) and independently enforced authorization/execution gateways, the Decision Engine evaluates alternative courses of action against explicit operational constraints, server-governed policies, multi-criteria objective functions, and auditable evidence snapshots.

### Architectural Position

```text
Human / Command Center
        ↓
Intelligence Interface (OmniHeader / DecisionEngineModal)
        ↓
Observations, Context, Ontology, Knowledge Graph, Digital Twin, and Governance
        ↓
Intelligence Services (What-If, Optimization, Forecasts, Risk, Sensors)
        ↓
DECISION ENGINE (Prompt 30)
        ↓
Evidence-Backed Recommendation (SHA-256 Fingerprinted & Audited)
        ↓
Existing Authorization and Policy Enforcement (RBAC / ABAC)
        ↓
Existing Execution Gateway
        ↓
Operational System
```

### Architectural Boundary

```text
DECISION ENGINE
      ↓
RECOMMENDATION ("NOT AUTHORIZED AND NOT EXECUTED")
      ↓
HUMAN OPERATOR / GOVERNED REVIEW
      ↓
EXISTING AUTHORIZATION & EXECUTION GATEWAY
      ↓
[operational execution]
```

Under no circumstances does the Decision Engine bypass human approval, call `ExecutionGateway`, or trigger automatic changes to physical PLCs, actuators, controllers, work orders, or inventory stores.

---

## 2. Supported Decision Categories

The engine supports 10 controlled, extensible analytical decision categories:

| Category | Identifier | Description |
| :--- | :--- | :--- |
| **Resource Allocation** | `RESOURCE_ALLOCATION` | Capacity, crew, machine, and shift balancing |
| **Demand Fulfillment** | `DEMAND_FULFILLMENT` | Order split, routing, and fulfillment alternative analysis |
| **Supplier Selection** | `SUPPLIER_SELECTION` | Vendor selection under cost, reliability, and lead-time constraints |
| **Maintenance Prioritization** | `MAINTENANCE_PRIORITIZATION` | Asset overhaul timing vs production impact |
| **SLA Risk Mitigation** | `SLA_RISK_MITIGATION` | Mitigation strategies for at-risk enterprise SLAs |
| **Financial Trade-Off** | `FINANCIAL_TRADEOFF` | Margin, operating cost, and tariff impact trade-offs |
| **Sustainability Trade-Off** | `SUSTAINABILITY_TRADEOFF` | Carbon footprint, energy consumption, and environmental targets |
| **Production Planning** | `PRODUCTION_PLANNING` | Batch sizing, takt-time adjustments, and schedule options |
| **Incident Response** | `INCIDENT_RESPONSE` | Containment and mitigation alternatives for factory anomalies |
| **Cross-Domain Planning** | `CROSS_DOMAIN_PLANNING` | Multi-plant, multi-tier operational planning |

---

## 3. Typed Decision Contracts

Contracts are defined in [backend/data/schemas/decision_engine_contract.py](file:///e:/js/sage_command_production/backend/data/schemas/decision_engine_contract.py):

* **`DecisionOption`**: A candidate course of action with typed parameters, expected outcomes, and strict rejection of forbidden actuation keywords (`PLC_COMMAND`, `ACTUATOR_COMMAND`, `EXECUTE_WORK_ORDER`, etc.).
* **`DecisionCriterion`**: Multi-criteria objectives with explicit units, directions (`MINIMIZE`, `MAXIMIZE`), weights, bounds, and normalization methods.
* **`DecisionConstraint`**: Hard mandatory requirements or soft preferences with standard operators (`<=`, `>=`, `==`, `<`, `>`, `IN`) evaluated against candidate outcomes.
* **`DecisionPolicy`**: Server-governed policy rules that cannot be weakened by caller inputs.
* **`DecisionEvidenceReference`**: Evidence references preserving upstream source subsystem, record ID, timestamp, provenance (`OBSERVED`, `DERIVED`, `FORECAST`, `SIMULATED`, `ESTIMATED`), quality score, and confidence.
* **`DecisionAlternative`**: Ranked candidate alternative with composite score, feasibility status, policy compliance, and binding constraint explanations.
* **`DecisionRecommendation`**: The governed recommendation payload containing `recommended_option_id`, rationale, confidence, uncertainty index, trade-offs, limitations, and the mandatory execution notice.
* **`DecisionEvaluation`**: Full immutable result with deterministic SHA-256 fingerprint and audit metadata.

---

## 4. Evaluation Pipeline

The evaluation pipeline follows 18 deterministic steps:

1. **Scope Validation**: Verifies tenant, workspace, and plant scope against caller authority.
2. **Resource Boundaries**: Validates option count (<= 100), criteria count (<= 50), constraints (<= 500), and evidence (<= 1000).
3. **Evidence Ingestion**: Validates temporal validity (no future leakage where evidence timestamp > assessment timestamp).
4. **Freshness Checks**: Identifies stale evidence (> 7 days) and generates explicit `DecisionLimitation` warnings.
5. **Actuation Rejection**: Rejects any candidate option containing forbidden actuation keywords in its ID, name, or parameters.
6. **Constraint Evaluation**: Evaluates hard and soft constraints. Hard constraint violations disqualify the candidate from feasibility.
7. **Criterion Normalization**: Computes min-max normalized scores [0.0, 1.0] respecting criterion direction.
8. **Policy Compliance**: Evaluates candidate parameters against active server-controlled policies.
9. **Composite Scoring**: Deterministically aggregates criterion scores using normalized weights or lexicographic priorities.
10. **Deterministic Ranking**: Sorts alternatives with stable tie-breaking:
    `(-is_policy_compliant, -is_feasible, -composite_score, option_id)`.
11. **Trade-Off Calculation**: Computes score and raw metric deltas between top-ranked and runner-up alternatives.
12. **Outcome Status Determination**: Assigns one of:
    - `RECOMMENDED`: Feasible, policy-compliant, confidence >= 0.65, no blocking limitations.
    - `CONDITIONALLY_RECOMMENDED`: Feasible and policy-compliant, but non-blocking limitations or marginal confidence.
    - `NO_FEASIBLE_OPTION`: All options violate hard constraints.
    - `POLICY_BLOCKED`: Candidates violate server policies.
    - `INSUFFICIENT_EVIDENCE`: Required inputs or evidence missing.
    - `CONFLICTING_EVIDENCE`: Contradictory upstream evidence detected.
    - `NEEDS_HUMAN_REVIEW`: Escalation required for safety or future leakage.
13. **Uncertainty Quantification**: Calculates uncertainty variance and confidence bounds.
14. **Deterministic Fingerprint**: Computes SHA-256 fingerprint over sorted, canonicalized problem inputs.
15. **Persistence**: Saves evaluation, alternatives, evidence snapshots, and immutable audit ledger record in SQLite WAL.
16. **Boundary Notice**: Attaches `"DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED"`.
17. **Audit Record**: Computes cryptographic payload checksum.
18. **Return**: Delivers structured `DecisionEvaluation`.

---

## 5. Persistence & Repository

Persistence is managed by [backend/repositories/decision_engine_repository.py](file:///e:/js/sage_command_production/backend/repositories/decision_engine_repository.py):

* **Engine**: SQLite in WAL mode with normal synchronization and foreign keys enabled.
* **Isolation**: Tenant isolation enforced as an absolute SQL query parameter on all reads and writes.
* **Concurrency**: Thread-safe with `threading.Lock()` and nanosecond-unique audit ledger IDs.
* **Audit Ledger**: Append-only table `decision_audit_ledger` recording `audit_id`, `actor_id`, `fingerprint`, and SHA-256 payload checksums.
* **Bounds**: Queries capped at 200 items max with safe offset handling.

---

## 6. REST API Endpoints & Permissions

Base Path: `/api/v3/decision-engine`

| Endpoint | Method | Required Permission | Description |
| :--- | :--- | :--- | :--- |
| `/evaluate` | `POST` | `decision_engine.evaluate` | Deterministically evaluates a decision problem |
| `/{decision_id}` | `GET` | `decision_engine.read` | Retrieves an evaluation by ID |
| `""` | `GET` | `decision_engine.read` | Lists historical evaluations for tenant |
| `/{decision_id}/alternatives` | `GET` | `decision_engine.read` | Retrieves ranked alternatives |
| `/{decision_id}/evidence` | `GET` | `decision_engine.read` | Retrieves evidence snapshots |
| `/{decision_id}/audit` | `GET` | `decision_engine.read` | Retrieves immutable audit ledger trail |

---

## 7. Frontend Integration

* **Modal Component**: [frontend/app/components/DecisionEngineModal.tsx](file:///e:/js/sage_command_production/frontend/app/components/DecisionEngineModal.tsx)
  * Accessible via the **Decisions** button in [frontend/app/components/OmniHeader.tsx](file:///e:/js/sage_command_production/frontend/app/components/OmniHeader.tsx).
  * Tabs: Recommendation, Alternatives & Ranking, Criteria & Weights, Constraints & Policies, Trade-offs & Sensitivity, Evidence & Provenance, Audit Ledger.
  * Prominently displays the architectural boundary banner:
    `⚠️ MANDATORY NOTICE: DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED`
  * Strictly analytical: Contains **no execution or action approval buttons**.

---

## 8. Verification & Test Suite

Dedicated test suite: [backend/test_v3_decision_engine.py](file:///e:/js/sage_command_production/backend/test_v3_decision_engine.py)

* **Test Count**: 135 passing tests (exceeds 120 test requirement).
* **Execution Boundary Tests**: AST inspection proves that neither the service nor routes import `ExecutionGateway`, `action_routes`, `action_store`, or physical actuation modules.
* **Commands**:
  ```bash
  # Dedicated Decision Engine tests
  python -m pytest backend/test_v3_decision_engine.py -q -ra

  # Full V3 regression suite
  python -m pytest backend/ -k "test_v3_" -q -ra

  # Frontend build verification
  cd frontend && npm run build
  ```
