# SageCommand V3 — Confidence and Uncertainty Intelligence Foundation (Prompt 32)

## 1. Executive Summary & Purpose

The **Confidence and Uncertainty Intelligence Foundation** introduces a production-grade, deterministic, explainable, tenant-isolated analytical evaluation layer for SageCommand V3. It establishes a rigorous common framework for evaluating the evidential support, reliability, and decomposed uncertainty of analytical conclusions and recommendations produced by existing subsystems (Prompts 10–31), including:

- Industrial Ontology and Operational Knowledge Graph (Prompts 11–12)
- Digital Twin and Data Quality Engine (Prompts 13–14)
- Anomaly Detection, Event Model, and Event Bus (Prompts 15–17)
- Incident Management, Root-Cause Analysis, and Blast-Radius Intelligence (Prompts 18–20)
- Predictive Maintenance and Demand Forecasting (Prompts 21–22)
- Supplier Risk and SLA / Customer Risk Intelligence (Prompts 23–24)
- Financial Impact and Sustainability Intelligence (Prompts 25–26)
- Multimodal Sensor Fusion (Prompt 27)
- What-If Simulation and Optimization Engine (Prompts 28–29)
- Decision Engine (Prompt 30)
- Evidence and Explainability Foundation (Prompt 31)

### Cardinal Invariants

1. **Analytical Confidence Index:** Confidence is a measure of support for a specific analytical claim under a specific context. It is **not** an uncalibrated probability that the claim is true unless a validated statistical calibration explicitly justifies that meaning.
2. **Exposed Uncertainty:** Uncertainty is information that must be decomposed and exposed, never hidden behind a single composite score.
3. **No Artificial Precision:** The system never manufactures false precision, assumes unverified distributions, or interprets missing evidence as proof of safety.
4. **Read-Only Intelligence Layer:** The service is strictly a read-only analytical evaluator. It persists its own assessments, dimension records, and append-only audit trail, but **never** mutates underlying operational records or source analytical outputs.
5. **Strict Non-Execution:** Outputs carry the mandatory notice:
   `CONFIDENCE AND UNCERTAINTY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED`

---

## 2. Architecture & Data Flow

```
[Operational & Telemetry Sources]
               │
               ▼
   [Subsystem Analytical Outputs] (Prompts 11–30)
               │
               ▼
   [Evidence & Explainability Lineage] (Prompt 31)
               │
               ▼
 ┌──────────────────────────────────────────────────────────────┐
 │       CONFIDENCE & UNCERTAINTY INTELLIGENCE FOUNDATION       │
 │                                                              │
 │  1. Scope & Plant Boundary Enforcement                       │
 │  2. Temporal Horizon & Freshness Validation                  │
 │  3. 10 Independent Confidence Dimensions                     │
 │  4. Blocking Deficiency Capping Rule                         │
 │  5. Uncertainty Decomposition (Aleatoric vs Epistemic)       │
 │  6. Validated Quantitative Intervals / Qualitative Fallbacks │
 │  7. Parameter Sensitivity Analysis                           │
 │  8. Deterministic SHA-256 Fingerprinting                     │
 └──────────────────────────────────────────────────────────────┘
               │
               ├──► SQLite WAL Persistence & Audit Ledger
               └──► REST API (/api/v3/confidence-uncertainty)
```

---

## 3. Ten Independent Confidence Dimensions

Rather than collapsing all evidence indicators into an opaque single number, the engine evaluates 10 explicit dimensions:

| Dimension | Description | Required Inputs | Missing Data Behavior |
| :--- | :--- | :--- | :--- |
| **Evidence Completeness** | Ratio of available supporting evidence items against saturation threshold. | Evidence pool | None / 0.0 -> INSUFFICIENT_EVIDENCE |
| **Evidence Quality** | Mean data quality score across supporting evidence items. | Evidence quality scores | Quality < 0.3 triggers blocking deficiency cap |
| **Freshness** | Age degradation relative to configured threshold and evaluation timestamp. | Timestamps & threshold | All stale -> Capped at 0.30 |
| **Temporal Consistency** | Alignment within assessment window, absence of temporal gaps or future leakage. | Assessment timestamp | Future-dated evidence -> score 0.0 & blocked |
| **Source Reliability** | Provenance trustworthiness (Observed: 1.0, Derived: 0.85, Forecast: 0.70, Simulated: 0.65, Estimated: 0.50, Unknown: 0.20). | Evidence Provenance | Unverified synthetic provenance penalized |
| **Cross-Source Agreement** | Corroboration across independent evidence sources; absence of contradictory values. | Conflict detection | Severe conflict -> Capped at 0.35 |
| **Method Validity** | Verification that mathematical prerequisites and valid target entities are satisfied. | Target entity ID & type | Invalid target -> 0.0 |
| **Context Coverage** | Presence of plant, asset, workspace metadata and operational dependencies. | Plant & workspace scope | Missing plant -> 0.75 |
| **Model Calibration** | Evaluates empirical calibration metadata. Default analytical heuristics are labeled uncalibrated. | Calibration metadata | Uncalibrated heuristic -> 0.50 with explicit notice |
| **Lineage Integrity** | Lineage graph validity, absence of directed cycles, and absence of unresolved parent references. | Lineage parent IDs | Unresolved parents penalize score |

### Blocking Deficiency Capping Rule

A high score in one dimension (such as completeness) must never conceal a critical deficiency in another. If any blocking deficiency is detected:
- **Future-Dated Evidence Leakage:** Score forced to `0.0`.
- **All Evidence Stale:** Aggregate score capped at `0.30`.
- **Critical Low Data Quality (< 0.3):** Aggregate score capped at `0.25`.
- **Severe Source Conflicts:** Aggregate score capped at `0.35`.

---

## 4. Uncertainty Taxonomy & Decomposition

Uncertainty is explicitly classified into two fundamental branches and eight specialized categories:

### 1. Epistemic Uncertainty (Reducible by Evidence)
- **Coverage Uncertainty:** Missing upstream sources or unmonitored modalities.
- **Source Disagreement:** Direct contradictions or divergent conclusions between sensors/models.
- **Model Uncertainty:** Approximations in physics models or simulation algorithms.
- **Parameter Uncertainty:** Inaccurately known coefficients, conversion factors, or tariffs.

### 2. Aleatoric Uncertainty (Inherent Stochasticity)
- **Process Noise:** Physical variance in manufacturing tolerances and chemical kinetics.
- **Measurement Uncertainty:** Sensor precision, resolution, and thermal drift.
- **Temporal Variability:** Stochastic shifts across operational shift handovers.

### Quantitative Intervals vs. Qualitative Fallbacks
- **Mathematical Intervals:** When supported by empirical telemetry or simulation ensembles, returns `[lower_bound, upper_bound]` with verified coverage probability (e.g. 90%). Enforces `lower_bound <= upper_bound` and finite numbers.
- **Qualitative Fallback:** When numerical intervals cannot be mathematically justified, reports a qualitative uncertainty summary to prevent manufacturing false precision.

---

## 5. Security, Permissions & Tenant Isolation

### Canonical Permissions
- `confidence_uncertainty.read` — View confidence assessments, uncertainty breakdowns, and history. (Assigned to VIEWER, ANALYST, ADMINISTRATOR).
- `confidence_uncertainty.assess` — Evaluate confidence and uncertainty for targets. (Assigned to ANALYST, ADMINISTRATOR).
- `confidence_uncertainty.validate` — Validate evidence readiness and eligibility. (Assigned to ANALYST, ADMINISTRATOR).
- `confidence_uncertainty.admin` — Administrative control over weights, calibration, and thresholds. (Assigned to ADMINISTRATOR).

### Partition Enforcement
- All queries, list operations, and detail retrievals require matching `tenant_id`.
- Plant scope restrictions (`user.assigned_plants`) prevent unauthorized cross-plant visibility.
- Unauthorized access attempts return non-disclosing `404 Not Found` or `403 Forbidden` responses.

---

## 6. REST API Endpoints

Root prefix: `/api/v3/confidence-uncertainty`

| Method | Endpoint | Description | Required Permission |
| :--- | :--- | :--- | :--- |
| `POST` | `/assess` | Evaluates multi-dimensional confidence and uncertainty. | `confidence_uncertainty.assess` |
| `POST` | `/assess/batch` | Bounded batch evaluation across multiple targets. | `confidence_uncertainty.assess` |
| `POST` | `/validate` | Validates evidence eligibility and assessment readiness. | `confidence_uncertainty.validate` |
| `GET` | `/{assessment_id}` | Retrieves full assessment by ID. | `confidence_uncertainty.read` |
| `GET` | `/{assessment_id}/evidence` | Retrieves supporting and conflicting evidence references. | `confidence_uncertainty.read` |
| `GET` | `/{assessment_id}/history` | Retrieves historical assessments for target entity. | `confidence_uncertainty.read` |
| `GET` | `/entity/{entity_id}/summary`| Retrieves entity-level confidence summary. | `confidence_uncertainty.read` |
| `GET` | `/` | Paginated listing of assessments in tenant scope. | `confidence_uncertainty.read` |

---

## 7. Deterministic Fingerprinting & Reproducibility

Every assessment generates a cryptographic SHA-256 fingerprint from its canonical inputs:
- Tenant, workspace, and plant identifiers.
- Target type and target record ID.
- Assessment timestamp.
- Algorithm and contract versions (`1.0.0`).
- Dimension scores and blocking deficiencies.
- Decomposed uncertainty types.
- Sorted supporting and conflicting evidence IDs.

Identical inputs produce identical fingerprints. Any material change alters the digest, guaranteeing cryptographic reproducibility and tamper detection.

---

## 8. Verification Commands

1. **Dedicated Test Suite:**
   ```bash
   python -m pytest backend/test_v3_confidence_uncertainty.py -q -ra
   ```
2. **Full V3 Regression Suite:**
   ```bash
   python -m pytest backend/ -k "test_v3_" -q -ra
   ```
3. **Frontend Production Build:**
   ```bash
   npm run build # inside frontend/
   ```
4. **Git Diff & Whitespace Validation:**
   ```bash
   git diff --check
   ```
