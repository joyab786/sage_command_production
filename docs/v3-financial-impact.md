# 💰 SageCommand V3 — Financial Impact Intelligence Specification

> **System**: SageCommand V3 Enterprise Autonomous & Operational Intelligence OS  
> **Status**: Analytical Only (Deterministic, Non-Mutating)  
> **Service Implementation**: [backend/services/financial_impact_service.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/services/financial_impact_service.py)  
> **API Routes**: [backend/api/financial_impact_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/financial_impact_routes.py)  
> **Database**: `sage_financial_impact.sqlite`  

---

## 📌 1. Subsystem Overview & Critical Safety Boundary

The **Financial Impact Intelligence Service** is a deterministic, analytical-only subsystem in SageCommand V3. It translates upstream operational signals (anomalies, equipment downtime, supply chain delays, quality defects) into quantitative financial exposure estimates.

### 🛡️ Critical Safety Boundary (ANALYTICAL ONLY)
* **Zero System Mutations**: The financial impact service does **NOT** execute, trigger, or mutate any financial, payment processing, invoice, ERP, procurement, order, or banking systems.
* **Deterministic Calculations**: No black-box generative AI math is permitted for financial valuations. All exposures are calculated through deterministic arithmetic formulas with explicit assumption provenance.
* **Uncertainty & Incompleteness Invariants**: If input telemetry or cost assumptions are missing or unvalidated, the calculation chain returns `UNKNOWN` or `INSUFFICIENT_DATA` rather than hallucinating estimates.

---

## 📐 2. The Deterministic Calculation Chain

The service processes financial assessments through a strict three-stage calculation pipeline:

```
┌─────────────────────────┐     ┌─────────────────────────┐     ┌─────────────────────────┐
│     SOURCE EVIDENCE     │  +  │  VALIDATED ASSUMPTIONS  │  =  │   FINANCIAL EXPOSURE    │
│  • Downtime Duration    │     │  • Cost per Hour ($/hr) │     │  • Base Expected ($)    │
│  • Affected Units/SKUs  │     │  • Scrap Cost ($/unit)  │     │  • Best Case Exposure   │
│  • SLA Penalty Terms    │     │  • Overtime Hourly Rate │     │  • Worst Case Exposure  │
└─────────────────────────┘     └─────────────────────────┘     └─────────────────────────┘
```

### Supported Financial Impact Categories
1. **Downtime Losses (`DOWNTIME_LOSS`)**: Idle line costs, unabsorbed overhead, lost production capacity.
2. **Scrap & Rework (`SCRAP_REWORK`)**: Ruined raw materials, damaged subassemblies, re-machining labor.
3. **SLA Penalties (`SLA_PENALTY`)**: Contractual liquidated damages for missed customer delivery windows.
4. **Logistics & Expedited Freight (`EXPEDITED_FREIGHT`)**: Premium air shipping fees to avoid line halts.
5. **Labor Overtime (`LABOR_OVERTIME`)**: Unplanned maintenance and recovery shifts.
6. **Energy & Utility Spikes (`ENERGY_SPIKE`)**: Peak-tariff surge costs due to machinery inefficiency.

---

## 💱 3. Multi-Currency Normalization & Provenance

* **Explicit Conversions**: Supports deterministic currency conversions across major industrial denominations (`USD`, `EUR`, `GBP`, `JPY`, `INR`, `CAD`, `AUD`, `CHF`, `CNY`).
* **Conversion Provenance**: Every converted value preserves the explicit exchange rate applied, timestamp, and conversion source to ensure auditability.
* **Aggregation Isolation**: Aggregations across multiple plants must explicitly declare target normalization currency; cross-currency sums without explicit exchange rates are strictly rejected.

---

## 🔌 4. API Reference Summary

### Analyze Financial Impact
`POST /api/v3/financial-impact/analyze`
* **Request Payload**:
  ```json
  {
    "source_entity_id": "line_03_stamping",
    "incident_id": "inc_9921b",
    "category": "DOWNTIME_LOSS",
    "evidence": [
      {
        "evidence_type": "DOWNTIME_HOURS",
        "value": 14.5,
        "source": "sensor_fusion_assessment"
      }
    ],
    "assumptions": [
      {
        "name": "line_downtime_hourly_cost",
        "value": 3200.0,
        "currency": "USD",
        "provenance": "finance_erp_standard_costing"
      }
    ]
  }
  ```
* **Response**:
  ```json
  {
    "assessment_id": "fin_4402a1",
    "status": "CALCULATED",
    "base_exposure": 46400.00,
    "currency": "USD",
    "confidence": 0.94,
    "range": {
      "best_case": 41760.00,
      "worst_case": 53360.00
    },
    "provenance_hash": "a8f3c1b..."
  }
  ```

### Retrieve Financial Impact Assessment
`GET /api/v3/financial-impact/{assessment_id}`
Returns complete breakdown of assumptions, evidence items, and sensitivity curves.

### Financial Exposure Summary
`GET /api/v3/financial-impact/summary?limit=50`
Returns top enterprise operational risks ranked by total projected financial loss.
