# SageCommand V3: Blast-Radius Intelligence Foundation

## Overview
The Blast-Radius Intelligence Foundation provides a deterministic, evidence-backed mechanism for estimating the potential impact spread of an operational entity, anomaly, incident, failure, or condition across the Operational Knowledge Graph. 

It answers the critical operational question: *"If this entity is compromised, what other assets, processes, areas, and dependencies may be affected or exposed?"*

## Cardinal Invariants
1. **Purely Analytical**: This is strictly an analytical intelligence layer.
2. **No Physical Mutation**: It must NEVER execute remediation, approve actions, create executable actions, or mutate physical systems.
3. **No Execution Gateway Bypass**: It does not make autonomous operational decisions.
4. **Estimated Scope**: The output represents the *potential/estimated* blast radius, not guaranteed physical impact.
5. **Evidence-Backed**: Every conclusion retains evidence, scope, confidence, uncertainty, and provenance.

## Core Domain Model (`BlastRadiusAnalysis`)
The schema strictly models impact without leaking execution components.

### 1. `ImpactNode`
Represents an entity affected within the blast radius.
- `impact_classification`: `DIRECT`, `UPSTREAM`, or `DOWNSTREAM`
- `impact_score`: Deterministic decay score (0.0 to 100.0) based on distance
- `confidence`: Assessment of certainty (`HIGH`, `MEDIUM`, `LOW`, `INSUFFICIENT_DATA`)
- `distance`: Dependency depth from the source
- `evidence_refs`: Traceable provenance back to Knowledge Graph facts

### 2. `ImpactPath`
Represents the structural edge propagation.
- `ordered_path`: Ordered list of entity IDs forming the traversal path.
- `relationship_types`: Ontology edges traversed (`FEEDS_INTO`, `CONTROLS`, etc.)
- `traversal_depth`: Distance mapping.
- `evidence_refs`: Traceable provenance to the structural relationships.

### 3. `ImpactScope`
A rollup of the blast radius spread.
- Aggregates the total number of affected assets, processes, areas, plants, and dependencies.

## Engine Implementation (`BlastRadiusService`)
The traversal relies on a bounded Breadth-First Search (BFS) over the Operational Knowledge Graph. 

### Limits & Configuration
- **`SAGE_BLAST_RADIUS_MAX_DEPTH`** (Default: 5): Caps the maximum dependency depth.
- **`SAGE_BLAST_RADIUS_MAX_NODES`** (Default: 200): Limits excessive graph expansions to prevent denial-of-service.
- **`SAGE_BLAST_RADIUS_MAX_PATHS`** (Default: 1000): Caps stored impact paths.

### Caching and Fingerprinting
Blast-radius computations are highly deterministic. Each request generates a SHA-256 `input_fingerprint` encompassing the source entity and timestamp context. 
If an identical request has already been computed, the engine immediately serves the cached `BlastRadiusAnalysis` from the `BlastRadiusRepository`.

## Persistence (`BlastRadiusRepository`)
Persists analyses into a dedicated SQLite database (`sage_blast_radius.sqlite`).
- Enforces strict **Multi-Tenant Isolation** (`tenant_id`).
- Implements **WAL Mode** for concurrent read/write scalability.

## Authorization
- Endpoints are gated by standard ABAC/RBAC mechanisms.
- Requires `blast_radius.read` or `blast_radius.analyze` permissions.

## Testing & Regression
The implementation achieves standard test requirements:
- Bounded BFS traversal validation.
- Max depth cutoff enforcement.
- Deterministic caching hits.
- Tenant isolation.
- Complete independence from mutations/LLM operations.
