import hashlib
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
from pydantic import BaseModel, Field


class BlastRadiusAnalysisStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class ImpactClassification(str, Enum):
    DIRECT = "DIRECT"
    DEPENDENT = "DEPENDENT"
    UPSTREAM = "UPSTREAM"
    DOWNSTREAM = "DOWNSTREAM"
    SHARED_RESOURCE = "SHARED_RESOURCE"
    RELATED = "RELATED"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ImpactEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"evd_{uuid.uuid4().hex}")
    source_type: str = Field(description="e.g., KNOWLEDGE_GRAPH, ONTOLOGY, DIGITAL_TWIN, INCIDENT, RCA")
    source_id: str
    source_timestamp: str = Field(description="ISO timestamp from the source observation")
    source_version: str = Field(default="1.0")
    provenance: str = Field(default="system")
    evidence_strength: float = Field(default=1.0, description="Multiplier between 0.0 and 1.0")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ImpactRelationship(BaseModel):
    relationship_type: str = Field(description="Semantic relationship type from ontology")
    direction: str = Field(description="UPSTREAM, DOWNSTREAM, or BOTH")
    propagation_behavior: str = Field(description="How this relationship passes impact")
    strength: float = Field(default=1.0)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.INSUFFICIENT_DATA)
    evidence_refs: List[ImpactEvidence] = Field(default_factory=list)


class ImpactNode(BaseModel):
    entity_id: str
    entity_type: str
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    impact_classification: ImpactClassification = Field(default=ImpactClassification.UNKNOWN)
    impact_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.INSUFFICIENT_DATA)
    uncertainty: str = Field(default="")
    distance: int = Field(default=0, description="Dependency depth from source")
    temporal_validity_start: Optional[str] = None
    temporal_validity_end: Optional[str] = None
    evidence_refs: List[ImpactEvidence] = Field(default_factory=list)
    provenance: str = Field(default="system")


class ImpactPath(BaseModel):
    path_id: str = Field(default_factory=lambda: f"path_{uuid.uuid4().hex}")
    source_node_id: str
    target_node_id: str
    ordered_path: List[str] = Field(default_factory=list)
    relationship_types: List[str] = Field(default_factory=list)
    traversal_depth: int
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.INSUFFICIENT_DATA)
    uncertainty: str = Field(default="")
    temporal_validity: Optional[str] = None
    evidence_refs: List[ImpactEvidence] = Field(default_factory=list)
    provenance: str = Field(default="system")


class ImpactScope(BaseModel):
    total_assets: int = Field(default=0)
    total_processes: int = Field(default=0)
    total_production_areas: int = Field(default=0)
    total_workspaces: int = Field(default=0)
    total_plants: int = Field(default=0)
    total_upstream_dependencies: int = Field(default=0)
    total_downstream_dependencies: int = Field(default=0)
    related_incidents: int = Field(default=0)
    related_anomalies: int = Field(default=0)


class BlastRadiusAnalysis(BaseModel):
    analysis_id: str = Field(default_factory=lambda: f"bra_{uuid.uuid4().hex}")
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    
    # Source Context
    source_entity_id: Optional[str] = None
    source_entity_type: Optional[str] = None
    source_incident_id: Optional[str] = None
    source_anomaly_id: Optional[str] = None
    source_event_id: Optional[str] = None
    
    analysis_status: BlastRadiusAnalysisStatus = Field(default=BlastRadiusAnalysisStatus.PENDING)
    analysis_timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    snapshot_timestamp: str = Field(description="Timestamp used as the valid context for graph evaluation")
    
    # Environment State versions
    ontology_version: str = Field(default="1.0")
    knowledge_graph_version: str = Field(default="1.0")
    digital_twin_snapshot_id: Optional[str] = None
    method_version: str = Field(default="deterministic_br_v1")
    
    input_fingerprint: str = Field(default="", description="Deterministic fingerprint of analysis inputs")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.INSUFFICIENT_DATA)
    uncertainty: str = Field(default="")
    
    scope: Optional[ImpactScope] = None
    schema_version: str = Field(default="1.0")
    
    # Optional outputs directly attached (or persisted separately)
    nodes: List[ImpactNode] = Field(default_factory=list)
    paths: List[ImpactPath] = Field(default_factory=list)
    
    def generate_fingerprint(self) -> str:
        """
        Deterministically normalizes analysis inputs to produce a deduplication fingerprint.
        """
        parts = [
            self.tenant_id,
            self.workspace_id or "",
            self.plant_id or "",
            self.source_entity_id or "",
            self.source_incident_id or "",
            self.source_anomaly_id or "",
            self.source_event_id or "",
            self.snapshot_timestamp,
            self.ontology_version,
            self.knowledge_graph_version,
            self.digital_twin_snapshot_id or "",
            self.method_version
        ]
        raw = "|".join(parts)
        self.input_fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.input_fingerprint
