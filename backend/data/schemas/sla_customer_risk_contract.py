import hashlib
import json
import uuid
from enum import Enum
from typing import List, Optional, Dict, Any
import pydantic
from pydantic import BaseModel, Field
from datetime import datetime, UTC

class SLARiskStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    LIKELY_BREACH = "LIKELY_BREACH"
    BREACHED = "BREACHED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class SLARiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class SLARiskConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class SLARiskFactor(BaseModel):
    factor_name: str = Field(..., description="Name of the risk factor (e.g., historical_lateness)")
    score: float = Field(..., ge=0.0, le=100.0, description="Normalized score 0.0-100.0, 100.0 being highest risk")
    weight: float = Field(..., description="Weight of this factor in the overall calculation")
    contribution: float = Field(0.0, description="Weighted contribution to total score")
    explanation: str = Field(default="", description="Explanation of calculation")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of supporting evidence")

class SLAEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"evd_{uuid.uuid4().hex}")
    source_domain: str = Field(..., description="Source system (e.g., PREDICTIVE_MAINTENANCE, SUPPLIER_RISK)")
    source_reference: str = Field(..., description="Source identifier")
    observation_timestamp: str = Field(..., description="ISO 8601 timestamp of observation")
    effective_timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp when this becomes effective")
    evidence_type: str = Field(..., description="Type of evidence")
    value: Any = Field(..., description="The actual observed metric or state")
    contribution: float = Field(0.0, description="Contribution to the factor")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence in this evidence")
    provenance: str = Field("OBSERVED", description="Provenance of evidence (OBSERVED, DERIVED, SIMULATED, UNKNOWN)")
    explanation: str = Field("", description="Explanation of evidence")

class SLAHistoricalPerformance(BaseModel):
    total_commitments: int = Field(default=0, description="Total historical commitments in period")
    breach_count: int = Field(default=0, description="Number of breached commitments")
    late_count: int = Field(default=0, description="Number of late commitments")
    compliance_rate: float = Field(default=0.0, description="Percentage of compliant commitments")
    average_delay_hours: float = Field(default=0.0, description="Average delay in hours")
    worst_delay_hours: float = Field(default=0.0, description="Worst delay in hours")
    trend: str = Field(default="STABLE", description="Recent trend (IMPROVING, WORSENING, STABLE)")

class SLACapacityExposure(BaseModel):
    utilization_percent: float = Field(default=0.0, description="Capacity utilization percentage")
    shortfall_units: int = Field(default=0, description="Capacity shortfall")
    projected_pressure: str = Field(default="LOW", description="Projected capacity pressure")

class SLADemandExposure(BaseModel):
    forecast_exceeds_capacity: bool = Field(default=False, description="Does forecast exceed capacity?")
    demand_acceleration: str = Field(default="FLAT", description="Demand acceleration trend")
    forecast_uncertainty: float = Field(default=0.0, description="Forecast uncertainty score")

class SLAContextBounds(BaseModel):
    delivery_context: Dict[str, Any] = Field(default_factory=dict)
    capacity_context: Dict[str, Any] = Field(default_factory=dict)
    demand_context: Dict[str, Any] = Field(default_factory=dict)
    supplier_context: Dict[str, Any] = Field(default_factory=dict)
    incident_context: Dict[str, Any] = Field(default_factory=dict)
    anomaly_context: Dict[str, Any] = Field(default_factory=dict)
    maintenance_context: Dict[str, Any] = Field(default_factory=dict)
    blast_radius_context: Dict[str, Any] = Field(default_factory=dict)
    ontology_context: Dict[str, Any] = Field(default_factory=dict)
    knowledge_graph_context: Dict[str, Any] = Field(default_factory=dict)
    digital_twin_context: Dict[str, Any] = Field(default_factory=dict)
    rca_context: Dict[str, Any] = Field(default_factory=dict)

class SLACustomerRiskAssessment(BaseModel):
    # Identity
    tenant_id: str = Field(..., description="Tenant identifier")
    workspace_id: Optional[str] = Field(None, description="Workspace identifier")
    customer_id: str = Field(..., description="Customer identifier")
    customer_reference: str = Field(default="", description="Customer reference/name")
    customer_segment: str = Field(default="DEFAULT", description="Customer segment")
    region: str = Field(default="GLOBAL", description="Customer region")
    
    # SLA/Service Identity
    service_id: str = Field(..., description="Service identifier")
    service_type: str = Field(default="STANDARD", description="Service type")
    sla_reference: str = Field(default="", description="SLA identifier")
    obligation_type: str = Field(default="DELIVERY", description="Obligation type")
    target_metric: str = Field(default="ON_TIME_DELIVERY", description="Target metric")
    target_threshold: float = Field(default=100.0, description="Target threshold")
    
    # Time
    assessment_id: str = Field(default_factory=lambda: f"sla_risk_{uuid.uuid4().hex}")
    assessment_timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    observation_start: str = Field(..., description="Observation period start")
    observation_end: str = Field(..., description="Observation period end")
    commitment_due_at: Optional[str] = Field(None, description="When the commitment is due")
    expected_completion_at: Optional[str] = Field(None, description="Expected completion time")
    breach_window_start: Optional[str] = Field(None, description="Breach window start")
    breach_window_end: Optional[str] = Field(None, description="Breach window end")
    
    # Risk State
    risk_level: SLARiskLevel = Field(..., description="Deterministic risk level")
    sla_status: SLARiskStatus = Field(..., description="SLA status")
    risk_score: float = Field(..., ge=0.0, le=100.0, description="Aggregated risk score")
    confidence: SLARiskConfidence = Field(..., description="Confidence in the assessment")
    
    # Explainability & Evidence
    factors: List[SLARiskFactor] = Field(default_factory=list, description="Calculated risk factors")
    evidence: List[SLAEvidence] = Field(default_factory=list, description="Structured evidence supporting the assessment")
    historical_performance: SLAHistoricalPerformance = Field(default_factory=SLAHistoricalPerformance, description="Historical SLA performance")
    capacity_exposure: SLACapacityExposure = Field(default_factory=SLACapacityExposure, description="Capacity exposure")
    demand_exposure: SLADemandExposure = Field(default_factory=SLADemandExposure, description="Demand exposure")
    context: SLAContextBounds = Field(default_factory=SLAContextBounds, description="Various context signals")
    
    data_quality_issues: List[str] = Field(default_factory=list, description="Exclusions or quality issues encountered")
    
    # Metadata
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
        factor_payload.sort(key=lambda x: x["name"])
        
        evidence_payload = [
            {"domain": e.source_domain, "obs_val": str(e.value), "timestamp": e.observation_timestamp}
            for e in self.evidence
        ]
        evidence_payload.sort(key=lambda x: (x["domain"], x["timestamp"], x["obs_val"]))
        
        payload = {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id or "",
            "customer_id": self.customer_id,
            "service_id": self.service_id,
            "assessment_timestamp": self.assessment_timestamp,
            "observation_end": self.observation_end,
            "commitment_due_at": self.commitment_due_at or "",
            "factors": factor_payload,
            "evidence": evidence_payload,
            "methodology": self.methodology,
            "model_version": self.model_version
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.input_fingerprint = hashlib.sha256(encoded).hexdigest()
        return self.input_fingerprint
