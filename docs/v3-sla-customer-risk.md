# SageCommand V3: SLA & Customer Risk Intelligence Foundation (Prompt 24)

## 1. Purpose
The SLA & Customer Risk Intelligence Foundation is a deterministically isolated analytical domain within the SageCommand V3 architecture. Its purpose is to quantify and explain the operational risk to customer SLA obligations based on historical, current, and forecasted operational realities.

**Strict Analytical Boundary:**
This foundation is strictly analytical. It **does not** execute remediation, communicate with customers, mutate orders, adjust inventory, or create purchase orders. It provides read-only intelligence that downstream systems or users may consult.

## 2. Architecture
Following the V3 pattern, this domain sits atop operational foundations (Incidents, Anomalies, Suppliers, Predictive Maintenance, Demand Forecasting). It operates a unidirectional data flow:

```text
Operational Foundations (Evidence) -> SLACustomerRiskService -> SLACustomerRiskRepository -> API -> UI
```

## 3. Contract (`SLACustomerRiskAssessment`)
The core contract models:
- **Identity:** Tenant, Workspace, Customer, Service.
- **Time:** Assessment boundaries, commitment timestamps, expected completion.
- **Risk State:** Deterministic classifications (e.g., `ON_TRACK`, `AT_RISK`, `LIKELY_BREACH`, `BREACHED`).
- **Explainability:** Weighted risk factors and explicit evidence payloads.

## 4. Deterministic Scoring
Scoring is calculated strictly from provided context:
1. **Historical Performance:** Compliance rates impact base risk.
2. **Temporal Projection:** Expected completion vs. commitment due dates deterministically drive breach projections.
3. **Operational Evidence:** Weighted points are added for active upstream risks on the dependency path (Supplier Risk, Anomalies, Incidents, Maintenance).
4. **Data Quality Exclusions:** Insufficient history or missing parameters drop confidence and cap maximum achievable risk metrics.

## 5. Idempotency & Provenance
Every assessment generates a `sha256` `input_fingerprint` across canonical inputs (factors, evidence, customer ID, service ID, assessment timestamp). Duplicate fingerprints on the same tenant short-circuit the database insert to prevent redundant storage.

## 6. Integrations
- **Incident Management (Prompt 18):** Incident records form `INCIDENT` evidence.
- **Anomaly Detection (Prompt 15):** Anomaly records form `ANOMALY` evidence.
- **Predictive Maintenance (Prompt 21):** Asset degradation forms `PREDICTIVE_MAINTENANCE` evidence.
- **Demand Forecasting (Prompt 22):** Demand acceleration and capacity shortfalls form structural SLA exposure.
- **Supplier Risk (Prompt 23):** Upstream supplier bottlenecks form `SUPPLIER_RISK` evidence.

## 7. Temporal Correctness
The service actively filters `observation_timestamp` and `effective_timestamp` against the `assessment_timestamp` to prevent future data leakage in retrospective analysis.

## 8. Authorization & Security
The API enforces RBAC permissions (`sla_customer_risk.read`, `sla_customer_risk.analyze`) and tenant/workspace boundaries (ABAC). Unbounded queries are blocked via hardcoded limits on history requests.
