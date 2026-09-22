import hashlib
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ValueProvenance(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"


class MaintenanceEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"evd_{uuid.uuid4().hex}")
    factor_type: str = Field(description="e.g., ANOMALY_RECURRENCE, DATA_QUALITY_DEGRADATION, DIGITAL_TWIN_STATE")
    source: str = Field(description="e.g., ANOMALY_ENGINE, DIGITAL_TWIN, INCIDENT_DB")
    source_id: str
    timestamp: str = Field(description="ISO timestamp of the evidence observation")
    contribution: float = Field(default=0.0, description="Numerical contribution to the risk score")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: ValueProvenance = Field(default=ValueProvenance.UNKNOWN)
    explanation: str = Field(default="")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MaintenanceRecommendation(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex}")
    action_type: str = Field(description="e.g., INSPECT, REVIEW_TELEMETRY")
    description: str = Field(description="Evidence-backed explainable text")
    estimated_impact: str = Field(default="UNKNOWN")
    evidence_refs: List[str] = Field(default_factory=list, description="List of evidence_ids")
    executable: bool = Field(default=False, description="Must always be False for this analytical foundation")


class AssessmentContext(BaseModel):
    related_anomalies: int = Field(default=0)
    related_events: int = Field(default=0)
    related_incidents: int = Field(default=0)
    related_rca: int = Field(default=0)
    blast_radius_downstream_impacts: int = Field(default=0)
    blast_radius_upstream_impacts: int = Field(default=0)
    digital_twin_state_available: bool = Field(default=False)
    knowledge_graph_relationships: int = Field(default=0)


class MaintenanceRiskAssessment(BaseModel):
    assessment_id: str = Field(default_factory=lambda: f"pm_{uuid.uuid4().hex}")
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    
    asset_id: str
    asset_type: str = Field(default="UNKNOWN")
    asset_name: str = Field(default="UNKNOWN")
    
    assessment_timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    prediction_horizon: str = Field(default="P7D", description="ISO 8601 duration, e.g., P7D for 7 days")
    
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    risk_level: RiskLevel = Field(default=RiskLevel.UNKNOWN)
    
    health_score: float = Field(default=100.0, ge=0.0, le=100.0)
    degradation_score: float = Field(default=0.0, ge=0.0, le=100.0)
    
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.INSUFFICIENT_DATA)
    uncertainty: str = Field(default="Insufficient evidence to assess maintenance risk.")
    
    failure_probability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    estimated_time_to_maintenance: Optional[str] = Field(default=None, description="ISO timestamp if deterministically supportable")
    maintenance_window: Optional[str] = Field(default=None, description="Suggested window based on horizon")
    
    evidence: List[MaintenanceEvidence] = Field(default_factory=list)
    recommendations: List[MaintenanceRecommendation] = Field(default_factory=list)
    
    context: AssessmentContext = Field(default_factory=AssessmentContext)
    
    input_fingerprint: str = Field(default="", description="Deterministic fingerprint of analysis inputs")
    provenance: str = Field(default="system")
    schema_version: str = Field(default="1.0")

    def generate_fingerprint(self, method_version: str = "v1") -> str:
        """
        Deterministically normalizes analysis inputs to produce a deduplication fingerprint.
        """
        # Ensure determinism by sorting evidence IDs
        sorted_evidence = sorted([e.evidence_id for e in self.evidence])
        
        parts = [
            self.tenant_id,
            self.workspace_id or "",
            self.plant_id or "",
            self.asset_id,
            self.assessment_timestamp,
            self.prediction_horizon,
            method_version,
            ",".join(sorted_evidence)
        ]
        raw = "|".join(parts)
        self.input_fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.input_fingerprint
