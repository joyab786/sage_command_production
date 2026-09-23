import hashlib
import json
import uuid
from enum import Enum
from typing import List, Optional, Dict, Any
import pydantic
from pydantic import BaseModel, Field
from datetime import datetime, UTC

class SupplierRiskStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class SupplierRiskConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class RiskFactor(BaseModel):
    factor_name: str = Field(..., description="Name of the risk factor (e.g., delivery_reliability)")
    score: float = Field(..., ge=0.0, le=100.0, description="Normalized score 0.0-100.0, 100.0 being highest risk")
    weight: float = Field(..., description="Weight of this factor in the overall calculation")
    contribution: float = Field(0.0, description="Weighted contribution to total score")
    explanation: str = Field(default="", description="Explanation of calculation")

class SupplierRiskEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"evd_{uuid.uuid4().hex}")
    factor_type: str = Field(..., description="The risk factor this evidence supports")
    source: str = Field(..., description="Source system (e.g., ERP, QMS)")
    source_id: str = Field(..., description="Source identifier")
    supplier_id: str = Field(..., description="Supplier identifier")
    timestamp: str = Field(..., description="ISO 8601 timestamp of observation")
    observed_value: Any = Field(..., description="The actual observed metric or state")
    expected_value: Any = Field(None, description="Expected or baseline value")
    contribution: float = Field(0.0, description="Contribution to the factor")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence in this evidence")
    provenance: str = Field("OBSERVED", description="Provenance of evidence")
    explanation: str = Field("", description="Explanation of evidence")

class AnalyticalObservation(BaseModel):
    observation_id: str = Field(default_factory=lambda: f"obs_{uuid.uuid4().hex}")
    observation_type: str = Field(..., description="Observation category (e.g., QUALITY_TREND)")
    description: str = Field(..., description="Human readable analytical observation")
    executable: bool = Field(False, description="Must always be False")

    @pydantic.model_validator(mode="before")
    @classmethod
    def check_executable(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("executable") is True:
            raise ValueError("AnalyticalObservation cannot be executable")
        return data

class SupplierExposure(BaseModel):
    affected_component_count: int = Field(default=0, description="Number of components affected by this supplier")
    affected_sku_count: int = Field(default=0, description="Number of SKUs affected")
    affected_order_count: int = Field(default=0, description="Number of active orders affected")
    affected_plant_count: int = Field(default=0, description="Number of affected plants")
    forecast_exposure_units: Optional[int] = Field(default=None, description="Forecasted demand units exposed to this supplier")
    single_source_exposure: bool = Field(default=False, description="Is this a single-source dependency?")

class ContextBounds(BaseModel):
    dependency_context: Dict[str, Any] = Field(default_factory=dict)
    delivery_context: Dict[str, Any] = Field(default_factory=dict)
    quality_context: Dict[str, Any] = Field(default_factory=dict)
    capacity_context: Dict[str, Any] = Field(default_factory=dict)
    demand_context: Dict[str, Any] = Field(default_factory=dict)
    incident_context: Dict[str, Any] = Field(default_factory=dict)
    blast_radius_context: Dict[str, Any] = Field(default_factory=dict)
    event_context: Dict[str, Any] = Field(default_factory=dict)
    ontology_context: Dict[str, Any] = Field(default_factory=dict)
    knowledge_graph_context: Dict[str, Any] = Field(default_factory=dict)
    digital_twin_context: Dict[str, Any] = Field(default_factory=dict)
    forecast_context: Dict[str, Any] = Field(default_factory=dict)

class SupplierRiskAssessment(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    workspace_id: Optional[str] = Field(None, description="Workspace identifier")
    plant_id: Optional[str] = Field(None, description="Plant identifier")
    supplier_id: str = Field(..., description="Canonical supplier identifier")
    supplier_name: str = Field(default="UNKNOWN", description="Supplier name")
    supplier_type: str = Field(default="UNKNOWN", description="Supplier type")
    
    assessment_id: str = Field(default_factory=lambda: f"risk_{uuid.uuid4().hex}")
    assessment_timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    as_of_timestamp: str = Field(..., description="ISO-8601 UTC timestamp defining the observation boundary")
    evaluation_window: int = Field(90, description="Evaluation window in days")
    
    risk_status: SupplierRiskStatus = Field(..., description="Overall assessed risk status")
    risk_score: float = Field(..., ge=0.0, le=100.0, description="Aggregated risk score (0 to 100, 100 is highest risk)")
    confidence: SupplierRiskConfidence = Field(..., description="Confidence in the assessment")
    uncertainty: str = Field(default="", description="Explanation of uncertainty drivers")
    
    factors: List[RiskFactor] = Field(default_factory=list, description="Calculated risk factors")
    evidence: List[SupplierRiskEvidence] = Field(default_factory=list, description="Structured evidence supporting the assessment")
    observations: List[AnalyticalObservation] = Field(default_factory=list, description="Analytical observations")
    exposure_summary: SupplierExposure = Field(default_factory=SupplierExposure, description="Operational exposure metrics")
    context: ContextBounds = Field(default_factory=ContextBounds, description="Various context signals")
    
    data_quality_issues: List[str] = Field(default_factory=list, description="Exclusions or quality issues encountered")
    
    provenance: str = Field(default="system", description="Provenance")
    methodology: str = Field(default="deterministic_weighted_sum", description="Calculation method")
    model_version: str = Field(default="v1.0")
    schema_version: str = Field(default="1.0")
    
    input_fingerprint: str = Field(default="")

    def generate_fingerprint(self) -> str:
        """
        Generate a deterministic input fingerprint based on canonical inputs.
        """
        factor_payload = [{"name": f.factor_name, "score": f.score, "weight": f.weight} for f in self.factors]
        # order them predictably
        factor_payload.sort(key=lambda x: x["name"])
        
        evidence_payload = [
            {"factor": e.factor_type, "obs_val": str(e.observed_value), "timestamp": e.timestamp}
            for e in self.evidence
        ]
        evidence_payload.sort(key=lambda x: (x["factor"], x["timestamp"], x["obs_val"]))
        
        payload = {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id or "",
            "plant_id": self.plant_id or "",
            "supplier_id": self.supplier_id,
            "as_of_timestamp": self.as_of_timestamp,
            "evaluation_window": self.evaluation_window,
            "factors": factor_payload,
            "evidence": evidence_payload,
            "methodology": self.methodology,
            "model_version": self.model_version
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.input_fingerprint = hashlib.sha256(encoded).hexdigest()
        return self.input_fingerprint
