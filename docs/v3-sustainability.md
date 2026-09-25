# SageCommand V3 — Sustainability Intelligence Foundation (Prompt 26)

> **Sustainability Intelligence is an analytical system. It does not directly
> control physical systems, execute remediation, purchase offsets, submit
> regulatory filings, or mutate operational/financial records.**

---

## 1. Purpose

Sustainability Intelligence provides a deterministic, explainable,
tenant-isolated analytical layer for understanding operational sustainability
impact. It answers:

- How much energy is associated with an operational condition?
- What emissions exposure is associated with energy consumption?
- What resource/water/waste consumption is associated with an asset or process?
- Which operational risks correlate with sustainability exposure?
- What sustainability impact is associated with downtime, maintenance, demand,
  supplier, SLA, blast-radius, or financial-impact scenarios?
- What is observed vs. derived vs. estimated vs. simulated?
- Which assumptions produced a sustainability estimate?
- How confident is the estimate?
- How does sustainability impact change under a scenario?

---

## 2. Architecture

```
Operational Intelligence
        |
        +--> Data Quality (Prompt 14)
        +--> Anomalies   (Prompt 15)
        +--> Events      (Prompts 16/17)
        +--> Incidents   (Prompt 18)
        +--> RCA         (Prompt 19)
        +--> Blast Radius (Prompt 20)
        +--> Predictive Maintenance (Prompt 21)
        +--> Demand Forecast        (Prompt 22)
        +--> Supplier Risk          (Prompt 23)
        +--> SLA/Customer Risk      (Prompt 24)
        +--> Financial Impact       (Prompt 25)
        +--> Digital Twin / KG / Ontology
        |
        v
Sustainability Intelligence (Prompt 26)
        |
        +--> Resource Consumption (MATERIAL, RESOURCE)
        +--> Energy
        +--> Emissions (CO2e with explicit factors)
        +--> Water
        +--> Waste
        +--> Sustainability Risk (analytically separate)
        +--> Scenario Analysis
        +--> Confidence
        +--> Evidence
        +--> Provenance
        |
        v
Persistence (SQLite WAL)
        |
        v
API (/api/v3/sustainability)
        |
        v
Analytical UI (SustainabilityModal.tsx)
```

---

## 3. Contract

`backend/data/schemas/sustainability_contract.py`

### Identity

| Field | Purpose |
|-------|---------|
| `tenant_id` | Required tenant isolation key |
| `workspace_id` | Optional workspace isolation |
| `plant_id` | Optional plant isolation |
| `assessment_id` | Unique assessment identifier |
| `asset_id` | Optional asset reference |
| `supplier_id` | Optional supplier reference |
| `customer_id` | Optional customer reference |
| `process_id` | Optional process reference |

### Assessment Metadata

| Field | Purpose |
|-------|---------|
| `assessment_timestamp` | ISO-8601 UTC timestamp of the assessment |
| `calculation_version` | Version of the calculation methodology |
| `scenario_id` | Scenario identifier |
| `input_fingerprint` | Deterministic SHA-256 fingerprint |

### Dimensions

```
ENERGY             — Energy consumption (kWh, MWh, etc.)
EMISSIONS          — CO2e/CO2 emissions with explicit factors
WATER              — Water consumption (liters, m3)
WASTE              — Waste generation (kg, tonnes)
MATERIAL           — Raw material consumption
RESOURCE           — General resource utilization
SUSTAINABILITY_RISK — Qualitative risk classification (analytically distinct)
```

---

## 4. Units

Every sustainability value carries a mandatory explicit unit.

### Energy Units

```
kWh, MWh, GWh, kJ, MJ, GJ, BTU, MMBTU
Intensity: kWh/unit, MWh/unit, kWh/kg, MWh/tonne
```

### Emissions Units

```
kgCO2e, tCO2e, kgCO2, tCO2, gCO2e
```

### Water Units

```
liters, m3, gallons, liters/unit, m3/unit
```

### Waste Units

```
kg, tonnes, kg/unit, tonnes/unit
```

### Material Units

```
kg, tonnes, units, kg/unit, tonnes/unit
```

Unitless sustainability numbers are never returned. `UNKNOWN` is returned if
no valid measurement or factor exists.

---

## 5. Emissions Methodology

Emissions are calculated via three explicit pathways:

**Pathway 1 — Direct observed emissions:**
```
evidence_type ∈ {co2e_kg, emissions_co2e, ...}
→ directly from evidence
```

**Pathway 2 — Energy × grid factor:**
```
energy_consumption × grid_emissions_factor
  = kgCO2e (or tCO2e)
```
Requires:
- Energy evidence with valid energy unit
- `grid_emissions_factor` with matching denominator unit
- Both temporally valid at assessment_timestamp

**Pathway 3 — Material × material factor:**
```
material_quantity × material_emissions_factor
  = kgCO2e
```

**CO2 vs CO2e:**
- The system explicitly tracks `gas_type` (CO2, CO2e, CH4, N2O)
- CO2 and CO2e are never confused
- GWP conversion methodology is preserved when applied

---

## 6. Assumptions

All assumptions are typed, explicit, and subject to temporal validity.

```
assumption_id: unique ID
name:          machine-readable name
value:         the assumption value
unit:          explicit unit
source:        where this came from
provenance:    USER_SUPPLIED | CONFIGURATION_SUPPLIED | DERIVED | ESTIMATED
effective_from: ISO-8601 (temporal validity start)
effective_to:   ISO-8601 (temporal validity end)
confidence:    HIGH | MEDIUM | LOW | INSUFFICIENT_DATA
```

Never silently use undocumented default factors.
Future assumptions are excluded at `assessment_timestamp`.
Expired assumptions are excluded at `assessment_timestamp`.

---

## 7. Provenance

Every value carries explicit provenance:

| Provenance | Meaning |
|-----------|---------|
| `OBSERVED` | Directly measured / reported value |
| `DERIVED` | Deterministic calculation from observed inputs |
| `ESTIMATED` | Analytical estimate using explicit assumptions |
| `SIMULATED` | Scenario-derived result |
| `UNKNOWN` | Insufficient evidence |

Estimated emissions are never represented as measured emissions.

---

## 8. Confidence

Every assessment exposes explicit confidence:

| Level | Meaning |
|-------|---------|
| `HIGH` | Multiple corroborating observed sources and validated assumptions |
| `MEDIUM` | Sufficient evidence and assumptions for a reasonable estimate |
| `LOW` | Limited evidence, low-quality assumptions, or multiple DQ issues |
| `INSUFFICIENT_DATA` | Cannot produce a meaningful estimate |

Confidence is computed from:
- Evidence count and quality
- Assumption completeness and quality
- Factor recency
- Temporal validity
- Data quality issues
- Upstream confidence propagation

---

## 9. Temporal Rules

For assessment timestamp `T`:

- Only evidence with `observation_timestamp ≤ T` is accepted
- Only assumptions with `effective_from ≤ T` and `effective_to > T` are accepted
- Only emissions factors with `effective_from ≤ T` and `effective_to > T` are accepted
- Future evidence is excluded with `FUTURE_EVIDENCE_EXCLUDED` issue
- Future assumptions are excluded with `FUTURE_ASSUMPTION_EXCLUDED` issue
- Expired assumptions are excluded with `EXPIRED_ASSUMPTION_EXCLUDED` issue

Historical assessments at any past `T` are therefore reproducible given the
same inputs.

---

## 10. Baseline Methodology

`BaselineComparison` supports:

```
baseline_id:            identifies the baseline
baseline_timestamp:     start of baseline period
baseline_timestamp_end: end of baseline period
baseline_source:        provenance of the baseline
baseline_value:         SustainabilityValue at baseline
current_value:          SustainabilityValue now
delta:                  current - baseline
delta_pct:              (current - baseline) / baseline × 100
is_comparable:          True if periods and units are compatible
```

Values from incompatible periods are flagged with `is_comparable=False`.

---

## 11. Scenario Methodology

Scenarios modify analytical assumptions without mutating operational records.

| Scenario | Description |
|----------|-------------|
| `BASELINE` | Historical baseline for comparison |
| `EXPECTED` | Current expected operating conditions |
| `STRESS` | Elevated-risk scenario with pessimistic assumptions |
| `CUSTOM` | User-supplied custom scenario |

Scenario-derived values carry `provenance=SIMULATED`.
Scenario fingerprints are deterministic for identical inputs.

---

## 12. Data Quality Integration

Sustainability Intelligence integrates with Prompt 14 Data Quality:

- Missing measurements → `UNKNOWN` propagated
- Stale measurements → `EXPIRED_FACTOR_EXCLUDED` or `LOW` confidence
- Invalid units → factor excluded
- Suspicious readings → `UNCERTAIN_MEASUREMENT` issue
- Source quality limitations → `LOW` confidence

The service never silently repairs source measurements.

---

## 13. Anomaly Integration (Prompt 15)

Anomalies provide contextual evidence:

```
Anomaly
   |
   v
abnormal consumption evidence
   |
   v
sustainability exposure
```

An anomaly is evidence context, not automatic proof of environmental impact.
The `integration_context.anomaly_ids` field records referenced anomalies.

---

## 14. Event and Incident Integration (Prompts 16/17/18)

Events and incidents provide operational context:

```
incident → downtime → energy/resource exposure evidence
event → process disruption → waste exposure evidence
```

Events and incidents are not mutated.
`integration_context.incident_ids` and `event_ids` record references.

---

## 15. RCA Integration (Prompt 19)

Where RCA identifies a causal candidate, it is exposed as context.
RCA does not automatically establish environmental causation without
evidence-backed support. `integration_context.rca_ids` records references.

---

## 16. Blast Radius Integration (Prompt 20)

```
blast_radius → affected assets/processes
            → aggregated sustainability exposure
```

Graph traversal is not duplicated. The blast radius assessment ID is
referenced in `integration_context.blast_radius_ids`.

---

## 17. Predictive Maintenance Integration (Prompt 21)

```
maintenance risk → expected downtime/resource exposure
               → sustainability exposure (via explicit assumptions)
```

Maintenance actions are not created. Only monetary/resource conversion
with validated assumptions is performed.

---

## 18. Demand Forecast Integration (Prompt 22)

```
forecast demand → expected production/resource requirement
             → energy/material/emissions exposure
```

Forecast horizon, prediction interval, and confidence are respected.
Demand forecasts are not modified.

---

## 19. Supplier Risk Integration (Prompt 23)

```
supplier dependency → material/resource exposure
                  → sustainability exposure
```

Supplier data is not mutated. Procurement is not executed.

---

## 20. SLA/Customer Risk Integration (Prompt 24)

Operational SLA risk may trigger additional resource usage:
- Expedited operations
- Additional resource usage
- Rework

Calculations require explicit sustainability assumptions. Customer
records are not mutated and customers are not contacted.

---

## 21. Financial Impact Integration (Prompt 25)

Financial impact and sustainability impact are related analytical layers.
However, money is never converted directly to emissions. Any relationship
uses explicit validated evidence models.

---

## 22. Digital Twin / KG / Ontology Integration

- **Ontology**: Used for identity and semantic classification
- **Knowledge Graph**: Used for relationship context
- **Digital Twin**: Used for operational state context

The Digital Twin is not mutated. Physical actuation is not performed.
Graph traversal is not duplicated from existing services.

---

## 23. Repository

`backend/services/sustainability_repository.py`

- SQLite WAL mode
- All SQL parameterized (no string concatenation)
- Tenant isolation at every query
- Workspace isolation when `workspace_id` is provided
- Plant isolation when `plant_id` is provided
- Query results capped at 200
- Deterministic fingerprint deduplication (idempotent saves)
- Indexes on `tenant_id`, `workspace_id`, `plant_id`, `asset_id`,
  `supplier_id`, `input_fingerprint`, `assessment_timestamp`

---

## 24. API

`backend/api/sustainability_routes.py`

Base path: `/api/v3/sustainability`

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| `POST` | `/analyze` | `sustainability.analyze` | Run deterministic analysis |
| `POST` | `/scenario` | `sustainability.analyze` | Run scenario analysis |
| `GET` | `/summary` | `sustainability.read` | List summary rows |
| `GET` | `` | `sustainability.read` | List full assessments |
| `GET` | `/{assessment_id}` | `sustainability.read` | Get by ID |

All routes enforce:
- Authentication
- Tenant isolation
- Workspace isolation
- RBAC (`sustainability.read`, `sustainability.analyze`, `sustainability.admin`)
- Payload limits
- Query limits (≤200)

---

## 25. Authorization

Permissions:

```
sustainability.read    — read assessments
sustainability.analyze — create new assessments
sustainability.admin   — administrative access
```

Server-side authorization is authoritative.
Tenant isolation is enforced at both the API and repository layers.

---

## 26. Frontend

`frontend/app/components/SustainabilityModal.tsx`

Tabs:
- **Overview** — confidence, scenario, dimension summary, risk factors
- **Energy** — consumption, intensity, provenance
- **Emissions** — CO2e, factor, provenance, intensity
- **Water / Waste / Materials** — shown for valid data only
- **Evidence & Quality** — assumptions, DQ issues, known limitations
- **Scenario** — baseline, assumptions, simulated results

**The UI does NOT contain:**
- Control commands
- Energy-control buttons
- Shutdown controls
- Procurement controls
- Financial transaction controls
- Customer communication
- Execution actions
- Carbon-credit purchase buttons

---

## 27. Execution Boundary

The following are **NOT** implemented:

| Boundary | Status |
|----------|--------|
| ExecutionGateway import | NO |
| Action API execution | NO |
| Physical actuation | NO |
| PLC/device control | NO |
| Energy control | NO |
| Production scheduling | NO |
| Maintenance execution | NO |
| Procurement execution | NO |
| Supplier mutation | NO |
| Inventory mutation | NO |
| Payment execution | NO |
| Invoice mutation | NO |
| Financial transaction | NO |
| Customer mutation | NO |
| Customer communication | NO |
| Regulatory filing | NO |
| Carbon-credit purchase | NO |
| Offset purchase | NO |
| Incident mutation | NO |
| RCA mutation | NO |
| Anomaly mutation | NO |
| Demand forecast mutation | NO |
| Digital Twin actuation | NO |
| Prompt 27 implementation | NO |

---

## 28. Limitations

1. Energy consumption is not inferred from operational risk scores alone.
2. Emissions factors must be explicitly supplied; no built-in global defaults.
3. Water, waste, and material values are only available when explicit evidence exists.
4. Scope 1/2/3 GHG classification requires additional evidence beyond what the
   system currently validates.
5. The system does not calculate social/governance sustainability metrics.
6. Baseline comparison requires historically stored assessment records.
7. This system produces estimates; independent audit is required for regulatory use.

---

## 29. False Claim Prevention

The system will **NOT** automatically state:

- "carbon neutral"
- "net zero"
- "compliant"
- "sustainable"
- "ESG compliant"
- "regulatory compliant"

unless a corresponding validated evidence model explicitly supports the claim.
All estimates are described as estimates.

---

## 30. Test Coverage

See `backend/test_v3_sustainability.py`:

- ≥75 meaningful tests covering:
  - Contract validation
  - Energy, Emissions, Water, Waste, Material, Resource, Risk
  - UNKNOWN propagation
  - Determinism and fingerprinting
  - Temporal correctness
  - Baselines and scenarios
  - Confidence
  - Upstream integrations (all 15 upstream prompts)
  - Security (tenant/workspace/plant/RBAC/ABAC)
  - Repository (CRUD, fingerprint, WAL, concurrency)
  - API endpoints
  - Execution boundary (AST/static verification)
