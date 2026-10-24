# 🔄 SageCommand V3 — Closed-Loop Outcome Evaluation Specification

> **System**: SageCommand V3 Enterprise Autonomous & Operational Intelligence OS  
> **Status**: Production Release (V3.0)  
> **Service Implementation**: [backend/services/outcome_evaluation_service.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/services/outcome_evaluation_service.py)  
> **Event Handler**: [backend/services/outcome_learning_event_handler.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/services/outcome_learning_event_handler.py)  
> **API Routes**: [backend/api/outcome_learning_routes.py](file:///c:/Users/Joyab/Downloads/SageCommand_Production/backend/api/outcome_learning_routes.py)  

---

## 📌 1. Subsystem Overview & Architectural Purpose

In traditional automated industrial systems, an agent considers its job complete once a write command is committed to the database. In SageCommand V3, execution marks only the midpoint of the operational lifecycle.

The **Closed-Loop Outcome Evaluation Service** establishes true continuous machine learning without physical risk. It compares:
1. **Pre-Execution Baseline State**: The initial operational conditions prior to action execution.
2. **Predicted / Expected Outcome**: The specific sensor targets and metric assertions formulated by the `Evaluator` node.
3. **Actual Post-Execution Telemetry**: Physical sensor measurements captured after execution across defined evaluation observation windows ($T_{\text{post}} \in [15\text{m}, 24\text{h}]$).

By comparing physical reality against predicted outcomes, the system detects metric drift, scores strategy efficacy, flags unintended side-effects, and recalibrates AI confidence weights for future decisions.

---

## 🔄 2. Event-Driven Outcome Learning Lifecycle

```mermaid
graph TD
    ExecGateway[Execution Gateway] -->|Action Committed| EvtBus[Internal Event Bus]
    EvtBus -->|EXECUTION_COMPLETED| VerifEngine[Continuous Verification Engine]
    VerifEngine -->|VERIFICATION_COMPLETED| EventHandler[Outcome Learning Event Handler]
    
    EventHandler --> OutcomeService[Outcome Evaluation Service]
    
    subgraph Outcome Evaluation Pipeline
        OutcomeService --> BaselineFetcher[Fetch Pre-Execution Telemetry Baseline]
        OutcomeService --> ActualSampler[Sample Post-Execution Sensor Windows]
        OutcomeService --> DriftCalculator[Calculate Metric Drift & Variance]
        OutcomeService --> EfficacyScorer[Compute Strategy Efficacy Score (0.0 - 1.0)]
        OutcomeService --> SideEffectDetector[Scan Downstream Nodes for Unintended Side Effects]
        OutcomeService --> ConfidenceTuner[Generate Model Calibration Recommendations]
    end

    ConfidenceTuner --> MemoryService[Organizational Memory Foundation]
    ConfidenceTuner --> DecisionEngine[Decision Engine Confidence Weights]
```

---

## 📐 3. Quantitative Evaluation Metrics

### 1. Normalized Metric Drift ($\Delta_{\text{drift}}$)
For each target sensor telemetry channel $k$, metric drift measures the deviation between expected value $E_k$ and observed post-execution value $O_k$, normalized by historical sensor standard deviation $\sigma_k$:

$$\Delta_{\text{drift}, k} = \frac{|O_k - E_k|}{\sigma_k}$$

* $\Delta_{\text{drift}} < 0.5\sigma$: **CONVERGED** (Predicted outcome matched physical reality).
* $0.5\sigma \le \Delta_{\text{drift}} \le 2.0\sigma$: **MODERATE DRIFT** (Tolerable variance; requires calibration tuning).
* $\Delta_{\text{drift}} > 2.0\sigma$: **CRITICAL DIVERGENCE** (Action failed to achieve intended physical response).

### 2. Strategy Efficacy Score ($S_{\text{efficacy}}$)
Evaluates overall success as a weighted composite of primary objective achievement and penalty factors for collateral disruption:

$$S_{\text{efficacy}} = w_{\text{primary}} \cdot P_{\text{target}} - \sum_j w_j \cdot C_j$$

Where:
* $P_{\text{target}} \in [0, 1]$ represents the percentage attainment of the primary operational goal.
* $C_j \in [0, 1]$ represents collateral side-effects (e.g., unintended temperature spikes or scrap increases).

### 3. Model Calibration & Confidence Recalibration
When a strategy consistently underperforms its predicted confidence score, the Outcome Evaluation service updates the Decision Engine's prior confidence distribution:

$$\text{Confidence}_{\text{new}} = \alpha \cdot \text{Confidence}_{\text{prior}} + (1 - \alpha) \cdot S_{\text{efficacy}}$$

This prevents the system from repeatedly selecting theoretically attractive strategies that fail to deliver in actual physical plant operations.

---

## 🔌 4. API Reference Summary

### Evaluate Action Outcome
`POST /api/v3/outcome-learning/evaluate`
* **Request Payload**:
  ```json
  {
    "action_id": "act_8841fa",
    "observation_window_seconds": 3600,
    "metrics_to_evaluate": [
      {
        "channel": "line_01.bearing_temperature_celsius",
        "expected_value": 68.0,
        "tolerance": 3.0
      }
    ]
  }
  ```
* **Response**:
  ```json
  {
    "evaluation_id": "eval_99120a",
    "action_id": "act_8841fa",
    "status": "COMPLETED",
    "efficacy_score": 0.92,
    "drift_assessment": "CONVERGED",
    "side_effects_detected": false,
    "confidence_adjustment": "+0.04",
    "timestamp": "2026-10-24T10:30:00Z"
  }
  ```

### List Historical Outcome Evaluations
`GET /api/v3/outcome-learning/evaluations?limit=50`
Returns paginated list of past evaluations filtered by plant ID, action type, and efficacy score.

### Retrieve Model Calibration Insights
`GET /api/v3/outcome-learning/insights`
Returns aggregate drift trends, model accuracy curves, and strategy ranking recommendations.
