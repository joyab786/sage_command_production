# SageCommand V3 — Data Quality Engine (Prompt 14)

## Architecture Overview
The **Data Quality Engine** is a critical architectural milestone in SageCommand V3. It provides deterministic, read-only evaluation of semantic data health across the Industrial Ontology, Knowledge Graph, and Digital Twin.

### Core Guiding Principles
1. **Zero Mutations:** The Data Quality Engine never mutates physical state, database records, or executes physical commands. It is strictly an assessment and reporting layer.
2. **Execution Isolation:** The system has zero dependency on the `ExecutionGateway` or `ActionStatus`. It operates entirely outside the command path.
3. **Strict Multi-Tenant Isolation:** All rules, issues, and assessments are partitioned by `tenant_id`. Cross-tenant data leakage is structurally impossible at the repository layer.
4. **Accuracy Strictness:** The accuracy of data is marked as `UNKNOWN` unless a verified, authoritative ground truth is available.

## 10 Quality Dimensions Evaluated
The engine evaluates data across the following 10 dimensions:
1. **Completeness:** Assesses whether required attributes (e.g., `canonical_name`) exist.
2. **Uniqueness:** Detects duplicate identifiers (`entity_id`, `canonical_name`) within a tenant space.
3. **Conformity:** Verifies adherence to the expected taxonomy and prevents invalid lifecycle states (e.g., `CONFLICT`).
4. **Integrity:** Identifies dangling or broken relational edges in the Industrial Ontology.
5. **Freshness:** Assesses staleness and expiration of the Digital Twin state properties.
6. **Validity:** Evaluates whether the digital twin state types map to known properties instead of `UNKNOWN`.
7. **Provenance:** Checks whether digital twin properties can be traced to an authoritative `source_id`.
8. **Consistency:** Searches for conflicting operational facts in the Knowledge Graph (e.g., multiple contradicting `OPERATES_AT` facts).
9. **Accuracy:** Measures adherence to a ground truth (defaults to UNKNOWN).
10. **Coverage:** Computes the ratio of measured entities versus expected population.

## Implementation Details
* **Services:** `DataQualityService` handles evaluation logic. `DataQualityRepository` persists `QualityRule`, `QualityIssue`, and `AssessmentRun` records in a partitioned SQLite store.
* **Contracts:** Foundational models defined in `data_quality_contract.py`.
* **Testing:** V3 Data Quality tests are defined in `test_v3_data_quality.py`, validating the rules, the scope mapping, and strict isolation metrics (including an explicit check to ensure `ExecutionGateway` is not imported).
