# backend/data/schemas/ontology_contract.py
"""
SageCommand V3 — Industrial Ontology Canonical Domain Contracts
Defines canonical semantic models, entity taxonomies, relationship vocabularies,
compatibility verification matrices, external identity mappings, lifecycle states,
and API request/response envelopes.

Cardinal Architectural Invariant:
The Industrial Ontology is a semantic truth and identity layer, not an operational execution layer.
It must never perform physical machine, inventory, or database state mutations.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re
import uuid


# =====================================================================
# 1. CONTROLLED ENTITY TYPE TAXONOMY
# =====================================================================

class EntityType(str, Enum):
    """
    Controlled vocabulary for industrial entities across discrete,
    process, and hybrid manufacturing domains.
    """
    # Enterprise & Facility Hierarchy
    ORGANIZATION = "ORGANIZATION"          # Enterprise or corporate legal entity
    PLANT = "PLANT"                        # Manufacturing or processing facility
    SITE = "SITE"                          # Physical geographical site or campus
    PRODUCTION_LINE = "PRODUCTION_LINE"    # Continuous or sequenced production line
    WORK_CELL = "WORK_CELL"                # Integrated group of machinery/stations
    
    # Equipment & Machinery
    MACHINE = "MACHINE"                    # Industrial machine (press, mill, lathe, etc.)
    EQUIPMENT = "EQUIPMENT"                # Ancillary industrial equipment (pump, conveyor, chiller)
    ROBOT = "ROBOT"                        # Industrial robotic arm, gantry, or AGV/AMR
    
    # Automation & Control Devices
    PLC = "PLC"                            # Programmable Logic Controller
    CONTROLLER = "CONTROLLER"              # PAC, CNC, DCS controller, or edge IPC
    SENSOR = "SENSOR"                      # Industrial sensor (temperature, vibration, pressure)
    ACTUATOR = "ACTUATOR"                  # Industrial actuator (valve, servo, solenoid)
    
    # Logistics & Storage
    WAREHOUSE = "WAREHOUSE"                # Storage or distribution warehouse facility
    STORAGE_LOCATION = "STORAGE_LOCATION"  # Bin, rack, tank, silo, or bay
    INVENTORY = "INVENTORY"                # Aggregate inventory pool or ledger
    INVENTORY_ITEM = "INVENTORY_ITEM"      # Discrete inventory item record
    
    # Products & Materials
    PRODUCT = "PRODUCT"                    # Finished good or sellable article
    MATERIAL = "MATERIAL"                  # Raw material or feedstock
    COMPONENT = "COMPONENT"                # Sub-assembly or intermediate component
    
    # Supply Chain & Business Partners
    SUPPLIER = "SUPPLIER"                  # Material, part, or equipment vendor
    CUSTOMER = "CUSTOMER"                  # Client or downstream purchaser
    
    # Operations & Governance
    WORK_ORDER = "WORK_ORDER"              # Production manufacturing order
    MAINTENANCE_ORDER = "MAINTENANCE_ORDER"# Preventive or corrective work order
    OPERATOR = "OPERATOR"                  # Human technician, machinist, or supervisor
    
    # Utilities & Resources
    ENERGY_RESOURCE = "ENERGY_RESOURCE"    # Power grid feed, generator, or solar bank
    UTILITY = "UTILITY"                    # Compressed air, steam, coolant, water feed


# =====================================================================
# 2. ENTITY LIFECYCLE & STATE TRANSITIONS
# =====================================================================

class EntityLifecycleState(str, Enum):
    """
    Deterministic lifecycle states for industrial entities.
    Distinguishes non-existence from inactive/decommissioned states.
    """
    DISCOVERED = "DISCOVERED"          # Identified via scan, telemetry, or import; pending verification
    ACTIVE = "ACTIVE"                  # Fully verified, commissioned, and operational in semantic model
    INACTIVE = "INACTIVE"              # Temporarily offline, suspended, or unmonitored
    DECOMMISSIONED = "DECOMMISSIONED"  # Permanently removed from service / retired
    ARCHIVED = "ARCHIVED"              # Historical record retained for compliance/audit only
    CONFLICT = "CONFLICT"              # Ambiguous mapping or contradictory external identity detected
    UNKNOWN = "UNKNOWN"                # Unspecified or unresolvable lifecycle status


# Guarded deterministic lifecycle transition map
VALID_LIFECYCLE_TRANSITIONS: Dict[EntityLifecycleState, set] = {
    EntityLifecycleState.DISCOVERED: {
        EntityLifecycleState.ACTIVE,
        EntityLifecycleState.CONFLICT,
        EntityLifecycleState.ARCHIVED,
        EntityLifecycleState.INACTIVE,
    },
    EntityLifecycleState.ACTIVE: {
        EntityLifecycleState.INACTIVE,
        EntityLifecycleState.DECOMMISSIONED,
        EntityLifecycleState.CONFLICT,
        EntityLifecycleState.ARCHIVED,
    },
    EntityLifecycleState.INACTIVE: {
        EntityLifecycleState.ACTIVE,
        EntityLifecycleState.DECOMMISSIONED,
        EntityLifecycleState.ARCHIVED,
    },
    EntityLifecycleState.DECOMMISSIONED: {
        EntityLifecycleState.ARCHIVED,
    },
    EntityLifecycleState.ARCHIVED: {
        EntityLifecycleState.ACTIVE,  # Reactivation allowed only via explicit administrative action
    },
    EntityLifecycleState.CONFLICT: {
        EntityLifecycleState.ACTIVE,  # Resolved
        EntityLifecycleState.INACTIVE,
        EntityLifecycleState.ARCHIVED,
    },
    EntityLifecycleState.UNKNOWN: {
        EntityLifecycleState.DISCOVERED,
        EntityLifecycleState.ACTIVE,
        EntityLifecycleState.ARCHIVED,
    },
}

def validate_lifecycle_transition(
    current_state: EntityLifecycleState,
    next_state: EntityLifecycleState
) -> bool:
    """Validates if a lifecycle transition is permitted by deterministic domain rules."""
    if current_state == next_state:
        return True
    allowed = VALID_LIFECYCLE_TRANSITIONS.get(current_state, set())
    return next_state in allowed


# =====================================================================
# 3. PROVENANCE & SOURCE VOCABULARY
# =====================================================================

class EntitySource(str, Enum):
    """Authoritative origin of an ontology entity or relationship."""
    MANUAL = "MANUAL"
    DATABASE = "DATABASE"
    MES = "MES"
    ERP = "ERP"
    SCADA = "SCADA"
    PLC = "PLC"
    SENSOR = "SENSOR"
    API = "API"
    IMPORT = "IMPORT"
    SIMULATOR = "SIMULATOR"
    DISCOVERY_AGENT = "DISCOVERY_AGENT"
    UNKNOWN = "UNKNOWN"


# =====================================================================
# 4. CONTROLLED RELATIONSHIP VOCABULARY
# =====================================================================

class RelationshipType(str, Enum):
    """
    Controlled semantic relationship types connecting industrial entities.
    Paired with inverse relationships where applicable.
    """
    # Containment & Hierarchy
    CONTAINS = "CONTAINS"
    PART_OF = "PART_OF"
    
    # Location & Placement
    LOCATED_AT = "LOCATED_AT"
    LOCATED_IN = "LOCATED_IN"
    
    # Control & Automation
    CONTROLS = "CONTROLS"
    CONTROLLED_BY = "CONTROLLED_BY"
    CONNECTED_TO = "CONNECTED_TO"
    
    # Sensors & Instrumentation
    HAS_SENSOR = "HAS_SENSOR"
    SENSOR_OF = "SENSOR_OF"
    
    # Actuation
    HAS_ACTUATOR = "HAS_ACTUATOR"
    ACTUATOR_OF = "ACTUATOR_OF"
    
    # Production & Consumption
    PRODUCES = "PRODUCES"
    PRODUCED_BY = "PRODUCED_BY"
    CONSUMES = "CONSUMES"
    CONSUMED_BY = "CONSUMED_BY"
    
    # Storage & Warehousing
    STORES = "STORES"
    STORED_IN = "STORED_IN"
    
    # Supply Chain
    SUPPLIES = "SUPPLIES"
    SUPPLIED_BY = "SUPPLIED_BY"
    
    # Usage & Dependencies
    USES = "USES"
    USED_BY = "USED_BY"
    DEPENDS_ON = "DEPENDS_ON"
    
    # Maintenance & Operations
    MAINTAINS = "MAINTAINS"
    MAINTAINED_BY = "MAINTAINED_BY"
    ASSIGNED_TO = "ASSIGNED_TO"
    OPERATES = "OPERATES"
    OPERATED_BY = "OPERATED_BY"


class RelationshipConfidence(str, Enum):
    """Confidence classification for relationships."""
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


# =====================================================================
# 5. DETERMINISTIC RELATIONSHIP COMPATIBILITY MATRIX
# =====================================================================

RELATIONSHIP_COMPATIBILITY: Dict[RelationshipType, Dict[str, set]] = {
    RelationshipType.CONTAINS: {
        "sources": {
            EntityType.ORGANIZATION, EntityType.SITE, EntityType.PLANT,
            EntityType.PRODUCTION_LINE, EntityType.WORK_CELL, EntityType.WAREHOUSE
        },
        "targets": {
            EntityType.SITE, EntityType.PLANT, EntityType.PRODUCTION_LINE,
            EntityType.WORK_CELL, EntityType.MACHINE, EntityType.EQUIPMENT,
            EntityType.ROBOT, EntityType.PLC, EntityType.CONTROLLER,
            EntityType.SENSOR, EntityType.ACTUATOR, EntityType.WAREHOUSE,
            EntityType.STORAGE_LOCATION, EntityType.ENERGY_RESOURCE, EntityType.UTILITY
        }
    },
    RelationshipType.PART_OF: {
        "sources": {
            EntityType.SITE, EntityType.PLANT, EntityType.PRODUCTION_LINE,
            EntityType.WORK_CELL, EntityType.MACHINE, EntityType.EQUIPMENT,
            EntityType.ROBOT, EntityType.PLC, EntityType.CONTROLLER,
            EntityType.SENSOR, EntityType.ACTUATOR, EntityType.WAREHOUSE,
            EntityType.STORAGE_LOCATION, EntityType.COMPONENT
        },
        "targets": {
            EntityType.ORGANIZATION, EntityType.SITE, EntityType.PLANT,
            EntityType.PRODUCTION_LINE, EntityType.WORK_CELL, EntityType.MACHINE,
            EntityType.PRODUCT, EntityType.WAREHOUSE
        }
    },
    RelationshipType.LOCATED_AT: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PLC, EntityType.CONTROLLER, EntityType.SENSOR,
            EntityType.ACTUATOR, EntityType.INVENTORY_ITEM, EntityType.PRODUCT,
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.OPERATOR
        },
        "targets": {
            EntityType.ORGANIZATION, EntityType.SITE, EntityType.PLANT,
            EntityType.PRODUCTION_LINE, EntityType.WORK_CELL, EntityType.WAREHOUSE,
            EntityType.STORAGE_LOCATION
        }
    },
    RelationshipType.LOCATED_IN: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PLC, EntityType.CONTROLLER, EntityType.SENSOR,
            EntityType.ACTUATOR, EntityType.INVENTORY_ITEM, EntityType.PRODUCT,
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.STORAGE_LOCATION
        },
        "targets": {
            EntityType.PLANT, EntityType.PRODUCTION_LINE, EntityType.WORK_CELL,
            EntityType.WAREHOUSE, EntityType.STORAGE_LOCATION
        }
    },
    RelationshipType.CONTROLS: {
        "sources": {
            EntityType.PLC, EntityType.CONTROLLER, EntityType.OPERATOR
        },
        "targets": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.ACTUATOR, EntityType.PRODUCTION_LINE, EntityType.WORK_CELL
        }
    },
    RelationshipType.CONTROLLED_BY: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.ACTUATOR, EntityType.PRODUCTION_LINE, EntityType.WORK_CELL
        },
        "targets": {
            EntityType.PLC, EntityType.CONTROLLER, EntityType.OPERATOR
        }
    },
    RelationshipType.CONNECTED_TO: {
        "sources": {
            EntityType.PLC, EntityType.CONTROLLER, EntityType.SENSOR,
            EntityType.ACTUATOR, EntityType.MACHINE, EntityType.EQUIPMENT,
            EntityType.ROBOT, EntityType.ENERGY_RESOURCE, EntityType.UTILITY
        },
        "targets": {
            EntityType.PLC, EntityType.CONTROLLER, EntityType.SENSOR,
            EntityType.ACTUATOR, EntityType.MACHINE, EntityType.EQUIPMENT,
            EntityType.ROBOT, EntityType.ENERGY_RESOURCE, EntityType.UTILITY
        }
    },
    RelationshipType.HAS_SENSOR: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PLC, EntityType.CONTROLLER, EntityType.PRODUCTION_LINE,
            EntityType.WORK_CELL, EntityType.STORAGE_LOCATION, EntityType.WAREHOUSE
        },
        "targets": {
            EntityType.SENSOR
        }
    },
    RelationshipType.SENSOR_OF: {
        "sources": {
            EntityType.SENSOR
        },
        "targets": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PLC, EntityType.CONTROLLER, EntityType.PRODUCTION_LINE,
            EntityType.WORK_CELL, EntityType.STORAGE_LOCATION, EntityType.WAREHOUSE
        }
    },
    RelationshipType.HAS_ACTUATOR: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PLC, EntityType.CONTROLLER
        },
        "targets": {
            EntityType.ACTUATOR
        }
    },
    RelationshipType.ACTUATOR_OF: {
        "sources": {
            EntityType.ACTUATOR
        },
        "targets": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PLC, EntityType.CONTROLLER
        }
    },
    RelationshipType.PRODUCES: {
        "sources": {
            EntityType.MACHINE, EntityType.PRODUCTION_LINE, EntityType.WORK_CELL,
            EntityType.PLANT
        },
        "targets": {
            EntityType.PRODUCT, EntityType.MATERIAL, EntityType.COMPONENT,
            EntityType.INVENTORY_ITEM
        }
    },
    RelationshipType.PRODUCED_BY: {
        "sources": {
            EntityType.PRODUCT, EntityType.MATERIAL, EntityType.COMPONENT,
            EntityType.INVENTORY_ITEM
        },
        "targets": {
            EntityType.MACHINE, EntityType.PRODUCTION_LINE, EntityType.WORK_CELL,
            EntityType.PLANT
        }
    },
    RelationshipType.CONSUMES: {
        "sources": {
            EntityType.MACHINE, EntityType.PRODUCTION_LINE, EntityType.WORK_CELL,
            EntityType.PLANT
        },
        "targets": {
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.ENERGY_RESOURCE,
            EntityType.UTILITY, EntityType.INVENTORY_ITEM
        }
    },
    RelationshipType.CONSUMED_BY: {
        "sources": {
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.ENERGY_RESOURCE,
            EntityType.UTILITY, EntityType.INVENTORY_ITEM
        },
        "targets": {
            EntityType.MACHINE, EntityType.PRODUCTION_LINE, EntityType.WORK_CELL,
            EntityType.PLANT
        }
    },
    RelationshipType.STORES: {
        "sources": {
            EntityType.WAREHOUSE, EntityType.STORAGE_LOCATION
        },
        "targets": {
            EntityType.INVENTORY, EntityType.INVENTORY_ITEM, EntityType.PRODUCT,
            EntityType.MATERIAL, EntityType.COMPONENT
        }
    },
    RelationshipType.STORED_IN: {
        "sources": {
            EntityType.INVENTORY, EntityType.INVENTORY_ITEM, EntityType.PRODUCT,
            EntityType.MATERIAL, EntityType.COMPONENT
        },
        "targets": {
            EntityType.WAREHOUSE, EntityType.STORAGE_LOCATION
        }
    },
    RelationshipType.SUPPLIES: {
        "sources": {
            EntityType.SUPPLIER
        },
        "targets": {
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.PRODUCT,
            EntityType.UTILITY, EntityType.ENERGY_RESOURCE, EntityType.EQUIPMENT,
            EntityType.MACHINE
        }
    },
    RelationshipType.SUPPLIED_BY: {
        "sources": {
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.PRODUCT,
            EntityType.UTILITY, EntityType.ENERGY_RESOURCE, EntityType.EQUIPMENT,
            EntityType.MACHINE
        },
        "targets": {
            EntityType.SUPPLIER
        }
    },
    RelationshipType.USES: {
        "sources": {
            EntityType.WORK_ORDER, EntityType.MAINTENANCE_ORDER
        },
        "targets": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.OPERATOR
        }
    },
    RelationshipType.USED_BY: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.MATERIAL, EntityType.COMPONENT, EntityType.OPERATOR
        },
        "targets": {
            EntityType.WORK_ORDER, EntityType.MAINTENANCE_ORDER
        }
    },
    RelationshipType.DEPENDS_ON: {
        "sources": {
            EntityType.PRODUCTION_LINE, EntityType.WORK_CELL, EntityType.MACHINE,
            EntityType.EQUIPMENT, EntityType.WORK_ORDER, EntityType.ROBOT
        },
        "targets": {
            EntityType.PRODUCTION_LINE, EntityType.MACHINE, EntityType.EQUIPMENT,
            EntityType.PLC, EntityType.CONTROLLER, EntityType.ENERGY_RESOURCE,
            EntityType.UTILITY, EntityType.MATERIAL, EntityType.WORK_ORDER
        }
    },
    RelationshipType.MAINTAINS: {
        "sources": {
            EntityType.OPERATOR, EntityType.MAINTENANCE_ORDER
        },
        "targets": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PRODUCTION_LINE, EntityType.PLC, EntityType.CONTROLLER,
            EntityType.SENSOR, EntityType.ACTUATOR
        }
    },
    RelationshipType.MAINTAINED_BY: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PRODUCTION_LINE, EntityType.PLC, EntityType.CONTROLLER,
            EntityType.SENSOR, EntityType.ACTUATOR
        },
        "targets": {
            EntityType.OPERATOR, EntityType.MAINTENANCE_ORDER
        }
    },
    RelationshipType.ASSIGNED_TO: {
        "sources": {
            EntityType.WORK_ORDER, EntityType.MAINTENANCE_ORDER
        },
        "targets": {
            EntityType.OPERATOR, EntityType.MACHINE, EntityType.PRODUCTION_LINE,
            EntityType.WORK_CELL
        }
    },
    RelationshipType.OPERATES: {
        "sources": {
            EntityType.OPERATOR
        },
        "targets": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PRODUCTION_LINE, EntityType.WORK_CELL
        }
    },
    RelationshipType.OPERATED_BY: {
        "sources": {
            EntityType.MACHINE, EntityType.EQUIPMENT, EntityType.ROBOT,
            EntityType.PRODUCTION_LINE, EntityType.WORK_CELL
        },
        "targets": {
            EntityType.OPERATOR
        }
    }
}

def validate_relationship_compatibility(
    source_type: EntityType,
    relationship_type: RelationshipType,
    target_type: EntityType
) -> Tuple[bool, Optional[str]]:
    """
    Deterministically verifies whether a relationship between two entity types is permitted.
    Returns (is_valid, error_message).
    """
    rule = RELATIONSHIP_COMPATIBILITY.get(relationship_type)
    if not rule:
        return False, f"Unknown or unmapped relationship type '{relationship_type.value}'."
    
    if source_type not in rule["sources"]:
        return False, (
            f"Invalid source entity type '{source_type.value}' for relationship '{relationship_type.value}'. "
            f"Permitted sources: {sorted([t.value for t in rule['sources']])}."
        )
        
    if target_type not in rule["targets"]:
        return False, (
            f"Invalid target entity type '{target_type.value}' for relationship '{relationship_type.value}'. "
            f"Permitted targets: {sorted([t.value for t in rule['targets']])}."
        )
        
    return True, None


# =====================================================================
# 6. CANONICAL ENTITY MODEL
# =====================================================================

class OntologyEntity(BaseModel):
    """
    Canonical Industrial Ontology Entity.
    Establishes semantic identity across heterogeneous external systems (SAP, MES, SCADA, PLC).
    """
    model_config = ConfigDict(extra="ignore")

    entity_id: str = Field(..., min_length=3, max_length=256, description="Canonical stable identifier")
    entity_type: EntityType = Field(..., description="Taxonomic classification")
    canonical_name: str = Field(..., min_length=1, max_length=256, description="Standardized system name")
    display_name: str = Field(..., min_length=1, max_length=256, description="Human-readable title")
    
    # Multi-tenant and spatial boundaries
    tenant_id: str = Field(..., min_length=1, max_length=128, description="Authoritative tenant isolation partition")
    workspace_id: str = Field(default="workspace_default", max_length=128, description="Workspace boundary")
    plant_id: Optional[str] = Field(default=None, max_length=128, description="Associated plant facility ID")
    
    # External system identity mapping: system -> external_id (e.g. {"SAP": "10007891", "MES": "MCH-007"})
    external_ids: Dict[str, str] = Field(default_factory=dict, description="External identifiers mapped to entity")
    
    # Arbitrary structured metadata & specifications
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Physical and technical specifications")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Operational tags and administrative metadata")
    
    # Lifecycle & Provenance
    status: EntityLifecycleState = Field(default=EntityLifecycleState.ACTIVE, description="Current lifecycle state")
    source: EntitySource = Field(default=EntitySource.MANUAL, description="Provenance origin of entity record")
    version: int = Field(default=1, ge=1, description="Sequential entity version")
    
    # Timestamps
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id_format(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[a-zA-Z0-9_\-\:\.]+$", v):
            raise ValueError(f"Invalid canonical entity ID '{v}': must contain only alphanumeric, '_', '-', ':', '.' characters.")
        return v


# =====================================================================
# 7. CANONICAL RELATIONSHIP MODEL
# =====================================================================

class OntologyRelationship(BaseModel):
    """
    Canonical Industrial Relationship Edge.
    Connects two entities within a tenant boundary using controlled semantic relationship types.
    """
    model_config = ConfigDict(extra="ignore")

    relationship_id: str = Field(default_factory=lambda: f"rel_{uuid.uuid4().hex[:12]}")
    relationship_type: RelationshipType = Field(..., description="Controlled relationship classification")
    source_entity_id: str = Field(..., description="Canonical ID of source entity")
    target_entity_id: str = Field(..., description="Canonical ID of target entity")
    
    # Multi-tenant and spatial boundaries (strict tenant match required)
    tenant_id: str = Field(..., description="Authoritative tenant isolation partition")
    workspace_id: str = Field(default="workspace_default")
    plant_id: Optional[str] = Field(default=None)
    
    # Metadata & Provenance
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Relationship edge attributes")
    valid_from: Optional[str] = Field(default=None, description="Temporal validity start (ISO 8601)")
    valid_to: Optional[str] = Field(default=None, description="Temporal validity end (ISO 8601)")
    source: EntitySource = Field(default=EntitySource.MANUAL, description="Provenance origin of relationship")
    confidence: RelationshipConfidence = Field(default=RelationshipConfidence.CONFIRMED)
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("source_entity_id", "target_entity_id")
    @classmethod
    def validate_no_self_referential_containment(cls, v: str) -> str:
        return v.strip()


# =====================================================================
# 8. EXTERNAL IDENTITY MAPPING ENTRY
# =====================================================================

class ExternalIdMapping(BaseModel):
    """Normalized external identity record mapping an external system ID to an entity."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(...)
    external_system: str = Field(..., min_length=1, max_length=64, description="Source system e.g. SAP, MES, SCADA")
    external_id: str = Field(..., min_length=1, max_length=256, description="External native identifier")
    entity_id: str = Field(..., description="Target canonical entity ID")
    confidence: RelationshipConfidence = Field(default=RelationshipConfidence.CONFIRMED)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =====================================================================
# 9. API REQUEST & RESPONSE ENVELOPES
# =====================================================================

class EntityCreateRequest(BaseModel):
    """Request payload to create a new canonical ontology entity."""
    model_config = ConfigDict(extra="ignore")

    entity_type: EntityType
    canonical_name: str = Field(..., min_length=1, max_length=256)
    display_name: str = Field(..., min_length=1, max_length=256)
    entity_id: Optional[str] = Field(default=None, description="Optional custom canonical ID. If omitted, auto-generated.")
    plant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default="workspace_default")
    external_ids: Dict[str, str] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: EntityLifecycleState = Field(default=EntityLifecycleState.ACTIVE)
    source: EntitySource = Field(default=EntitySource.MANUAL)


class EntityUpdateRequest(BaseModel):
    """Request payload to update an existing ontology entity."""
    model_config = ConfigDict(extra="ignore")

    display_name: Optional[str] = None
    plant_id: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    status: Optional[EntityLifecycleState] = None
    source: Optional[EntitySource] = None
    external_ids_to_add: Optional[Dict[str, str]] = None
    external_ids_to_remove: Optional[List[str]] = None


class RelationshipCreateRequest(BaseModel):
    """Request payload to establish a relationship edge between two entities."""
    model_config = ConfigDict(extra="ignore")

    relationship_type: RelationshipType
    source_entity_id: str
    target_entity_id: str
    plant_id: Optional[str] = None
    workspace_id: Optional[str] = Field(default="workspace_default")
    attributes: Dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    source: EntitySource = Field(default=EntitySource.MANUAL)
    confidence: RelationshipConfidence = Field(default=RelationshipConfidence.CONFIRMED)


class ExternalMappingRequest(BaseModel):
    """Request payload to register an external identifier mapping."""
    model_config = ConfigDict(extra="ignore")

    entity_id: Optional[str] = None
    system: Optional[str] = None
    external_system: Optional[str] = None
    external_id: str = Field(..., min_length=1, max_length=256)
    confidence: RelationshipConfidence = Field(default=RelationshipConfidence.CONFIRMED)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_system(self) -> str:
        s = self.system or self.external_system
        if not s:
            raise ValueError("Either 'system' or 'external_system' is required.")
        return s


class EntityResponse(BaseModel):
    success: bool = True
    data: OntologyEntity
    message: Optional[str] = None


class EntityListResponse(BaseModel):
    success: bool = True
    data: List[OntologyEntity]
    total_count: int
    limit: int
    offset: int


class RelationshipResponse(BaseModel):
    success: bool = True
    data: OntologyRelationship
    message: Optional[str] = None


class RelationshipListResponse(BaseModel):
    success: bool = True
    data: List[OntologyRelationship]
    total_count: int


class ExternalLookupResponse(BaseModel):
    success: bool = True
    resolved: bool
    entity: Optional[OntologyEntity] = None
    conflict: bool = False
    conflict_entity_ids: List[str] = Field(default_factory=list)
    message: Optional[str] = None


class TaxonomyResponse(BaseModel):
    success: bool = True
    entity_types: List[str]
    relationship_types: List[str]
    lifecycle_states: List[str]
    sources: List[str]
    compatibility_rules: Dict[str, Any]
