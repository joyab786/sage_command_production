# SageCommand V3: Demand Forecasting Intelligence Foundation

## Architectural Tenets

The Demand Forecasting Intelligence Foundation (Prompt 22) represents the analytical prediction layer of SageCommand V3. It predicts future operational demand based on historical observations, providing rigorous statistical context, uncertainty quantification, and deterministic boundaries.

**Strictly Analytical**: Demand Forecasting has NO operational execution authority. It produces analytical output (demand curves, bound trajectories, evidence records) and must NEVER mutate the factory floor, procurement, inventory levels, or trigger Execution Gateway workflows. 

## Determinism & Model Provenance

To maintain explainability and auditability:
- Numerical forecasts are generated using deterministic statistical models (Naïve, Moving Average, Trend Adjusted).
- No LLMs or non-deterministic AI models are used for the actual generation of forecast data points.
- Every forecast point includes a calculated lower bound, upper bound, and explicit confidence level.
- Every forecast payload includes an `input_fingerprint` uniquely identifying the historical observation set used to produce it, ensuring caching and reproducible evaluations.
- Forecast objects include explicit `method_selected`, `trend_context`, and `provenance` metadata.

## Core Capabilities

1. **Horizon Prediction**: Supports `SHORT_TERM` (1 week), `MEDIUM_TERM` (1 month), and `LONG_TERM` (1 quarter) forecasting horizons.
2. **Granular Modeling**: Supports `HOURLY`, `DAILY`, and `WEEKLY` granularity.
3. **Data Quality Integration**: Contextualizes forecasts with `data_quality_score` and `anomalies_considered` from the Data Quality engine.
4. **Historical Backtesting (Evaluation)**: Provides `/api/v3/demand-forecasting/evaluate` to systematically compare past forecasts against actual realized observations, measuring MAE, RMSE, and BIAS.

## Implementation Details

### API Routes

| Method | Route | Description | Required Permission |
| --- | --- | --- | --- |
| `POST` | `/api/v3/demand-forecasting/forecast` | Generate a new forecast based on historical observations | `demand_forecasting.analyze` |
| `GET` | `/api/v3/demand-forecasting/forecast/{id}` | Retrieve a specific historical forecast | `demand_forecasting.read` |
| `GET` | `/api/v3/demand-forecasting/forecasts` | List all historical forecasts | `demand_forecasting.read` |
| `POST` | `/api/v3/demand-forecasting/evaluate` | Evaluate a past forecast against actuals | `demand_forecasting.evaluate` |

### Database Layer

Uses SQLite with WAL mode (`demand_forecasts_v3`, `demand_forecast_evaluations_v3`). Fingerprinting provides fast deductive lookups.

## Security & Authorization

Managed via `authorization_service.py`:
- `demand_forecasting.read`: VIEWER role
- `demand_forecasting.analyze`, `demand_forecasting.evaluate`: ANALYST role
- `demand_forecasting.admin`: ADMINISTRATOR, SECURITY_ADMIN roles

All operations mandate explicit tenant isolation validation.
