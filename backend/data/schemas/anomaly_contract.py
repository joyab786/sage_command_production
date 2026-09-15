# backend/data/schemas/anomaly_contract.py
"""
SageCommand V3 — Real Anomaly Detection Engine Contracts (Prompt 15)
Defines deterministic domain models for anomalies, baselines, observations, and assessment scopes.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timezone
from pydantic import BaseModel, Field

try:
    from data.schemas.data_quality_contract import QualityStatus
except ModuleNotFoundError:
    from backend.data.schemas.data_quality_contract import QualityStatus


# =============================================================================
# 1. ENUMS
# =============================================================================

class AnomalyType(str, Enum):
    """Deterministic anomaly categories."""
    POINT = "POINT"                  # Single outlier observation
    CONTEXTUAL = "CONTEXTUAL"        # Normal value, abnormal for current context
    TEMPORAL = "TEMPORAL"            # Gaps, rapid transitions, abnormal duration
    TREND = "TREND"                  # Meaningful deviation from trend
    SEQUENCE = "SEQUENCE"            # Unexpected order of states
    MULTIVARIATE = "MULTIVARIATE"    # Unusual combination of multiple variables
    SEMANTIC = "SEMANTIC"            # Impossible or contextually invalid state/value combination


class AnomalyStatus(str, Enum):
    """Lifecycle states for detected anomalies."""
    DETECTED = "DETECTED"            # Anomaly currently observed
    CONFIRMED = "CONFIRMED"          # Confirmed by user or deterministic secondary check
    DISMISSED = "DISMISSED"          # Marked as non-anomalous (e.g. planned maintenance)
    EXPIRED = "EXPIRED"              # No longer actively detected/relevant
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA" # Not enough valid data to assess


class AnomalySeverity(str, Enum):
    """Deterministic severity levels."""
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DetectorMethod(str, Enum):
    """Mathematical methods for anomaly detection."""
    Z_SCORE = "Z_SCORE"              # Standard score against mean and std_dev
    MAD = "MAD"                      # Robust Z-Score using Median Absolute Deviation
    IQR = "IQR"                      # Interquartile Range multiplier
    MOVING_WINDOW = "MOVING_WINDOW"  # Rolling baseline aggregation
    RATE_OF_CHANGE = "RATE_OF_CHANGE"# Rapid delta detection


# =============================================================================
# 2. MODELS
# =============================================================================

class AnomalyBaseline(BaseModel):
    """
    A reproducible, deterministic baseline against which anomalies are assessed.
    """
    baseline_id: str = Field(..., description="Unique baseline identifier")
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    entity_id: str = Field(..., description="The entity this baseline applies to")
    metric: str = Field(..., description="The property or metric being monitored (e.g., vibration)")
    
    detector_method: DetectorMethod
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Configuration (e.g. threshold, window_size)")
    
    sample_count: int = Field(..., description="Number of valid samples used to compute this baseline")
    calculated_statistics: Dict[str, float] = Field(default_factory=dict, description="Computed metrics (e.g. mean, std_dev, median, mad)")
    
    context: Optional[str] = Field(None, description="Operating context for this baseline (e.g., 'production_mode=normal')")
    
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: int = Field(default=1, description="Explicit versioning for evolving baselines")


class AnomalyEvidence(BaseModel):
    """
    Cryptographically independent evidence capturing the exact state that triggered an anomaly.
    """
    observation_id: Optional[str] = None
    source: str = Field(default="system")
    source_timestamp: str = Field(..., description="Time the underlying observation occurred")
    metric: str = Field(...)
    value: Union[float, int, str, bool, dict]
    data_quality_status: QualityStatus = Field(default=QualityStatus.PASS)
    baseline_reference_id: Optional[str] = None
    context_snapshot: Dict[str, Any] = Field(default_factory=dict)


class AnomalyDetection(BaseModel):
    """
    A persistently recorded detection of anomalous behavior.
    """
    anomaly_id: str = Field(..., description="Unique anomaly identifier")
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    entity_id: str = Field(...)
    metric: str = Field(...)
    
    type: AnomalyType
    status: AnomalyStatus = Field(default=AnomalyStatus.DETECTED)
    severity: AnomalySeverity = Field(default=AnomalySeverity.INFO)
    
    detector_method: DetectorMethod
    anomaly_score: Optional[float] = Field(None, description="Deterministic mathematical score (e.g., Z-score distance)")
    
    evidence: List[AnomalyEvidence] = Field(default_factory=list)
    
    # Deduplication and Lifecycle
    first_detected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_detected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    occurrence_count: int = Field(default=1)
    
    fingerprint: str = Field(..., description="Deterministic hash/string identifying this exact condition for deduplication")


class AnomalyAssessmentScope(BaseModel):
    """
    Defines the scope of a requested anomaly assessment.
    """
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    entity_ids: Optional[List[str]] = None
    metrics: Optional[List[str]] = None
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None


class AnomalyAssessmentRun(BaseModel):
    """
    Records the outcome of a detection run.
    """
    run_id: str = Field(..., description="Unique run identifier")
    tenant_id: str
    scope: AnomalyAssessmentScope
    start_time: str
    completion_time: str
    baselines_evaluated: int = 0
    observations_evaluated: int = 0
    anomalies_detected: int = 0
    execution_duration_ms: int = 0


class AnomalyListResponse(BaseModel):
    anomalies: List[AnomalyDetection]
    total_count: int
