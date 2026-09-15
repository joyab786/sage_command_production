# SAGECOMMAND OS V3 — INDUSTRIAL ONTOLOGY FOUNDATION
## Canonical Semantic Truth and Identity Layer

---

## 1. ARCHITECTURAL OVERVIEW

The **Industrial Ontology Foundation** establishes the canonical semantic backbone for **SageCommand OS V3**. It provides a deterministic, tenant-isolated, queryable representation of industrial entities, assets, automation components, materials, operations, and organizational relationships across hybrid enterprise environments.

```
       +-------------------------------------------------------------+
       |                  Enterprise External Systems                |
       |             [MES]    [SCADA]    [ERP]    [SAP]    [WMS]     |
       +-------------------------------------------------------------+
                                      |
                                      | External Identity Mappings
                                      v
+---------------------------------------------------------------------------+
|               INDUSTRIAL ONTOLOGY FOUNDATION (V3 Domain Layer)            |
|                                                                           |
|   +-------------------+  +----------------------+  +------------------+   |
|   |  Entity Taxonomy  |  | Relationship Engine  |  | Identity Mapper  |   |
|   |    (25 Types)     |  |    (16 Types + CM)   |  | (MES, SCADA, SAP)|   |
|   +-------------------+  +----------------------+  +------------------+   |
|   +-------------------+  +----------------------+  +------------------+   |
|   | Lifecycle State   |  | Version Snapshotting |  | Tenant Isolation |   |
|   | Machine (Guards)  |  |  & Audit Provenance  |  |  (RLS & Indexes) |   |
|   +-------------------+  +----------------------+  +------------------+   |
+---------------------------------------------------------------------------+
                                      |
                           Strict Isolation Barrier
                      [Zero Execution Gateway Bypass]
                                      v
+---------------------------------------------------------------------------+
|              SAGECOMMAND V3 EXECUTION & STORAGE BOUNDARY                  |
|     (Execution Gateway, Transaction Logs, Session-Scoped Databases)       |
+---------------------------------------------------------------------------+
```

### Cardinal Architectural Invariant
> **The Industrial Ontology is purely a semantic truth and identity layer, NOT an operational execution layer.**
> 
> * The Ontology Service has **zero execution attributes** (`execute`, `execute_action`, `execute_transaction`).
> * Registering, querying, updating, or relating ontology entities **never executes operational mutations**.
> * Operational mutations (inventory deductions, setpoint adjustments, emergency stops) remain exclusively bounded by the **Prompt 10 V3 Execution Gateway**.

---

## 2. CANONICAL ENTITY TAXONOMY

The ontology defines **25 canonical industrial entity types** grouped into six functional domains:

| Domain | EntityType | Description |
| :--- | :--- | :--- |
| **Enterprise & Spatial Hierarchy** | `ENTERPRISE` | Top-level corporate or organizational conglomerate. |
| | `SITE` | Geographic industrial campus or physical facility. |
| | `PLANT` | Individual manufacturing or processing plant. |
| | `PRODUCTION_LINE` | End-to-end assembly or processing line within a plant. |
| | `WORK_CELL` | Localized functional cell or automated station. |
| | `WORK_STATION` | Specific operator or robotic work station. |
| **Industrial Assets & Machinery** | `MACHINE` | Heavy industrial machine (e.g. stamping press, CNC mill). |
| | `EQUIPMENT` | Auxiliary or support industrial equipment (e.g. chillers, pumps). |
| | `ROBOT` | Articulated robotic arm, AGV, or automated gantry. |
| | `TOOL` | Cutting tool, die, mold, or exchangeable end-effector. |
| **Industrial Automation & OT** | `PLC` | Programmable Logic Controller. |
| | `CONTROLLER` | Microcontroller, PAC, or PID loop controller. |
| | `SENSOR` | Telemetry source (vibration, temperature, pressure, vision). |
| | `ACTUATOR` | Physical actuator (valve, servo motor, hydraulic cylinder). |
| **Logistics & Inventory** | `WAREHOUSE` | Raw material, WIP, or finished goods warehouse. |
| | `STORAGE_LOCATION` | Specific bin, rack, or shelf storage location. |
| | `INVENTORY_ITEM` | Tracked stock item, SKU, or consumable part. |
| | `PRODUCT` | Finished product manufactured by the enterprise. |
| | `MATERIAL` | Raw feedstock or bulk chemical/alloy material. |
| | `COMPONENT` | Sub-assembly or piece part used in product construction. |
| **Operational & Governance** | `BATCH` | Specific production run or chemical batch. |
| | `WORK_ORDER` | Scheduled maintenance or manufacturing job. |
| | `OPERATION` | Step or recipe segment within a manufacturing process. |
| **Personnel & Organization** | `OPERATOR` | Plant floor technician, machinist, or maintenance worker. |
| | `ORGANIZATION` | Department, shift crew, or operational business unit. |

---

## 3. CANONICAL RELATIONSHIP VOCABULARY & COMPATIBILITY MATRIX

Entities are linked through **16 strongly-typed, directional semantic relationships**. Every relationship is validated against a deterministic **Compatibility Matrix** before creation.

### Relationship Vocabulary

| RelationshipType | Inverse Concept | Description |
| :--- | :--- | :--- |
| `PART_OF` | `CONTAINS` | Hierarchical composition (e.g. WorkCell `PART_OF` Line). |
| `CONTAINS` | `PART_OF` | Parent container enclosing a child entity. |
| `LOCATED_AT` | `HOSTS` | Spatial location of an asset within a facility. |
| `FEEDS` | `FED_BY` | Material or sequential process flow between assets. |
| `MONITORS` | `MONITORED_BY` | Sensor or agent observing asset/process telemetry. |
| `CONTROLS` | `CONTROLLED_BY` | Controller or actuator adjusting equipment states. |
| `DEPENDS_ON` | `DEPENDENCY_OF` | Operational prerequisite between entities. |
| `USES_TOOL` | `TOOL_USED_BY` | Machine or robot utilizing a specific tool. |
| `CONSUMES` | `CONSUMED_BY` | Machine or operation consuming materials or components. |
| `PRODUCES` | `PRODUCED_BY` | Machine or line manufacturing finished goods. |
| `OPERATES` | `OPERATED_BY` | Human operator assigned to machinery or work cell. |
| `MAINTAINS` | `MAINTAINED_BY` | Technician or crew responsible for equipment upkeep. |
| `HAS_SENSOR` | `SENSOR_OF` | Physical integration of sensor on a machine. |
| `HAS_ACTUATOR` | `ACTUATOR_OF` | Physical integration of actuator on equipment. |
| `STORES` | `STORED_AT` | Warehouse or location storing inventory items. |
| `ASSOCIATED_WITH`| `ASSOCIATED_WITH`| General associative contextual binding. |

### Compatibility Enforcement
Attempting to create an edge between incompatible types (e.g. `CUSTOMER` -> `HAS_SENSOR` -> `SENSOR` or `INVENTORY_ITEM` -> `FEEDS` -> `SITE`) is rejected with `RELATIONSHIP_INCOMPATIBLE` (HTTP 400).

---

## 4. EXTERNAL IDENTITY RESOLUTION & CONFLICT MANAGEMENT

In brownfield industrial environments, machines and materials are identified across fragmented systems:
- **MES**: `MCH-007`
- **SCADA**: `PRESS_LINE_1`
- **SAP / ERP**: `MAT-90021-X`
- **WMS**: `LOC-B4-R2`

### External ID Lookup
`GET /api/v3/ontology/lookup?system=MES&external_id=MCH-007` resolves the system-specific identifier to its canonical URN (e.g. `machine:plant_mumbai:hydraulic_stamping_press_01`).

### Conflict Detection & Safety State
If an incoming external mapping attempts to map an external identifier that is already bound to a *different* canonical entity within the tenant:
1. The target entity's lifecycle state transitions immediately to `CONFLICT`.
2. A detailed security audit log is emitted (`EXTERNAL_ID_CONFLICT`).
3. The registration is rejected with HTTP 400 and `EXTERNAL_ID_CONFLICT`.
4. The system prevents dual-identity corruption.

---

## 5. ENTITY LIFECYCLE STATE MACHINE

Entities follow guarded lifecycle states to enforce industrial compliance:

```
                  +-----------+
                  |   DRAFT   |
                  +-----+-----+
                        |
                        v
     +------------> +--------+ <------------+
     |              | ACTIVE |              |
     |              +---+----+              |
     |                  |                   |
     v                  v                   v
+----+-------+   +------+-----+      +------+-----+
|MAINTENANCE |   | DEPRECATED |      |   FAULT    |
+------------+   +------+-----+      +------------+
                        |
                        v
                 +------+-----+
                 |  ARCHIVED  |
                 +------------+
```

* Any state may transition to `CONFLICT` upon identity collisions.
* Decommissioned (`ARCHIVED`) entities cannot transition back to `ACTIVE` without formal revision.
* Invalid transitions (e.g. `ARCHIVED` -> `ACTIVE`) raise `INVALID_LIFECYCLE_TRANSITION` (HTTP 400).

---

## 6. MULTI-TENANT REPOSITORY ARCHITECTURE

The persistent storage layer is implemented in `SQLiteOntologyRepository` with strict multi-tenant isolation:

```sql
-- 4 Core Normalized Tables
ontology_entities
ontology_external_ids
ontology_relationships
ontology_entity_versions
```

### Isolation Guarantees:
1. **Tenant ID Primary Partitioning**: Every table indexes `(tenant_id, ...)` as the leading column.
2. **Server-Authoritative JWT Enforcement**: All queries take `identity.tenant_id` from the cryptographically verified JWT token. Caller parameters cannot override tenant scope.
3. **Cross-Tenant Relationships Blocked**: If an edge attempts to link an entity from Tenant A to Tenant B, the relationship creation fails closed with `SOURCE_ENTITY_NOT_FOUND` or `TARGET_ENTITY_NOT_FOUND`.
4. **Historical Snapshots**: Updates automatically write the prior state into `ontology_entity_versions` for immutable audit provenance.

---

## 7. REST API SURFACE

The ontology exposes a comprehensive REST surface under `/api/v3/ontology`:

| Method | Endpoint | Permission | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/taxonomy` | `ontology.read` | Retrieves full taxonomies and compatibility matrix. |
| `GET` | `/entities` | `ontology.read` | Paginated listing of entities scoped to tenant. |
| `POST` | `/entities` | `ontology.manage` | Creates a new canonical entity. |
| `GET` | `/entities/{id}` | `ontology.read` | Retrieves entity metadata and external mappings. |
| `PUT` | `/entities/{id}` | `ontology.manage` | Updates entity attributes, metadata, or status. |
| `DELETE` | `/entities/{id}` | `ontology.manage` | Deletes entity and cascaded relationships. |
| `GET` | `/entities/{id}/relationships` | `ontology.read` | Lists relationship edges connected to entity. |
| `POST` | `/relationships` | `ontology.manage` | Creates relationship edge with compatibility check. |
| `DELETE` | `/relationships/{id}` | `ontology.manage` | Deletes relationship edge within tenant. |
| `GET` | `/lookup` | `ontology.read` | Resolves external system identifier to canonical entity. |
| `POST` | `/mappings` | `ontology.manage` | Binds external system ID to entity (with conflict guard). |

---

## 8. FRONTEND INSPECTION MODAL

A minimal, read-only **Ontology Inspection Modal** is integrated into the Next.js header (`OmniHeader.tsx` -> `OntologyModal.tsx`).
- **Entity Browser**: Searchable list filtered by `EntityType`.
- **Entity Inspector**: Displays canonical URN, display name, plant, lifecycle status pill, attributes, and external ID mappings.
- **Relationship Visualizer**: Lists connected upstream and downstream edges with confidence indicators.
- **Strict Read-Only**: The UI does not provide operational mutation buttons, adhering strictly to the cardinal invariant.
