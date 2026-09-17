import hashlib
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
from pydantic import BaseModel, Field


class RcaAnalysisStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class CauseType(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    SENSOR = "SENSOR"
    PROCESS = "PROCESS"
    MATERIAL = "MATERIAL"
    OPERATOR = "OPERATOR"
    SOFTWARE = "SOFTWARE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    ENVIRONMENT = "ENVIRONMENT"
    UPSTREAM_DEPENDENCY = "UPSTREAM_DEPENDENCY"
    UNKNOWN = "UNKNOWN"


class CausalRelationshipType(str, Enum):
    PRECEDES = "PRECEDES"
    DEPENDS_ON = "DEPENDS_ON"
    CORRELATES_WITH = "CORRELATES_WITH"
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    CONTRADICTS = "CONTRADICTS"
    SUPPORTS = "SUPPORTS"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DataQualityState(str, Enum):
    VALID = "VALID"
    INCOMPLETE = "INCOMPLETE"
    STALE = "STALE"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class EvidenceSourceType(str, Enum):
    INCIDENT = "INCIDENT"
    EVENT = "EVENT"
    ANOMALY = "ANOMALY"
    TWIN_STATE = "TWIN_STATE"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    ONTOLOGY = "ONTOLOGY"
    DATA_QUALITY = "DATA_QUALITY"
    OPERATOR_OBSERVATION = "OPERATOR_OBSERVATION"


class TemporalReasoning(BaseModel):
    time_difference_ms: int
    window_used_ms: int
    temporal_relation: str
    source_timestamp: str
    target_timestamp: str


class DependencyReasoning(BaseModel):
    graph_depth: int
    relationship_type: str
    source_entity: str
    target_entity: str
    path: List[str] = Field(default_factory=list)


class RcaEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"evd_{uuid.uuid4().hex}")
    cause_id: str
    source_type: EvidenceSourceType
    source_id: str
    relationship: str
    recorded_timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    provenance: str
    relevance_metadata: Dict[str, Any] = Field(default_factory=dict)


class CauseCandidate(BaseModel):
    cause_id: str = Field(default_factory=lambda: f"cause_{uuid.uuid4().hex}")
    analysis_id: str
    cause_type: CauseType
    label: str
    description: str
    status: str = Field(default="CANDIDATE")
    score: float = Field(default=0.0)
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.UNKNOWN)
    uncertainty: str = Field(default="")
    evidence_refs: List[RcaEvidence] = Field(default_factory=list)
    entity_refs: List[str] = Field(default_factory=list)
    temporal_support: Optional[TemporalReasoning] = None
    dependency_support: Optional[DependencyReasoning] = None
    data_quality_state: DataQualityState = Field(default=DataQualityState.UNKNOWN)
    provenance: str = Field(default="system")


class CausalRelationship(BaseModel):
    relationship_id: str = Field(default_factory=lambda: f"rel_{uuid.uuid4().hex}")
    analysis_id: str
    source_cause_id: str
    target_cause_id: str
    relationship_type: CausalRelationshipType
    description: str = Field(default="")


class RcaAnalysis(BaseModel):
    analysis_id: str = Field(default_factory=lambda: f"rca_{uuid.uuid4().hex}")
    incident_id: str
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    schema_version: str = Field(default="1.0")
    analysis_version: int = Field(default=1)
    status: RcaAnalysisStatus = Field(default=RcaAnalysisStatus.PENDING)
    started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    completed_at: Optional[str] = None
    method_version: str = Field(default="deterministic_v1")
    input_fingerprint: str = Field(description="Deterministic fingerprint of all inputs used in analysis")
    
    causes: List[CauseCandidate] = Field(default_factory=list)
    relationships: List[CausalRelationship] = Field(default_factory=list)

    def generate_fingerprint(
        self,
        incident_id: str,
        evidence_ids: List[str],
        kg_version: str,
        twin_snapshot_id: str,
        method_version: str
    ) -> str:
        """Generates deterministic input fingerprint for reproducibility."""
        sorted_evidence = sorted(evidence_ids)
        raw = f"{incident_id}|{','.join(sorted_evidence)}|{kg_version}|{twin_snapshot_id}|{method_version}"
        self.input_fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.input_fingerprint
