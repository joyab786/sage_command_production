# backend/data/schemas/data_quality_contract.py
"""
Data Quality Domain Contracts.
Provides strong typing for rules, evaluations, issues, and assessment runs.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class QualityDimension(str, Enum):
    COMPLETENESS = "COMPLETENESS"
    VALIDITY = "VALIDITY"
    CONSISTENCY = "CONSISTENCY"
    UNIQUENESS = "UNIQUENESS"
    FRESHNESS = "FRESHNESS"
    ACCURACY = "ACCURACY"
    PROVENANCE = "PROVENANCE"
    INTEGRITY = "INTEGRITY"
    CONFORMITY = "CONFORMITY"
    COVERAGE = "COVERAGE"

class QualityStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"

class QualitySeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class IssueLifecycle(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"

class QualityRule(BaseModel):
    rule_id: str
    name: str
    description: str
    dimension: QualityDimension
    entity_type: Optional[str] = None
    field: Optional[str] = None
    relationship_type: Optional[str] = None
    severity: QualitySeverity = QualitySeverity.MEDIUM
    threshold: Optional[Any] = None
    enabled: bool = True
    version: int = 1
    tenant_id: Optional[str] = None  # None implies system-wide rule
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class QualityResult(BaseModel):
    rule_id: str
    rule_version: int
    dimension: QualityDimension
    status: QualityStatus
    severity: QualitySeverity
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    field: Optional[str] = None
    relationship_id: Optional[str] = None
    observed_value: Optional[str] = None
    expected_value: Optional[str] = None
    evidence: str
    source: str
    assessed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class QualityIssue(BaseModel):
    issue_id: str
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    entity_id: Optional[str] = None
    relationship_id: Optional[str] = None
    dimension: QualityDimension
    rule_id: str
    severity: QualitySeverity
    status: IssueLifecycle
    evidence: str
    first_detected_at: str
    last_detected_at: str
    occurrence_count: int
    source: str
    resolution_metadata: Optional[Dict[str, Any]] = None

class AssessmentScope(BaseModel):
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    entity_types: Optional[List[str]] = None
    dimensions: Optional[List[QualityDimension]] = None

class AssessmentRun(BaseModel):
    assessment_id: str
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    scope: AssessmentScope
    start_time: str
    completion_time: Optional[str] = None
    rules_evaluated: int = 0
    entities_evaluated: int = 0
    counts_by_dimension: Dict[str, int] = Field(default_factory=dict)
    counts_by_status: Dict[str, int] = Field(default_factory=dict)
    overall_score: float = 0.0
    execution_duration_ms: int = 0
    engine_version: str = "v3.0.0"

class AssessmentRequest(BaseModel):
    scope: AssessmentScope

class AssessmentResponse(BaseModel):
    assessment: AssessmentRun
    results: List[QualityResult]
    new_issues: int
    resolved_issues: int

class IssueListResponse(BaseModel):
    issues: List[QualityIssue]
    total_count: int
