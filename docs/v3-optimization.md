# SageCommand V3 — Optimization Intelligence Foundation (Prompt 29)

> **Cardinal Invariant**:
> SageCommand Optimization produces analytical recommendations. It does not execute recommendations or mutate physical/operational systems.

---

## 1. Executive Summary & Optimization Architecture

The **Optimization Intelligence Foundation** is the analytical decision-support layer of the SageCommand V3 Industrial Intelligence OS. Building upon the What-If Counterfactual Simulation layer (Prompt 28), the Digital Twin, Multimodal Sensor Fusion, and Industrial Ontology, the optimization engine formulates and solves constrained, multi-objective industrial allocation problems.

### Governed Decision Pipeline

```text
Candidate Decisions
        ↓
Feasibility Engine
        ↓
Objectives (Multi-Objective)
        ↓
Constraints (Hard & Soft)
        ↓
Deterministic Solver
        ↓
Candidate Solutions
        ↓
Ranking & Tie-Breaking
        ↓
Trade-Offs Analysis
        ↓
Sensitivity & Robustness
        ↓
Evidence Chain Synthesis
        ↓
Decision Recommendation
```

### Architectural Boundary

```text
OPTIMIZATION
    ↓
RECOMMENDATION
    ↓
HUMAN / AUTHORIZED DECISION
    ↓
[future governed execution path]
```

Under no circumstances does optimization trigger automatic execution or bypass authorized human verification.

---

## 2. Decision Variables & Analytical Scope

Decision variables represent analytical planning and allocation options. Supported types:
- `ALLOCATE_CAPACITY`: Factory line capacity distribution
- `ALLOCATE_DEMAND`: Routing customer or internal order demand
- `ASSIGN_SUPPLIER`: Supplier volume and share allocation
- `ALLOCATE_RESOURCE`: Allocation of tooling, material, or labor
- `PRIORITIZE_ASSET`: Analytical ranking of assets for inspection
- `ALLOCATE_MAINTENANCE_CAPACITY`: Bounded maintenance scheduling allocations
- `SET_PRODUCTION_LEVEL`: Analytical rate setpoints
- `SET_RESOURCE_LEVEL`: Analytical resource quotas
- `SELECT_SCENARIO`: Choosing between discrete simulated counterfactuals
- `ROUTE_ANALYTICAL_FLOW`: Logical routing across facilities

### Forbidden Actuation Boundary
Decision variables must **never** represent direct operational actuation:
`PLC_COMMAND`, `ACTUATOR_COMMAND`, `EXECUTE_WORK_ORDER`, `PURCHASE_ORDER`, `CUSTOMER_MESSAGE`, `PHYSICAL_COMMAND`.
Any attempt to define actuation commands is rejected at schema validation.

---

## 3. Decision Domains

Every decision variable requires an explicit, finite domain:
- **CONTINUOUS**: Bounded interval $[min, max]$
- **INTEGER**: Discrete integer steps within $[min, max]$
- **BINARY**: Discrete choices $\{0, 1\}$
- **CATEGORICAL**: Explicit enum/string choices (e.g. `["LINE_A", "LINE_B"]`)
- **BOUNDED_SCALAR**: Real-valued scalar $[min, max]$
- **BOUNDED_PERCENTAGE**: Bounded fraction $[0.0, 1.0]$ or percentage $[0.0, 100.0]$

NaN, Infinity, and inverted bounds ($min > max$) are strictly rejected.

---

## 4. Optimization Objectives

Supported objective types:
- `MINIMIZE_COST`: Minimize operational, resource, or procurement expense
- `MINIMIZE_DOWNTIME`: Minimize projected equipment unavailability
- `MINIMIZE_DELAY`: Minimize order schedule slippage
- `MINIMIZE_RISK`: Minimize composite failure and supplier risk
- `MINIMIZE_SERVICE_PENALTY`: Minimize projected SLA financial penalties
- `MINIMIZE_RESOURCE_USAGE`: Minimize material or component consumption
- `MINIMIZE_ENERGY`: Minimize power consumption (kWh)
- `MINIMIZE_EMISSIONS`: Minimize carbon footprint ($\text{kg CO}_2\text{e}$)
- `MAXIMIZE_THROUGHPUT`: Maximize finished goods output
- `MAXIMIZE_SERVICE_LEVEL`: Maximize on-time, in-full fulfillment
- `MAXIMIZE_UTILIZATION`: Maximize productive machine utilization
- `MAXIMIZE_MARGIN`: Maximize gross economic return
- `MAXIMIZE_RESILIENCE`: Maximize diversity and redundancy of allocations

Each objective records:
- `objective_id`, `name`, `direction` (`MINIMIZE` / `MAXIMIZE`)
- `weight`: Finite, non-negative auditable weight
- `unit`: Engineering unit
- `weight_source`, `weight_version`, `normalization`

---

## 5. Multi-Objective Optimization & Weight Safety

Deterministic methods:
1. **Weighted Sum**: $Score = \sum w_i \cdot \text{Normalized}(Obj_i) - \text{Penalties}$
2. **Lexicographic**: Optimize highest priority objective first, breaking ties on secondary objectives.
3. **Constraint-First**: Hard constraints strictly dominate soft preferences.
4. **Pareto Bounded**: Discover non-dominated frontier candidates.

Weights are explicit, versioned, and auditable. Hidden weights or ungrounded LLM weight selection are strictly prohibited.

---

## 6. Constraints: Hard vs Soft & Binding Analysis

Typed constraints:
- `CAPACITY`: Physical throughput limits
- `DEMAND`: Required order volume
- `INVENTORY_AVAILABILITY`: On-hand stock thresholds
- `SUPPLIER_CAPACITY`: Vendor supply limits
- `ASSET_AVAILABILITY`: Machine operational readiness
- `RESOURCE_AVAILABILITY`: Tooling and workforce limits
- `PRODUCTION_LIMIT`: Maximum safe speeds
- `QUALITY_LIMIT`: Acceptable scrap/defect rates
- `SLA_LIMIT`: Customer contractual thresholds
- `ENERGY_LIMIT`: Power caps
- `EMISSION_LIMIT`: Environmental compliance ceilings
- `BUDGET_LIMIT`: Financial expense ceilings
- `DEPENDENCY`: Upstream/downstream flow dependencies
- `TEMPORAL`: Horizon and deadline limits
- `SCENARIO`: Counterfactual boundary conditions

### Hard vs Soft Constraints
- **Hard Constraints**: Mandatory conditions. If violated, candidate is marked `INFEASIBLE` and receives a heavy penalty.
- **Soft Constraints**: Preferred conditions. May be violated with an explicit, auditable penalty ($penalty = magnitude \times weight$).

### Binding Constraints
A satisfied constraint is classified as **binding** when its margin is zero or within 5% of its threshold, indicating an active trade-off bottleneck.

---

## 7. Feasibility Engine & Infeasibility Relaxation

The feasibility engine verifies problem parameters prior to solving:
1. Structural integrity of variables and domains
2. Non-actuating safety compliance
3. Bounded resource constraints
4. Total capacity vs minimum demand contradictions

If infeasible, the engine does not simply return "No solution"; it produces **structured relaxation recommendations** calculated deterministically (e.g. `capacity +300` or `demand -350`).

---

## 8. Solver Adapter Architecture & Resource Bounds

Solvers implement a common `OptimizationSolver` contract:
- `DeterministicBoundedSolver`: Exhaustive combinatorial search over discrete grids. Can claim `OPTIMAL` when search is complete.
- `GreedySolver`: Heuristic priority allocation. Claims `HEURISTIC`.
- `LocalImprovementSolver`: Hill-climbing neighborhood search. Claims `HEURISTIC`.
- `LexicographicSolver`: Multi-objective hierarchical search.

### Resource Bounds
- Maximum Decision Variables: 100
- Maximum Candidates Evaluated: 10,000
- Maximum Iterations: 10,000
- Maximum Objectives: 20
- Maximum Constraints: 500
- Maximum Candidates Returned: 100

If search is truncated by resource limits, `RESOURCE_LIMIT` optimality status is reported.

---

## 9. Optimality Semantics

| Status | Definition |
| :--- | :--- |
| `OPTIMAL` | Proven mathematically optimal via complete bounded search. |
| `FEASIBLE_BEST_FOUND` | Highest-scoring feasible solution discovered under truncation or search limits. |
| `HEURISTIC` | Derived from greedy or local improvement heuristics without optimality proof. |
| `PARTIAL` | Incomplete allocation across variables. |
| `INFEASIBLE` | No candidate satisfies all hard constraints. |
| `RESOURCE_LIMIT` | Solver was truncated by computational budget. |
| `UNKNOWN` | Status cannot be deterministically validated. |

---

## 10. Candidate Ranking & Deterministic Tie-Breaking

Candidates are ordered using a strict, deterministic hierarchy:
1. Feasibility (`FEASIBLE` precedes `INFEASIBLE`)
2. Soft constraint penalty (lowest penalty first)
3. Composite objective score (descending)
4. Primary objective value (respecting MIN / MAX)
5. Canonical Candidate ID string (alphabetical tie-breaker)

Never relies on undefined dictionary or set iteration orders.

---

## 11. Multi-Candidate Trade-Off Analysis

Compares alternative feasible solutions against the recommended plan:
- Objective value deltas and percentage shifts
- Identified advantages and trade-off sacrifices
- Quantifies exchange rates (e.g. "+10% cost delivers -35% risk reduction and -15% emissions")

---

## 12. Sensitivity Analysis & Deterministic Robustness

Evaluates controlled perturbations against the recommended solution:
- Demand $\pm 5\%$, $\pm 10\%$
- Capacity $\pm 5\%$, $\pm 10\%$
- Supplier risk $+10\%$
- Energy factor $+10\%$

### Robustness Classification
- `ROBUST`: Solution remains feasible across all tested parameter perturbations.
- `SENSITIVE`: Feasible under $\pm 5\%$ shifts, but violates constraints at $\pm 10\%$.
- `FRAGILE`: Violates constraints under small $\pm 5\%$ perturbations.
- `UNKNOWN`: Perturbations could not be evaluated.

---

## 13. Upstream Intelligence Integration & Evidence

Integrates upstream analytical truth:
- **What-If Simulation** (Prompt 28): Scenario states, baseline deltas, constraint margins.
- **Demand Forecasting** (Prompt 22): Projected horizon demand and prediction intervals.
- **Supplier Risk** (Prompt 23): Vendor reliability indices and concentration risk.
- **Predictive Maintenance** (Prompt 21): Asset failure probability and maintenance urgency.
- **SLA / Customer Risk** (Prompt 24): Projected contractual delivery penalties.
- **Financial Impact** (Prompt 25): Cost of downtime and margin models.
- **Sustainability** (Prompt 26): Carbon emission and energy consumption factors.
- **Digital Twin** (Prompt 13): Live operational baselines.

Each evidence item records: `evidence_id`, `source_type`, `source_id`, `provenance`, `confidence`, and `contribution`.

---

## 14. Deterministic SHA-256 Fingerprinting

Fingerprints ensure cryptographic idempotency and reproducibility. Computed across:
- Tenant, workspace, and plant scopes
- Canonical sorted variables and domains
- Canonical sorted objectives and weights
- Canonical sorted constraints and operators
- Context references and parameters
- Multi-objective method, solver method, and version

Identical problems yield identical SHA-256 fingerprints.

---

## 15. Persistence Architecture

Backed by SQLite WAL mode:
- `optimization_problems`: Problem formulations and parameters
- `optimization_results`: Optimization runs, scores, optimality status, and fingerprints
- `optimization_candidates`: Ranked candidate solution values
- `optimization_evidence`: Upstream evidence chains
- `optimization_sensitivities`: Perturbation test results

Enforces strict tenant isolation, foreign key constraints, indexes, and parameterized SQL.

---

## 16. REST API Endpoints

Base path: `/api/v3/optimization`

| Method | Endpoint | Description | Required Permission |
| :--- | :--- | :--- | :--- |
| `POST` | `/analyze` | Formulates and solves optimization problem | `optimization.analyze` |
| `GET` | `/{optimization_id}` | Retrieves full optimization result | `optimization.read` |
| `GET` | `` | Lists optimization result summaries | `optimization.read` |
| `GET` | `/{optimization_id}/candidates` | Retrieves ranked candidate allocations | `optimization.read` |
| `GET` | `/{optimization_id}/sensitivity` | Retrieves parameter sensitivity and robustness | `optimization.read` |
| `GET` | `/{optimization_id}/evidence` | Retrieves upstream evidence chain | `optimization.read` |

---

## 17. Permissions & Authorization

Registered canonical permissions:
- `optimization.read`: Read-only visibility into problems, solutions, and trade-offs.
- `optimization.analyze`: Authority to formulate and run optimization analyses.
- `optimization.evaluate`: Authority to evaluate candidate trade-offs and sensitivity.
- `optimization.admin`: Administrative authority over solver configurations and resource limits.

Roles:
- `VIEWER`: granted `optimization.read`
- `ANALYST`: granted `optimization.analyze`, `optimization.evaluate`
- `ADMINISTRATOR`: granted `optimization.admin`

---

## 18. Security & Isolation

- **Tenant Isolation**: Every database query and API endpoint enforces strict tenant boundaries. Cross-tenant access returns HTTP 403.
- **Plant Scoping**: Plant-restricted operators can only access optimization runs for authorized plants.
- **Input Sanitization**: Rejects expressions containing dangerous tokens (no `eval`, `exec`, or code injection).
- **Parameterized SQL**: All persistence queries use strict SQL parameters.

---

## 19. Execution Boundary Verification

Static and runtime invariants ensure:
- The optimization module contains no imports or invocations of `ExecutionGateway`, `Action API`, PLC controllers, or physical actuators.
- Recommendations remain advisory decision intelligence until authorized through human operational review.
