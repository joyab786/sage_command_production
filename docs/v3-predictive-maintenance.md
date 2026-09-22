# Predictive Maintenance Intelligence Foundation

## Overview
The Predictive Maintenance Intelligence Foundation in SageCommand V3 is a deterministic, read-only analytical layer.
It synthesizes telemetry, anomaly history, data quality metrics, and digital twin state to produce a robust maintenance risk assessment for industrial assets.

## Core Features
1. **Deterministic Fingerprinting**: Guaranteed reproducible assessments based on input signals.
2. **Contextual Integration**: Consumes signals from Data Quality, Anomaly Engine, and Digital Twin subsystems.
3. **Strict Isolation**: 
   - Uses dedicated SQLite persistence (`pm_assessments`).
   - Implements multi-tenant and workspace/plant authorization constraints.
   - **No execution boundaries**: Generates strictly non-executable `MaintenanceRecommendation` objects.

## API Endpoints
- `POST /v3/predictive-maintenance/analyze`: Triggers a risk assessment for an asset.
- `GET /v3/predictive-maintenance/assessment/{id}`: Retrieves a cached assessment.
- `GET /v3/predictive-maintenance/assessments`: Lists assessments for the current tenant.

## Schema Highlights
- `MaintenanceRiskAssessment`: Contains `risk_score`, `health_score`, `degradation_score`, and `confidence`.
- `MaintenanceEvidence`: Evidence records indicating *why* an asset's risk score was elevated (e.g., `ANOMALY_RECURRENCE`).
- `MaintenanceRecommendation`: Evidence-backed suggestions with a strict `executable=False` invariant.
