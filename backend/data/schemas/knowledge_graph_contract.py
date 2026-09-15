# backend/data/schemas/knowledge_graph_contract.py
"""
SageCommand V3 — Operational Knowledge Graph (OKG) Contracts
Defines deterministic domain models for operational facts, temporal validity,
provenance, freshness states, graph nodes, traversal envelopes, and validation reports.

Cardinal Invariant:
The Operational Knowledge Graph is purely an informational context and query layer.
It never performs operational mutations or bypasses the Execution Gateway.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict

try:
    from data.schemas.ontology_contract import (
        EntityType,
        RelationshipType,
        RelationshipConfidence,
        EntityLifecycleState,
    )
except ModuleNotFoundError:
    from backend.data.schemas.ontology_contract import (
        EntityType,
        RelationshipType,
        RelationshipConfidence,
        EntityLifecycleState,
    )


# =============================================================================
# 1. ENUMS
# =============================================================================

class FactValueType(str, Enum):
    """Primitive data type representation for operational fact values."""
    STRING = "STRING"
    FLOAT = "FLOAT"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"
    JSON = "JSON"
    ENTITY_REFERENCE = "ENTITY_REFERENCE"


class FactSourceType(str, Enum):
    """Deterministic provenance categories for operational knowledge."""
    TELEMETRY = "TELEMETRY"
    DATABASE = "DATABASE"
    API = "API"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"
    SIMULATOR = "SIMULATOR"
    IMPORTED_DATASET = "IMPORTED_DATASET"


class FactLifecycleState(str, Enum):
    """Lifecycle progression for operational facts."""
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CONFLICT = "CONFLICT"


class FreshnessState(str, Enum):
    """Temporal freshness evaluation for operational observations."""
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class TraversalDirection(str, Enum):
    """Directionality for graph neighbor and path traversal."""
    UPSTREAM = "UPSTREAM"      # Inward/incoming dependency edges
    DOWNSTREAM = "DOWNSTREAM"  # Outward/outgoing dependency edges
    BOTH = "BOTH"              # Bidirectional expansion


# =============================================================================
# 2. CORE DOMAIN MODELS
# =============================================================================

class OperationalFact(BaseModel):
    """
    Deterministic representation of an operational observation or assertion.
    Features bitemporal awareness: distinguishing when a fact occurred (observed_at),
    when it was legally valid (valid_from -> valid_to), and when the system ingested it (recorded_at).
    """
    model_config = ConfigDict(extra="ignore")

    fact_id: str = Field(..., description="Unique fact identifier, e.g. fact_8a92b1c4")
    tenant_id: str = Field(..., description="Mandatory tenant isolation partition key")
    workspace_id: str = Field(default="workspace_default")
    plant_id: Optional[str] = None
    subject_entity_id: str = Field(..., description="Canonical ontology entity URN")
    predicate: str = Field(..., min_length=1, max_length=128, description="Operational attribute or relationship type")
    object_entity_id: Optional[str] = Field(None, description="Optional target entity URN if fact links two entities")
    value_type: FactValueType = Field(default=FactValueType.STRING)
    value: Any = Field(..., description="Observed value, typed or serialized")
    unit: Optional[str] = Field(None, description="Physical or logical unit, e.g. CELSIUS, RPM, UNITS")
    source_type: FactSourceType = Field(default=FactSourceType.SYSTEM)
    source_id: str = Field(..., description="Identifier of reporting device, actor, or sync process")
    observed_at: str = Field(..., description="ISO 8601 timestamp when observed in the field")
    valid_from: str = Field(..., description="ISO 8601 timestamp when fact became valid")
    valid_to: Optional[str] = Field(None, description="ISO 8601 timestamp when validity ended, or None if still active")
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence score if reported by genuine source")
    status: FactLifecycleState = Field(default=FactLifecycleState.ACTIVE)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OperationalEdge(BaseModel):
    """
    Dynamic operational relationship edge linking two canonical ontology entities.
    Captures temporal associations like CURRENTLY_PRODUCING or CURRENTLY_ASSIGNED.
    """
    model_config = ConfigDict(extra="ignore")

    edge_id: str = Field(..., description="Unique edge identifier, e.g. edge_7f21a9c3")
    tenant_id: str = Field(..., description="Mandatory tenant boundary key")
    workspace_id: str = Field(default="workspace_default")
    plant_id: Optional[str] = None
    source_entity_id: str = Field(..., description="Source entity URN")
    target_entity_id: str = Field(..., description="Target entity URN")
    predicate: str = Field(..., description="Operational edge predicate / relationship name")
    attributes: Dict[str, Any] = Field(default_factory=dict)
    valid_from: str
    valid_to: Optional[str] = None
    source_type: FactSourceType = Field(default=FactSourceType.SYSTEM)
    source_id: str = Field(default="system")
    status: FactLifecycleState = Field(default=FactLifecycleState.ACTIVE)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class KnowledgeGraphNode(BaseModel):
    """
    Contextual view of an entity inside the Operational Knowledge Graph,
    merging canonical ontology identity with active operational facts and freshness indicators.
    """
    model_config = ConfigDict(extra="ignore")

    entity_id: str
    entity_type: EntityType
    canonical_name: str
    display_name: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    lifecycle_status: EntityLifecycleState
    operational_status: Optional[str] = None
    active_facts: List[OperationalFact] = Field(default_factory=list)
    freshness: FreshnessState = Field(default=FreshnessState.UNKNOWN)
    last_observed_at: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    external_ids: Dict[str, str] = Field(default_factory=dict)


class GraphNeighbor(BaseModel):
    """A neighbor node connected via either ontology structure or operational edges."""
    model_config = ConfigDict(extra="ignore")

    entity_id: str
    entity_type: EntityType
    display_name: str
    relationship_type: str
    direction: str  # "OUTGOING" | "INCOMING"
    edge_source: str  # "ONTOLOGY" | "OPERATIONAL"
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    freshness: Optional[FreshnessState] = None


class GraphPath(BaseModel):
    """Deterministic path representation between two entities in the graph."""
    model_config = ConfigDict(extra="ignore")

    source_entity_id: str
    target_entity_id: str
    path: List[str]  # Ordered sequence of entity IDs
    depth: int
    edges: List[Dict[str, Any]] = Field(default_factory=list)


class GraphValidationIssue(BaseModel):
    """Structured graph consistency finding."""
    model_config = ConfigDict(extra="ignore")

    severity: str  # "ERROR" | "WARNING"
    issue_type: str
    entity_id: Optional[str] = None
    fact_id: Optional[str] = None
    message: str


class GraphValidationReport(BaseModel):
    """Comprehensive graph consistency audit report."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_valid: bool
    error_count: int
    warning_count: int
    issues: List[GraphValidationIssue] = Field(default_factory=list)


# =============================================================================
# 3. REQUEST & RESPONSE ENVELOPES
# =============================================================================

class FactCreateRequest(BaseModel):
    """Request payload to ingest an operational fact."""
    model_config = ConfigDict(extra="ignore")

    subject_entity_id: str = Field(..., min_length=1)
    predicate: str = Field(..., min_length=1, max_length=128)
    object_entity_id: Optional[str] = None
    value_type: FactValueType = Field(default=FactValueType.STRING)
    value: Any = Field(...)
    unit: Optional[str] = None
    source_type: FactSourceType = Field(default=FactSourceType.API)
    source_id: str = Field(..., min_length=1)
    observed_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FactRevokeRequest(BaseModel):
    """Request payload to revoke an active fact."""
    model_config = ConfigDict(extra="ignore")

    reason: str = Field(..., min_length=1, max_length=256)


class FactResponse(BaseModel):
    success: bool = True
    data: OperationalFact
    message: Optional[str] = None


class FactListResponse(BaseModel):
    success: bool = True
    data: List[OperationalFact]
    total_count: int
    limit: int
    offset: int


class EntityNodeResponse(BaseModel):
    success: bool = True
    data: KnowledgeGraphNode
    message: Optional[str] = None


class NeighborsResponse(BaseModel):
    success: bool = True
    entity_id: str
    neighbors: List[GraphNeighbor]
    total_count: int


class ContextResponse(BaseModel):
    success: bool = True
    root_entity_id: str
    nodes: Dict[str, KnowledgeGraphNode]
    edges: List[Dict[str, Any]]
    total_nodes: int
    total_edges: int
    depth_reached: int


# Alias for backward compatibility
GraphContextResponse = ContextResponse


class PathResponse(BaseModel):
    success: bool = True
    found: bool
    data: Optional[GraphPath] = None
    message: Optional[str] = None


class ValidationResponse(BaseModel):
    success: bool = True
    report: GraphValidationReport


class ProjectionSyncResponse(BaseModel):
    success: bool = True
    facts_ingested: int
    source_records_inspected: int
    message: str
