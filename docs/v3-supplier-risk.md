# SageCommand V3 — Supplier Risk Intelligence Foundation

## Overview
Supplier Risk Intelligence is a deterministic, analytical-only subsystem within SageCommand V3. It evaluates supplier operational reliability by aggregating data across delivery, quality, capacity disruption, and dependency contexts.

**Crucial Constraint**: Supplier Risk is strictly analytical. It has absolutely no execution authority. It does not import, reference, or use the `ExecutionGateway` or the `Action API`. It cannot create purchase orders, modify inventory, or actuate physical systems. It can only generate risk assessments, which are then read by humans or other services to inform decision-making.

## Risk Factors

The foundation evaluates the following core risk factors:

1. **Delivery Reliability**: Calculated deterministically based on the ratio of late deliveries to total deliveries within the evaluation window.
2. **Quality Risk**: Calculated based on the defect rate from quality inspections and incident data.
3. **Capacity Disruption**: Driven by the severity and frequency of supply shortfalls or disruptions recorded in the incident management system.
4. **Concentration / Dependency**: Measures the exposure risk. If a supplier is a single-source for critical components or affects multiple plants concurrently, the dependency risk score increases.

## Architecture

* **Service Layer (`supplier_risk_service.py`)**: Implements the deterministic evaluation engine. It aggregates historical observations and calculates the weighted risk score and overall status (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
* **Repository (`supplier_risk_repository.py`)**: Uses SQLite in WAL mode. Employs a strict JSON payload structure isolating assessments by `tenant_id`, `workspace_id`, and `plant_id`.
* **API Routes (`supplier_risk_routes.py`)**: Exposes REST endpoints protected by strict RBAC (`supplier_risk.analyze`, `supplier_risk.read`, `supplier_risk.history`).
* **Contract (`supplier_risk_contract.py`)**: Pydantic v2 schemas detailing the exact structure of an assessment, the risk factors, the evidence array, and analytical observations. Includes a cryptographic input fingerprint to ensure idempotency.

## Determinism and Fingerprinting
To prevent drift and ensure audibility, every assessment produces an `input_fingerprint` (SHA-256). This fingerprint is generated based on the canonical inputs (supplier, timestamp, calculated factors, and evidence). If the identical inputs are evaluated twice, the same fingerprint is generated, and the repository will return the existing assessment rather than duplicating it.

## Temporal Boundaries
The service rigorously enforces the `as_of_timestamp`. Any operational observation that occurs *after* this timestamp is deterministically ignored. This prevents temporal leakage and ensures historical accuracy of the assessments. Data lacking timestamps or containing malformed dates are flagged as data quality issues and excluded from the calculation.
