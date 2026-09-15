# SageCommand V3 — Real Anomaly Detection Engine

The **Real Anomaly Detection Engine** (Prompt 15) is a core component of the SAGE Command V3 architecture. It is responsible for identifying abnormal conditions within the industrial environment using deterministic mathematical models.

## Architectural Boundaries (Strict Constraints)

1. **Observational Only**: This engine only detects and flags anomalies based on data observations. It performs ZERO operational mutations.
2. **Execution Isolation**: The engine is strictly isolated from the `ExecutionGateway`. It cannot execute physical commands, trigger safety systems, or perform remediation.
3. **Determinism**: Unlike predictive AI (which is restricted in V3), this engine uses verifiable, reproducible mathematical models (Z-Score, MAD, IQR, Rate of Change) to determine anomalies. LLMs are NOT authoritative in the detection pipeline.
4. **Tenant Isolation**: All baselines, assessments, and anomaly states are rigidly partitioned by `tenant_id`.

## Detection Methods

The engine evaluates data against established `AnomalyBaseline` definitions using one of the following methods:

### Z-Score (Standard Deviation)
Measures the distance of a point from the mean in units of standard deviation. 
- **Requirement**: Normal distribution, $\ge$ 30 valid samples.
- **Formula**: $Z = \frac{|X - \mu|}{\sigma}$

### MAD (Median Absolute Deviation)
A robust version of Z-Score, resilient to extreme outliers.
- **Requirement**: $\ge$ 15 valid samples.
- **Formula**: $RobustZ = \frac{0.6745 \times |X - \text{median}|}{MAD}$

### IQR (Interquartile Range)
Identifies anomalies lying outside the bounds calculated via quartiles.
- **Requirement**: $\ge$ 10 valid samples.
- **Formula**: $[Q_1 - k(IQR), Q_3 + k(IQR)]$

### Rate of Change
Detects rapid sequential variations (absolute delta or percentage).
- **Requirement**: $\ge$ 2 valid samples.

## Integration with V3 Systems

- **Data Quality (Prompt 14)**: The anomaly engine silently ignores points flagged with `LOW` confidence (or explicitly marked invalid) by the Data Quality service.
- **Digital Twin (Prompt 13)**: The engine extracts `TwinStateProperty` values for assessment.
- **Knowledge Graph (Prompt 12) & Ontology (Prompt 11)**: Provides semantic context and entity resolution for the baseline scopes.

## API Endpoints

- `GET /api/v3/anomalies`: List detected anomalies within the tenant scope.
- `GET /api/v3/anomalies/baselines`: Retrieve configured baselines.
- `POST /api/v3/anomalies/detect`: Execute a targeted detection run across a defined scope.

## Persistence

Data is isolated locally in `v3_anomaly_db.sqlite` during development, utilizing the `AnomalyRepository`. Detections are deterministically deduplicated via SHA-256 fingerprinting (incorporating tenant, entity, metric, method, context, and version) to prevent database spamming during sustained anomalies.
