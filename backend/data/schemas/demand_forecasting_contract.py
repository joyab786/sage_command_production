import hashlib
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
from pydantic import BaseModel, Field

class Granularity(str, Enum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"

class ForecastHorizon(str, Enum):
    SHORT_TERM = "SHORT_TERM"
    MEDIUM_TERM = "MEDIUM_TERM"
    LONG_TERM = "LONG_TERM"

class TrendDirection(str, Enum):
    STABLE = "STABLE"
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class ForecastMethod(str, Enum):
    NAIVE = "NAIVE"
    MOVING_AVERAGE = "MOVING_AVERAGE"
    WEIGHTED_MOVING_AVERAGE = "WEIGHTED_MOVING_AVERAGE"
    EXPONENTIAL_SMOOTHING = "EXPONENTIAL_SMOOTHING"
    TREND_ADJUSTED = "TREND_ADJUSTED"
    SEASONAL = "SEASONAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class ValueProvenance(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"

class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class DemandObservation(BaseModel):
    timestamp: str = Field(description="ISO 8601 timestamp")
    value: float
    unit: str = Field(default="UNITS")
    source: str = Field(default="UNKNOWN")
    entity_id: str
    provenance: ValueProvenance = Field(default=ValueProvenance.OBSERVED)
    quality_metadata: Dict[str, Any] = Field(default_factory=dict)

class ForecastEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"f_evd_{uuid.uuid4().hex}")
    factor_type: str = Field(description="e.g., TREND, SEASONALITY, ANOMALY, QUALITY")
    source: str
    source_id: str
    timestamp: str
    contribution: float = Field(default=0.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: ValueProvenance = Field(default=ValueProvenance.UNKNOWN)
    explanation: str = Field(default="")

class ForecastRecommendation(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: f"f_rec_{uuid.uuid4().hex}")
    observation_type: str = Field(description="e.g., EXPECTED_INCREASE, MONITOR_VOLATILITY")
    description: str = Field(description="Analytical explanation")
    evidence_refs: List[str] = Field(default_factory=list)
    executable: bool = Field(default=False, description="Must always be False. This subsystem has no execution authority.")

class ForecastContext(BaseModel):
    anomalies_considered: int = Field(default=0)
    data_quality_score: float = Field(default=100.0)
    related_events: int = Field(default=0)
    digital_twin_state_available: bool = Field(default=False)
    knowledge_graph_relationships: int = Field(default=0)
    maintenance_context_available: bool = Field(default=False)

class ForecastPoint(BaseModel):
    timestamp: str
    value: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None

class DemandForecast(BaseModel):
    forecast_id: str = Field(default_factory=lambda: f"fcst_{uuid.uuid4().hex}")
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    demand_entity_id: str
    demand_entity_type: str = Field(default="UNKNOWN")
    demand_entity_name: str = Field(default="UNKNOWN")
    
    forecast_timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    forecast_horizon: ForecastHorizon
    forecast_granularity: Granularity
    forecast_start: str
    forecast_end: str
    
    baseline_value: Optional[float] = None
    forecast_values: List[ForecastPoint] = Field(default_factory=list)
    
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.INSUFFICIENT_DATA)
    uncertainty: str = Field(default="Insufficient evidence to assess forecast.")
    
    trend_context: TrendDirection = Field(default=TrendDirection.INSUFFICIENT_DATA)
    seasonality_context: str = Field(default="NONE")
    
    method_selected: ForecastMethod = Field(default=ForecastMethod.INSUFFICIENT_DATA)
    
    historical_observations: List[DemandObservation] = Field(default_factory=list)
    evidence: List[ForecastEvidence] = Field(default_factory=list)
    recommendations: List[ForecastRecommendation] = Field(default_factory=list)
    context: ForecastContext = Field(default_factory=ForecastContext)
    
    input_fingerprint: str = Field(default="")
    provenance: str = Field(default="system")
    model_version: str = Field(default="v1.0")
    schema_version: str = Field(default="1.0")

    def generate_fingerprint(self) -> str:
        """
        Deterministically normalizes analysis inputs to produce a deduplication fingerprint.
        """
        # Exclude IDs and non-deterministic fields from the fingerprint
        parts = [
            self.tenant_id,
            self.workspace_id or "",
            self.plant_id or "",
            self.demand_entity_id,
            self.forecast_timestamp,
            self.forecast_horizon.value,
            self.forecast_granularity.value,
            self.model_version,
            str(len(self.historical_observations)),
            self.method_selected.value
        ]
        raw = "|".join(parts)
        self.input_fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.input_fingerprint

class ForecastEvaluationMetric(BaseModel):
    metric: str
    value: float
    description: str

class ForecastEvaluation(BaseModel):
    evaluation_id: str = Field(default_factory=lambda: f"f_eval_{uuid.uuid4().hex}")
    tenant_id: str
    forecast_id: str
    evaluation_timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    metrics: List[ForecastEvaluationMetric] = Field(default_factory=list)
    evaluation_observations: int = Field(default=0)
    provenance: str = Field(default="system")
