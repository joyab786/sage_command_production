# backend/data/schemas/outcome_learning_contract.py
"""
SageCommand V3 — Closed-Loop Learning: Outcome Evaluation, Prediction Accuracy & Governed Feedback
Prompt 39 Foundation Contracts

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Defines immutable prediction snapshots, observed outcome records, deterministic
prediction-outcome evaluations, bounded aggregate metrics, and governed read-only
decision-support learning context.

Cardinal Invariants:
1. Predictions preserve what was expected BEFORE the outcome was observed.
2. An observed outcome is NOT automatically verified; only authoritative verification
   evidence enables an outcome to become eligible for future learning.
3. Outcome evaluation is deterministic, typed, and mathematically sound (no division by zero).
4. Evaluation history is append-only, durable, scope-isolated, and idempotent.
5. Historical learning context is strictly read-only decision support — never an execution grant.
6. Zero autonomous model-weight mutation, online reinforcement learning, or policy rewrite.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import uuid
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

try:
    from data.schemas.verification_contract import (
        validate_identifier,
        _validate_safe_text,
        _scan_for_secrets,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from data.schemas.event_contract import EventCategory, EventSeverity, EventLifecycle
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.verification_contract import (
        validate_identifier,
        _validate_safe_text,
        _scan_for_secrets,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from backend.data.schemas.event_contract import EventCategory, EventSeverity, EventLifecycle

SCHEMA_VERSION = "3.0.0"
EVALUATION_POLICY_VERSION = "1.0.0"
METRIC_IMPLEMENTATION_VERSION = "1.0.0"


# =============================================================================
# 1. CENTRALIZED ENUMS
# =============================================================================

class PredictionType(str, Enum):
    """Supported prediction domains with well-defined expectation and comparison semantics."""
    DEMAND_FORECAST = "DEMAND_FORECAST"
    RECOVERY_DURATION = "RECOVERY_DURATION"
    MAINTENANCE_RISK = "MAINTENANCE_RISK"
    OPERATIONAL_COST = "OPERATIONAL_COST"
    MISSION_CRITERION = "MISSION_CRITERION"
    ENERGY_CONSUMPTION = "ENERGY_CONSUMPTION"
    PRODUCTION_THROUGHPUT = "PRODUCTION_THROUGHPUT"


class OutcomeVerificationStatus(str, Enum):
    """
    Authoritative verification status of an observed outcome.
    Distinguishes observation from authoritative verification.
    """
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INDETERMINATE = "INDETERMINATE"
    REJECTED = "REJECTED"


class OutcomeEligibilityStatus(str, Enum):
    """Deterministic eligibility outcome for prediction-outcome evaluation."""
    ELIGIBLE = "ELIGIBLE"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    ALREADY_EVALUATED = "ALREADY_EVALUATED"


class OutcomeEligibilityReason(str, Enum):
    """Safe, machine-readable deterministic reason codes for outcome eligibility."""
    ELIGIBLE = "ELIGIBLE"
    PREDICTION_NOT_FOUND = "PREDICTION_NOT_FOUND"
    UNSUPPORTED_PREDICTION_TYPE = "UNSUPPORTED_PREDICTION_TYPE"
    OUTCOME_NOT_VERIFIED = "OUTCOME_NOT_VERIFIED"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    INVALID_EVALUATION_WINDOW = "INVALID_EVALUATION_WINDOW"
    DATA_MODE_MISMATCH = "DATA_MODE_MISMATCH"
    INVALIDATED_SOURCE = "INVALIDATED_SOURCE"
    DUPLICATE_EVALUATION = "DUPLICATE_EVALUATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    TIMING_VIOLATION = "TIMING_VIOLATION"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    DISABLED = "DISABLED"


class EvaluationStatus(str, Enum):
    """Deterministic evaluation outcome status."""
    EVALUATED = "EVALUATED"
    PARTIALLY_EVALUATED = "PARTIALLY_EVALUATED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class DirectionalBias(str, Enum):
    """Directional classification of prediction error."""
    OVER_PREDICTED = "OVER_PREDICTED"
    UNDER_PREDICTED = "UNDER_PREDICTED"
    MATCHED = "MATCHED"
    NOT_DETERMINABLE = "NOT_DETERMINABLE"


class DataMode(str, Enum):
    """Operational data mode boundary."""
    REAL = "REAL"
    SIMULATION = "SIMULATION"
    HYBRID = "HYBRID"


# =============================================================================
# 2. HELPER FUNCTIONS
# =============================================================================

def _validate_scope_identifier(v: str, field_name: str) -> str:
    """Validates scope identifier and rejects fabricated or manufactured identifiers."""
    validate_identifier(v, field_name)
    normalized = v.strip().lower()
    if normalized in ("global", "unknown", "default"):
        raise ValueError(f"Manufactured or wildcard scope '{v}' is prohibited for '{field_name}'.")
    return v.strip()


def _parse_utc_iso(ts_str: str) -> datetime:
    """Parses ISO timestamp string into UTC datetime."""
    clean_ts = ts_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =============================================================================
# 3. PREDICTION SNAPSHOT CONTRACT
# =============================================================================

class PredictionSnapshot(BaseModel):
    """
    Immutable snapshot preserving what the system expected BEFORE the outcome was observed.
    Once recorded, this record is append-only and cannot be overwritten.
    """
    model_config = ConfigDict(extra="forbid")

    prediction_id: str = Field(..., max_length=128, description="Canonical prediction identifier")
    schema_version: str = Field(default=SCHEMA_VERSION, max_length=32)
    prediction_type: PredictionType = Field(..., description="Strongly typed prediction domain")
    target_reference: str = Field(..., max_length=128, description="Target entity, mission, asset, or criterion ID")
    predicted_at: str = Field(..., description="ISO-8601 UTC timestamp when prediction was generated")
    
    # Expected outcome
    expected_value: Any = Field(..., description="Original expected value (numeric, string, bool, or dict)")
    expected_unit: Optional[str] = Field(default=None, max_length=32, description="Physical/operational unit (e.g. hours, units, usd)")
    forecast_horizon: Optional[str] = Field(default=None, max_length=64, description="Forecast horizon, e.g. P7D, SHORT_TERM")
    evaluation_window_start: Optional[str] = Field(default=None, description="ISO-8601 UTC evaluation window start")
    evaluation_window_end: Optional[str] = Field(default=None, description="ISO-8601 UTC evaluation window end")
    
    # Provenance and Model Context
    prediction_method: Optional[str] = Field(default=None, max_length=128, description="Method/algorithm reference")
    model_version: Optional[str] = Field(default=None, max_length=64, description="Model, rule, or estimator version")
    prediction_provenance: str = Field(..., max_length=128, description="Originating service or source")
    data_mode: DataMode = Field(default=DataMode.REAL, description="Real, simulation, or hybrid data mode")

    # Authoritative Scopes
    tenant_id: str = Field(..., max_length=128)
    workspace_id: str = Field(..., max_length=128)
    plant_id: str = Field(..., max_length=128)

    # Reference Linkage
    source_references: Dict[str, Any] = Field(default_factory=dict, description="Related object IDs, event IDs, etc.")
    is_superseded: bool = Field(default=False, description="Whether this prediction was superseded by a later revision")
    superseded_by: Optional[str] = Field(default=None, max_length=128, description="Newer prediction ID if superseded")
    details: Dict[str, Any] = Field(default_factory=dict, description="Auxiliary structured context")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 UTC record creation timestamp"
    )

    @field_validator("prediction_id")
    @classmethod
    def val_pred_id(cls, v: str) -> str:
        return validate_identifier(v, "prediction_id")

    @field_validator("target_reference")
    @classmethod
    def val_target_ref(cls, v: str) -> str:
        return validate_identifier(v, "target_reference")

    @field_validator("tenant_id")
    @classmethod
    def val_tenant(cls, v: str) -> str:
        return _validate_scope_identifier(v, "tenant_id")

    @field_validator("workspace_id")
    @classmethod
    def val_workspace(cls, v: str) -> str:
        return _validate_scope_identifier(v, "workspace_id")

    @field_validator("plant_id")
    @classmethod
    def val_plant(cls, v: str) -> str:
        return _validate_scope_identifier(v, "plant_id")

    @field_validator("expected_unit", "prediction_method", "model_version", "prediction_provenance")
    @classmethod
    def val_safe_str(cls, v: Optional[str]) -> Optional[str]:
        if v:
            _scan_for_secrets(v, "text_field")
            _validate_safe_text(v, "text_field")
        return v

    def compute_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint binding expectation and scope."""
        canonical_dict = {
            "schema_version": str(self.schema_version),
            "prediction_type": str(self.prediction_type.value),
            "target_reference": str(self.target_reference),
            "predicted_at": str(self.predicted_at),
            "expected_value": self.expected_value,
            "expected_unit": str(self.expected_unit or ""),
            "forecast_horizon": str(self.forecast_horizon or ""),
            "evaluation_window_start": str(self.evaluation_window_start or ""),
            "evaluation_window_end": str(self.evaluation_window_end or ""),
            "prediction_method": str(self.prediction_method or ""),
            "model_version": str(self.model_version or ""),
            "prediction_provenance": str(self.prediction_provenance),
            "data_mode": str(self.data_mode.value),
            "tenant_id": str(self.tenant_id),
            "workspace_id": str(self.workspace_id),
            "plant_id": str(self.plant_id),
        }
        canonical_bytes = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()


# =============================================================================
# 4. OBSERVED OUTCOME CONTRACT
# =============================================================================

class ObservedOutcome(BaseModel):
    """
    Record of an observed physical/operational outcome.
    Must maintain explicit verification status and evidence provenance.
    """
    model_config = ConfigDict(extra="forbid")

    outcome_id: str = Field(..., max_length=128, description="Canonical outcome identifier")
    schema_version: str = Field(default=SCHEMA_VERSION, max_length=32)
    prediction_id: Optional[str] = Field(default=None, max_length=128, description="Associated prediction ID if direct")
    target_reference: str = Field(..., max_length=128, description="Target entity, mission, asset, or criterion ID")
    outcome_type: str = Field(..., max_length=128, description="Outcome classification (e.g. DEMAND_OBSERVATION, ACTUAL_COST)")
    observed_at: str = Field(..., description="ISO-8601 UTC timestamp when outcome physically occurred/was observed")
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 UTC timestamp when outcome was recorded in SageCommand"
    )
    
    # Observed Value
    observed_value: Any = Field(..., description="Actual observed outcome value")
    unit: Optional[str] = Field(default=None, max_length=32, description="Physical/operational unit")
    
    # Evidence & Verification Linkage
    source_references: Dict[str, Any] = Field(default_factory=dict, description="References to telemetry, events, or sensors")
    verification_reference: Optional[str] = Field(default=None, max_length=128, description="Verification run ID or finding ID")
    verification_status: OutcomeVerificationStatus = Field(
        default=OutcomeVerificationStatus.OBSERVED,
        description="Authoritative verification status (OBSERVED is not yet VERIFIED)"
    )
    is_diagnostic: bool = Field(default=False, description="True if verification was diagnostic only")
    is_invalidated: bool = Field(default=False, description="True if evidence was subsequently invalidated")
    provenance: str = Field(..., max_length=128, description="Evidence source system or sensor feed")
    data_mode: DataMode = Field(default=DataMode.REAL, description="Real, simulation, or hybrid")

    # Authoritative Scopes
    tenant_id: str = Field(..., max_length=128)
    workspace_id: str = Field(..., max_length=128)
    plant_id: str = Field(..., max_length=128)

    correlation_id: Optional[str] = Field(default=None, max_length=128)
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    @field_validator("outcome_id")
    @classmethod
    def val_outc_id(cls, v: str) -> str:
        return validate_identifier(v, "outcome_id")

    @field_validator("target_reference")
    @classmethod
    def val_target_ref(cls, v: str) -> str:
        return validate_identifier(v, "target_reference")

    @field_validator("prediction_id", "verification_reference", "correlation_id")
    @classmethod
    def val_opt_ids(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return validate_identifier(v, "id_field")
        return v

    @field_validator("tenant_id")
    @classmethod
    def val_tenant(cls, v: str) -> str:
        return _validate_scope_identifier(v, "tenant_id")

    @field_validator("workspace_id")
    @classmethod
    def val_workspace(cls, v: str) -> str:
        return _validate_scope_identifier(v, "workspace_id")

    @field_validator("plant_id")
    @classmethod
    def val_plant(cls, v: str) -> str:
        return _validate_scope_identifier(v, "plant_id")

    @field_validator("unit", "provenance", "outcome_type")
    @classmethod
    def val_safe_str(cls, v: Optional[str]) -> Optional[str]:
        if v:
            _scan_for_secrets(v, "text_field")
            _validate_safe_text(v, "text_field")
        return v

    def compute_fingerprint(self) -> str:
        """Computes deterministic SHA-256 fingerprint binding observation and scope."""
        canonical_dict = {
            "schema_version": str(self.schema_version),
            "target_reference": str(self.target_reference),
            "outcome_type": str(self.outcome_type),
            "observed_at": str(self.observed_at),
            "observed_value": self.observed_value,
            "unit": str(self.unit or ""),
            "verification_reference": str(self.verification_reference or ""),
            "verification_status": str(self.verification_status.value),
            "is_diagnostic": 1 if self.is_diagnostic else 0,
            "provenance": str(self.provenance),
            "data_mode": str(self.data_mode.value),
            "tenant_id": str(self.tenant_id),
            "workspace_id": str(self.workspace_id),
            "plant_id": str(self.plant_id),
        }
        canonical_bytes = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()


# =============================================================================
# 5. PREDICTION-OUTCOME EVALUATION CONTRACT
# =============================================================================

class PredictionOutcomeEvaluation(BaseModel):
    """
    Durable, immutable record comparing a prediction snapshot against an observed outcome.
    Evaluations are append-only. Re-evaluations link to prior evaluation IDs.
    """
    model_config = ConfigDict(extra="forbid")

    evaluation_id: str = Field(..., max_length=128, description="Canonical evaluation identifier")
    schema_version: str = Field(default=SCHEMA_VERSION, max_length=32)
    prediction_id: str = Field(..., max_length=128)
    outcome_id: str = Field(..., max_length=128)
    
    evaluation_status: EvaluationStatus = Field(...)
    eligibility_reason: str = Field(..., max_length=64)
    evaluation_policy_version: str = Field(default=EVALUATION_POLICY_VERSION, max_length=32)
    metric_implementation_version: str = Field(default=METRIC_IMPLEMENTATION_VERSION, max_length=32)
    
    prediction_type: PredictionType = Field(...)
    target_reference: str = Field(..., max_length=128)
    
    # Values compared
    predicted_value: Any = Field(...)
    observed_value: Any = Field(...)
    unit: Optional[str] = Field(default=None, max_length=32)
    comparison_semantics: str = Field(..., max_length=64, description="NUMERIC_ERROR, CATEGORICAL_EXACT_MATCH, etc.")

    # Calculated Metrics (None when mathematically invalid or not applicable)
    absolute_error: Optional[float] = Field(default=None, description="|y - y_hat|")
    signed_error: Optional[float] = Field(default=None, description="y - y_hat")
    relative_error: Optional[float] = Field(default=None, description="|y - y_hat| / |y|; None when y == 0")
    directional_bias: Optional[DirectionalBias] = Field(default=None)
    exact_match: Optional[bool] = Field(default=None, description="Exact categorical or boolean equality")

    # Verification & Learning Governance Linkage
    verification_reference: Optional[str] = Field(default=None, max_length=128)
    is_diagnostic: bool = Field(default=False)
    eligible_for_learning: bool = Field(default=False, description="True only if verified authoritative real-world data")
    learning_ineligibility_reason: Optional[str] = Field(default=None, max_length=64)
    provenance: str = Field(default="prediction_outcome_evaluator", max_length=128)
    data_mode: DataMode = Field(default=DataMode.REAL)

    # Scopes
    tenant_id: str = Field(..., max_length=128)
    workspace_id: str = Field(..., max_length=128)
    plant_id: str = Field(..., max_length=128)

    # Provenance & Audit
    prior_evaluation_id: Optional[str] = Field(default=None, max_length=128, description="Linkage if re-evaluated")
    reevaluation_reason: Optional[str] = Field(default=None, max_length=256)
    idempotency_key: str = Field(..., max_length=128)
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    correlation_id: Optional[str] = Field(default=None, max_length=128)
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("evaluation_id", "prediction_id", "outcome_id")
    @classmethod
    def val_canonical_ids(cls, v: str) -> str:
        return validate_identifier(v, "id_field")

    @field_validator("prior_evaluation_id", "verification_reference", "correlation_id")
    @classmethod
    def val_opt_ids(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return validate_identifier(v, "id_field")
        return v

    @field_validator("tenant_id")
    @classmethod
    def val_tenant(cls, v: str) -> str:
        return _validate_scope_identifier(v, "tenant_id")

    @field_validator("workspace_id")
    @classmethod
    def val_workspace(cls, v: str) -> str:
        return _validate_scope_identifier(v, "workspace_id")

    @field_validator("plant_id")
    @classmethod
    def val_plant(cls, v: str) -> str:
        return _validate_scope_identifier(v, "plant_id")

    @field_validator("reevaluation_reason", "comparison_semantics")
    @classmethod
    def val_safe_str(cls, v: Optional[str]) -> Optional[str]:
        if v:
            _scan_for_secrets(v, "text_field")
            _validate_safe_text(v, "text_field")
        return v


# =============================================================================
# 6. AGGREGATE METRICS SUMMARY CONTRACT
# =============================================================================

class AggregateMetricsSummary(BaseModel):
    """
    Bounded, deterministic metrics aggregate calculated from eligible evaluations.
    Explicitly reports sample counts and insufficient-data status.
    """
    model_config = ConfigDict(extra="forbid")

    prediction_type: PredictionType = Field(...)
    tenant_id: str = Field(...)
    workspace_id: str = Field(...)
    plant_id: Optional[str] = Field(default=None)
    data_mode: DataMode = Field(default=DataMode.REAL)
    model_version: Optional[str] = Field(default=None)
    
    window_start: Optional[str] = Field(default=None)
    window_end: Optional[str] = Field(default=None)

    total_evaluations: int = Field(default=0, ge=0)
    eligible_sample_count: int = Field(default=0, ge=0)
    excluded_evaluations: int = Field(default=0, ge=0)
    sample_status: str = Field(..., description="SUFFICIENT_DATA or INSUFFICIENT_DATA")
    min_sample_threshold: int = Field(default=5, ge=1)

    # Numeric Aggregates (None when insufficient data or non-numeric)
    mean_absolute_error: Optional[float] = Field(default=None)
    mean_absolute_percentage_error: Optional[float] = Field(default=None)
    root_mean_squared_error: Optional[float] = Field(default=None)
    signed_mean_error: Optional[float] = Field(default=None, description="Signed average error / systematic bias")

    # Directional Counts
    over_predicted_count: int = Field(default=0, ge=0)
    under_predicted_count: int = Field(default=0, ge=0)
    exact_matched_count: int = Field(default=0, ge=0)
    exact_match_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Exclusions Breakdown
    unverified_count: int = Field(default=0, ge=0)
    deferred_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)

    unit: Optional[str] = Field(default=None)
    metric_implementation_version: str = Field(default=METRIC_IMPLEMENTATION_VERSION)
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


# =============================================================================
# 7. GOVERNED LEARNING CONTEXT CONTRACT
# =============================================================================

class GovernedLearningContext(BaseModel):
    """
    Controlled, read-only historical evaluation context provided to future decision-support.
    Provides verifiable evidence without granting execution or model-mutating authority.
    """
    model_config = ConfigDict(extra="forbid")

    prediction_type: PredictionType = Field(...)
    tenant_id: str = Field(...)
    workspace_id: str = Field(...)
    plant_id: Optional[str] = Field(default=None)
    model_version: Optional[str] = Field(default=None)
    data_mode: DataMode = Field(default=DataMode.REAL)

    sample_count: int = Field(default=0, ge=0)
    evaluation_status: str = Field(..., description="SUFFICIENT_DATA or INSUFFICIENT_DATA")
    mean_absolute_error: Optional[float] = Field(default=None)
    mean_absolute_percentage_error: Optional[float] = Field(default=None)
    signed_mean_error: Optional[float] = Field(default=None)
    directional_tendency: Optional[str] = Field(default=None, description="OVER_PREDICTING, UNDER_PREDICTING, BALANCED, etc.")
    unit: Optional[str] = Field(default=None)

    window_start: Optional[str] = Field(default=None)
    window_end: Optional[str] = Field(default=None)
    provenance: str = Field(default="verified_outcome_evaluations")
    limitations: List[str] = Field(default_factory=list)
    retrieved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
