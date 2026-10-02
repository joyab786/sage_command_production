# backend/data/schemas/sensor_fusion_contract.py
"""
SageCommand V3 — Multimodal Sensor Fusion Intelligence Foundation Contracts (Prompt 27)

ANALYTICAL ONLY.
Combines heterogeneous industrial observations into a coherent analytical assessment.
Does NOT execute physical commands, write to PLCs, trigger work orders, actuate digital twins,
or mutate upstream operational or financial records.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, field_validator
import hashlib
import json


# =============================================================================
# 1. MODALITY ENUM (Section 5)
# =============================================================================

class Modality(str, Enum):
    """
    Explicit, controlled modalities for heterogeneous industrial sensor fusion.
    Every observation must identify its modality.
    """
    NUMERIC_TELEMETRY = "NUMERIC_TELEMETRY"
    VIBRATION = "VIBRATION"
    TEMPERATURE = "TEMPERATURE"
    PRESSURE = "PRESSURE"
    ELECTRICAL = "ELECTRICAL"
    ACOUSTIC = "ACOUSTIC"
    VISUAL = "VISUAL"
    THERMAL = "THERMAL"
    PROCESS = "PROCESS"
    EVENT = "EVENT"
    ANOMALY = "ANOMALY"
    DIGITAL_TWIN = "DIGITAL_TWIN"


# =============================================================================
# 2. MEASUREMENT TYPES (Section 6)
# =============================================================================

class MeasurementType(str, Enum):
    """
    Typed physical and qualitative measurement categories.
    No meaningless unitless physical measurements.
    """
    TEMPERATURE = "TEMPERATURE"
    PRESSURE = "PRESSURE"
    VIBRATION_RMS = "VIBRATION_RMS"
    VIBRATION_PEAK = "VIBRATION_PEAK"
    VIBRATION_ACCELERATION = "VIBRATION_ACCELERATION"
    VIBRATION_VELOCITY = "VIBRATION_VELOCITY"
    ACOUSTIC_LEVEL = "ACOUSTIC_LEVEL"
    ACOUSTIC_FREQUENCY = "ACOUSTIC_FREQUENCY"
    CURRENT = "CURRENT"
    VOLTAGE = "VOLTAGE"
    POWER = "POWER"
    FREQUENCY = "FREQUENCY"
    POWER_FACTOR = "POWER_FACTOR"
    FLOW = "FLOW"
    SPEED = "SPEED"
    TORQUE = "TORQUE"
    HUMIDITY = "HUMIDITY"
    PROCESS_RATE = "PROCESS_RATE"
    ENERGY = "ENERGY"
    QUALITY_MEASUREMENT = "QUALITY_MEASUREMENT"
    VISUAL_DEFECT = "VISUAL_DEFECT"
    THERMAL_HOTSPOT = "THERMAL_HOTSPOT"
    THERMAL_GRADIENT = "THERMAL_GRADIENT"
    GENERIC_NUMERIC = "GENERIC_NUMERIC"
    EVENT_OCCURRENCE = "EVENT_OCCURRENCE"
    ANOMALY_SCORE = "ANOMALY_SCORE"
    TWIN_STATE = "TWIN_STATE"


# =============================================================================
# 3. PROVENANCE ENUM (Section 8)
# =============================================================================

class SensorValueProvenance(str, Enum):
    """
    Established provenance semantics. Never convert simulated or estimated
    values into observed sensor values.
    """
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    SIMULATED = "SIMULATED"
    ESTIMATED = "ESTIMATED"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# 4. AGREEMENT & ALIGNMENT ENUMS (Section 10, 20)
# =============================================================================

class AgreementStatus(str, Enum):
    """
    Cross-modal agreement classification.
    """
    AGREEMENT = "AGREEMENT"
    PARTIAL_AGREEMENT = "PARTIAL_AGREEMENT"
    DISAGREEMENT = "DISAGREEMENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AlignmentStrategy(str, Enum):
    """
    Deterministic temporal alignment strategies.
    """
    EXACT = "EXACT"
    NEAREST = "NEAREST"
    WINDOW = "WINDOW"
    RESAMPLED = "RESAMPLED"


class FusionStrategy(str, Enum):
    """
    Deterministic numerical and contextual fusion methodologies.
    """
    WEIGHTED_EVIDENCE_FUSION = "WEIGHTED_EVIDENCE_FUSION"
    NORMALIZED_SCORE_FUSION = "NORMALIZED_SCORE_FUSION"
    CONSENSUS_FUSION = "CONSENSUS_FUSION"
    CONTEXTUAL_FUSION = "CONTEXTUAL_FUSION"


class SensorHealthStatus(str, Enum):
    """
    Analytical sensor health/reliability indicator.
    Analytical only — does NOT reconfigure sensors or PLCs.
    """
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    CONSTANT_VALUE = "CONSTANT_VALUE"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    NOISY = "NOISY"
    DISAGREEING = "DISAGREEING"
    UNKNOWN = "UNKNOWN"


class FusionConfidence(str, Enum):
    """
    Deterministic qualitative confidence levels.
    """
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class FusionUncertainty(str, Enum):
    """
    Deterministic qualitative uncertainty levels.
    """
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# 5. UNIT SAFETY & DETERMINISTIC CONVERSIONS (Section 7)
# =============================================================================

# Controlled unit synonym map (normalized upper-case)
UNIT_NORMALIZATION_MAP: Dict[str, str] = {
    "C": "CELSIUS",
    "°C": "CELSIUS",
    "CELSIUS": "CELSIUS",
    "F": "FAHRENHEIT",
    "°F": "FAHRENHEIT",
    "FAHRENHEIT": "FAHRENHEIT",
    "K": "KELVIN",
    "KELVIN": "KELVIN",
    "BAR": "BAR",
    "PSI": "PSI",
    "PA": "PA",
    "KPA": "KPA",
    "MPA": "MPA",
    "A": "AMPERE",
    "AMPERE": "AMPERE",
    "MA": "MILLIAMPERE",
    "MILLIAMPERE": "MILLIAMPERE",
    "V": "VOLT",
    "VOLT": "VOLT",
    "KV": "KILOVOLT",
    "KILOVOLT": "KILOVOLT",
    "MV": "MILLIVOLT",
    "MILLIVOLT": "MILLIVOLT",
    "W": "WATT",
    "WATT": "WATT",
    "KW": "KILOWATT",
    "KILOWATT": "KILOWATT",
    "MW": "MEGAWATT",
    "MEGAWATT": "MEGAWATT",
    "M/S^2": "M/S^2",
    "M/S2": "M/S^2",
    "G": "G_ACCEL",
    "MM/S": "MM/S",
    "M/S": "M/S",
    "RPM": "RPM",
    "HZ": "HZ",
    "KHZ": "KHZ",
    "DB": "DB",
    "DBA": "DBA",
    "PCT": "PERCENT",
    "%": "PERCENT",
    "PERCENT": "PERCENT",
    "L/MIN": "L/MIN",
    "M3/H": "M3/H",
    "NM": "NM",
}

# Unit family mapping for compatibility checks
UNIT_FAMILY_MAP: Dict[str, str] = {
    "CELSIUS": "TEMPERATURE",
    "FAHRENHEIT": "TEMPERATURE",
    "KELVIN": "TEMPERATURE",
    "BAR": "PRESSURE",
    "PSI": "PRESSURE",
    "PA": "PRESSURE",
    "KPA": "PRESSURE",
    "MPA": "PRESSURE",
    "AMPERE": "CURRENT",
    "MILLIAMPERE": "CURRENT",
    "VOLT": "VOLTAGE",
    "KILOVOLT": "VOLTAGE",
    "MILLIVOLT": "VOLTAGE",
    "WATT": "POWER",
    "KILOWATT": "POWER",
    "MEGAWATT": "POWER",
    "M/S^2": "ACCELERATION",
    "G_ACCEL": "ACCELERATION",
    "MM/S": "VELOCITY",
    "M/S": "VELOCITY",
    "RPM": "SPEED",
    "HZ": "FREQUENCY",
    "KHZ": "FREQUENCY",
    "DB": "ACOUSTIC",
    "DBA": "ACOUSTIC",
    "PERCENT": "RATIO",
    "L/MIN": "FLOW",
    "M3/H": "FLOW",
    "NM": "TORQUE",
}

# Canonical base unit per family
CANONICAL_BASE_UNITS: Dict[str, str] = {
    "TEMPERATURE": "CELSIUS",
    "PRESSURE": "BAR",
    "CURRENT": "AMPERE",
    "VOLTAGE": "VOLT",
    "POWER": "WATT",
    "ACCELERATION": "M/S^2",
    "VELOCITY": "MM/S",
    "SPEED": "RPM",
    "FREQUENCY": "HZ",
    "ACOUSTIC": "DB",
    "RATIO": "PERCENT",
    "FLOW": "L/MIN",
    "TORQUE": "NM",
}


def normalize_unit_string(unit: Optional[str]) -> Optional[str]:
    """Standardizes unit strings into canonical uppercase representation."""
    if not unit:
        return None
    cleaned = unit.strip().upper()
    return UNIT_NORMALIZATION_MAP.get(cleaned, cleaned)


def are_units_compatible(unit_a: Optional[str], unit_b: Optional[str]) -> bool:
    """Checks whether two units belong to the same physical dimension."""
    if not unit_a or not unit_b:
        return False
    norm_a = normalize_unit_string(unit_a)
    norm_b = normalize_unit_string(unit_b)
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True
    fam_a = UNIT_FAMILY_MAP.get(norm_a)
    fam_b = UNIT_FAMILY_MAP.get(norm_b)
    return fam_a is not None and fam_a == fam_b


def convert_unit(value: float, from_unit: str, to_unit: str) -> Tuple[Optional[float], bool, str]:
    """
    Deterministically converts compatible physical units.
    Returns (converted_value, is_success, explanation).
    Only defined explicit conversions are supported. Never guesses units.
    """
    norm_from = normalize_unit_string(from_unit)
    norm_to = normalize_unit_string(to_unit)

    if not norm_from or not norm_to:
        return None, False, f"Missing or invalid units: {from_unit} -> {to_unit}"

    if norm_from == norm_to:
        return float(value), True, "Identical units"

    fam_from = UNIT_FAMILY_MAP.get(norm_from)
    fam_to = UNIT_FAMILY_MAP.get(norm_to)

    if fam_from is None or fam_to is None or fam_from != fam_to:
        return None, False, f"Incompatible units: {from_unit} ({fam_from}) and {to_unit} ({fam_to})"

    val = float(value)

    # Temperature
    if fam_from == "TEMPERATURE":
        # Convert to Celsius first
        if norm_from == "CELSIUS":
            celsius = val
        elif norm_from == "FAHRENHEIT":
            celsius = (val - 32.0) * (5.0 / 9.0)
        elif norm_from == "KELVIN":
            celsius = val - 273.15
        else:
            return None, False, f"Unsupported temperature unit {norm_from}"

        # Convert from Celsius to target
        if norm_to == "CELSIUS":
            return round(celsius, 6), True, "Converted to Celsius"
        elif norm_to == "FAHRENHEIT":
            fahr = (celsius * (9.0 / 5.0)) + 32.0
            return round(fahr, 6), True, "Converted to Fahrenheit"
        elif norm_to == "KELVIN":
            return round(celsius + 273.15, 6), True, "Converted to Kelvin"

    # Pressure (base = BAR)
    elif fam_from == "PRESSURE":
        # Convert to BAR
        if norm_from == "BAR":
            bar = val
        elif norm_from == "PSI":
            bar = val * 0.06894757293168361
        elif norm_from == "PA":
            bar = val / 100000.0
        elif norm_from == "KPA":
            bar = val / 100.0
        elif norm_from == "MPA":
            bar = val * 10.0
        else:
            return None, False, f"Unsupported pressure unit {norm_from}"

        # Convert from BAR to target
        if norm_to == "BAR":
            return round(bar, 6), True, "Converted to bar"
        elif norm_to == "PSI":
            return round(bar * 14.503773773, 6), True, "Converted to psi"
        elif norm_to == "PA":
            return round(bar * 100000.0, 6), True, "Converted to Pa"
        elif norm_to == "KPA":
            return round(bar * 100.0, 6), True, "Converted to kPa"
        elif norm_to == "MPA":
            return round(bar / 10.0, 6), True, "Converted to MPa"

    # Current (base = AMPERE)
    elif fam_from == "CURRENT":
        amp = val if norm_from == "AMPERE" else val / 1000.0
        if norm_to == "AMPERE":
            return round(amp, 6), True, "Converted to A"
        elif norm_to == "MILLIAMPERE":
            return round(amp * 1000.0, 6), True, "Converted to mA"

    # Voltage (base = VOLT)
    elif fam_from == "VOLTAGE":
        if norm_from == "VOLT":
            volt = val
        elif norm_from == "KILOVOLT":
            volt = val * 1000.0
        elif norm_from == "MILLIVOLT":
            volt = val / 1000.0
        else:
            return None, False, f"Unsupported voltage unit {norm_from}"

        if norm_to == "VOLT":
            return round(volt, 6), True, "Converted to V"
        elif norm_to == "KILOVOLT":
            return round(volt / 1000.0, 6), True, "Converted to kV"
        elif norm_to == "MILLIVOLT":
            return round(volt * 1000.0, 6), True, "Converted to mV"

    # Power (base = WATT)
    elif fam_from == "POWER":
        if norm_from == "WATT":
            watt = val
        elif norm_from == "KILOWATT":
            watt = val * 1000.0
        elif norm_from == "MEGAWATT":
            watt = val * 1000000.0
        else:
            return None, False, f"Unsupported power unit {norm_from}"

        if norm_to == "WATT":
            return round(watt, 6), True, "Converted to W"
        elif norm_to == "KILOWATT":
            return round(watt / 1000.0, 6), True, "Converted to kW"
        elif norm_to == "MEGAWATT":
            return round(watt / 1000000.0, 6), True, "Converted to MW"

    # Acceleration (base = M/S^2)
    elif fam_from == "ACCELERATION":
        # 1 g = 9.80665 m/s^2
        acc = val if norm_from == "M/S^2" else val * 9.80665
        if norm_to == "M/S^2":
            return round(acc, 6), True, "Converted to m/s^2"
        elif norm_to == "G_ACCEL":
            return round(acc / 9.80665, 6), True, "Converted to g"

    # Frequency (base = HZ)
    elif fam_from == "FREQUENCY":
        hz = val if norm_from == "HZ" else val * 1000.0
        if norm_to == "HZ":
            return round(hz, 6), True, "Converted to Hz"
        elif norm_to == "KHZ":
            return round(hz / 1000.0, 6), True, "Converted to kHz"

    return None, False, f"Conversion from {norm_from} to {norm_to} is not implemented"


# =============================================================================
# 6. CORE DOMAIN MODELS (Section 4, 25, 26)
# =============================================================================

class SensorObservation(BaseModel):
    """
    A single typed industrial observation from a physical or virtual sensor.
    Carries full provenance, temporal bounds, and source metadata.
    """
    model_config = ConfigDict(extra="ignore")

    observation_id: str = Field(..., description="Unique observation identifier")
    tenant_id: str = Field(..., description="Tenant isolation boundary")
    workspace_id: str = Field(default="workspace_default")
    plant_id: Optional[str] = Field(default=None)
    entity_id: str = Field(..., description="Target industrial machine or asset identifier")
    entity_type: str = Field(default="MACHINE", description="Ontology entity type")
    sensor_id: str = Field(..., description="Reporting sensor/instrument identifier")
    sensor_type: Optional[str] = Field(default=None, description="Hardware or logical sensor classification")
    modality: Modality = Field(..., description="Observation modality")
    measurement_type: MeasurementType = Field(..., description="Physical or qualitative measurement category")
    value: Any = Field(..., description="Quantitative scalar, categorical label, or structured payload")
    unit: Optional[str] = Field(default=None, description="Explicit measurement unit")
    observed_at: str = Field(..., description="ISO-8601 UTC timestamp when observed")
    received_at: Optional[str] = Field(default=None, description="ISO-8601 UTC timestamp when ingested")
    source_reference: Optional[str] = Field(default=None, description="Originating device, topic, or edge gateway")
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.OBSERVED)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Source-reported confidence score")
    quality: float = Field(default=1.0, ge=0.0, le=1.0, description="Data Quality score (0.0 to 1.0)")
    temporal_validity: Optional[Dict[str, Any]] = Field(default=None)
    source_lineage: List[str] = Field(default_factory=list, description="Chain of source sensors to avoid double-counting")
    parent_observation_id: Optional[str] = Field(default=None, description="Parent observation if derived")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("observed_at timestamp must be a non-empty ISO-8601 string")
        return v.strip()


class NormalizedObservation(BaseModel):
    """
    Unit-compatible normalized observation for numerical comparison and aggregation.
    """
    model_config = ConfigDict(extra="ignore")

    observation_id: str
    sensor_id: str
    modality: Modality
    measurement_type: MeasurementType
    raw_value: Any
    raw_unit: Optional[str] = None
    normalized_value: Optional[float] = None
    normalized_unit: Optional[str] = None
    scaled_score: Optional[float] = None
    observed_at: str
    temporal_offset_seconds: float = 0.0
    provenance: SensorValueProvenance
    confidence: float = 1.0
    quality_score: float = 1.0
    is_valid: bool = True
    exclusion_reason: Optional[str] = None


class FusionEvidence(BaseModel):
    """
    Explainable evidence contributing to a fused observation.
    Must be fully traceable to source observation and lineage.
    """
    model_config = ConfigDict(extra="ignore")

    evidence_id: str = Field(..., description="Deterministic evidence identifier")
    modality: Modality
    source_type: str = Field(default="SENSOR", description="Originating source type")
    source_id: str = Field(..., description="Device or sensor identifier")
    observation_id: Optional[str] = None
    timestamp: str
    value: Any
    unit: Optional[str] = None
    normalized_value: Optional[float] = None
    confidence: float = 1.0
    quality: float = 1.0
    contribution: float = Field(default=0.0, description="Weighted contribution to fused score")
    provenance: SensorValueProvenance = SensorValueProvenance.OBSERVED
    explanation: str = ""
    is_independent: bool = True
    parent_evidence_id: Optional[str] = None
    source_lineage: List[str] = Field(default_factory=list)


class FusedObservation(BaseModel):
    """
    Deterministically calculated combined analytical observation.
    """
    model_config = ConfigDict(extra="ignore")

    fused_observation_id: str
    target_entity_id: str
    measurement_type: MeasurementType
    fused_value: Any
    unit: Optional[str] = None
    observed_window: Dict[str, str] = Field(default_factory=dict)
    contributing_modalities: List[Modality] = Field(default_factory=list)
    contributing_observations: List[str] = Field(default_factory=list)
    fusion_method: FusionStrategy
    agreement_score: float = 1.0
    confidence: FusionConfidence = FusionConfidence.MEDIUM
    uncertainty: FusionUncertainty = FusionUncertainty.LOW
    provenance: SensorValueProvenance = SensorValueProvenance.OBSERVED
    evidence: List[FusionEvidence] = Field(default_factory=list)


class CrossModalCorrelation(BaseModel):
    """
    Cross-modal relationship or correlation between two observation streams.
    Does not claim causal certainty.
    """
    model_config = ConfigDict(extra="ignore")

    correlation_id: str
    modality_a: Modality
    modality_b: Modality
    sensor_id_a: str
    sensor_id_b: str
    measurement_type_a: MeasurementType
    measurement_type_b: MeasurementType
    method: str = Field(default="PEARSON", description="Correlation method")
    correlation_coefficient: Optional[float] = None
    sample_count: int = 0
    is_significant: bool = False
    coincident_events: int = 0
    directional_agreement: Optional[bool] = None
    explanation: str = ""


class CrossModalAgreement(BaseModel):
    """
    Deterministic agreement assessment across multiple modalities.
    """
    model_config = ConfigDict(extra="ignore")

    agreement_id: str
    target_entity_id: str
    modalities: List[Modality]
    status: AgreementStatus
    agreement_score: float = Field(default=1.0, ge=0.0, le=1.0)
    supporting_modalities: List[Modality] = Field(default_factory=list)
    conflicting_modalities: List[Modality] = Field(default_factory=list)
    neutral_modalities: List[Modality] = Field(default_factory=list)
    details: str = ""


class SensorHealthIndicator(BaseModel):
    """
    Analytical sensor quality indicator.
    Does not actuate or disable physical sensors.
    """
    model_config = ConfigDict(extra="ignore")

    sensor_id: str
    modality: Modality
    status: SensorHealthStatus
    reliability_score: float = Field(default=1.0, ge=0.0, le=1.0)
    sample_count: int = 0
    stale_seconds: Optional[float] = None
    noise_level: Optional[float] = None
    constant_value_detected: bool = False
    disagreement_count: int = 0
    findings: List[str] = Field(default_factory=list)


class WeightingRule(BaseModel):
    """
    Explicit, versioned weighting rule. No hidden weights or LLM changes.
    """
    model_config = ConfigDict(extra="ignore")

    factor_name: str
    modality: Modality
    weight: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    version: str = "1.0"


class EvaluationWindow(BaseModel):
    """
    Bounded temporal evaluation window.
    """
    model_config = ConfigDict(extra="ignore")

    start_time: str
    end_time: str
    duration_seconds: float


class FusionAssessment(BaseModel):
    """
    Top-level deterministic multimodal sensor fusion assessment.
    Contains raw and normalized observations, cross-modal relationships,
    evidence, confidence, uncertainty, quality, context, and fingerprint.
    """
    model_config = ConfigDict(extra="ignore")

    fusion_assessment_id: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    target_entity_id: str
    target_entity_type: str = "MACHINE"
    assessment_timestamp: str
    evaluation_window: EvaluationWindow
    observations: List[SensorObservation] = Field(default_factory=list)
    modalities_present: List[Modality] = Field(default_factory=list)
    modalities_missing: List[Modality] = Field(default_factory=list)
    normalized_observations: List[NormalizedObservation] = Field(default_factory=list)
    fused_observations: List[FusedObservation] = Field(default_factory=list)
    correlations: List[CrossModalCorrelation] = Field(default_factory=list)
    agreements: List[CrossModalAgreement] = Field(default_factory=list)
    disagreements: List[CrossModalAgreement] = Field(default_factory=list)
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    sensor_health: List[SensorHealthIndicator] = Field(default_factory=list)
    evidence: List[FusionEvidence] = Field(default_factory=list)
    confidence: FusionConfidence = FusionConfidence.UNKNOWN
    uncertainty: FusionUncertainty = FusionUncertainty.HIGH
    provenance: SensorValueProvenance = SensorValueProvenance.OBSERVED
    data_quality_summary: Dict[str, Any] = Field(default_factory=dict)
    digital_twin_context: Optional[Dict[str, Any]] = None
    ontology_context: Optional[Dict[str, Any]] = None
    knowledge_graph_context: Optional[Dict[str, Any]] = None
    limitations: List[str] = Field(default_factory=list)
    methodology: str = "DETERMINISTIC_MULTIMODAL_FUSION_V1"
    model_version: str = "1.0.0"
    schema_version: str = "1.0"
    input_fingerprint: str
    execution_boundary_verified: bool = True


# =============================================================================
# 7. API REQUEST & RESPONSE SCHEMAS
# =============================================================================

class SensorFusionAnalyzeRequest(BaseModel):
    """
    Payload for POST /api/v3/sensor-fusion/analyze.
    """
    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    workspace_id: str = "workspace_default"
    plant_id: Optional[str] = None
    target_entity_id: str
    target_entity_type: str = "MACHINE"
    assessment_timestamp: Optional[str] = None
    evaluation_window_seconds: int = 3600
    alignment_strategy: AlignmentStrategy = AlignmentStrategy.WINDOW
    temporal_tolerance_seconds: float = 60.0
    fusion_strategy: FusionStrategy = FusionStrategy.WEIGHTED_EVIDENCE_FUSION
    observations: List[SensorObservation] = Field(default_factory=list)
    include_digital_twin: bool = True
    include_ontology: bool = True
    include_knowledge_graph: bool = True
    include_anomalies: bool = True
    include_data_quality: bool = True


class SensorFusionSummaryItem(BaseModel):
    """
    Summary view of a persisted fusion assessment.
    """
    model_config = ConfigDict(extra="ignore")

    fusion_assessment_id: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    target_entity_id: str
    assessment_timestamp: str
    confidence: FusionConfidence
    uncertainty: FusionUncertainty
    provenance: SensorValueProvenance
    modalities_present: List[Modality]
    agreement_status: AgreementStatus
    observation_count: int
    fused_observation_count: int
    input_fingerprint: str


class SensorFusionListResponse(BaseModel):
    """
    Paginated list response for GET /api/v3/sensor-fusion/assessments.
    """
    model_config = ConfigDict(extra="ignore")

    assessments: List[SensorFusionSummaryItem]
    total_count: int


class SensorEntitySummaryResponse(BaseModel):
    """
    Aggregated summary for GET /api/v3/sensor-fusion/entities/{entity_id}/summary.
    """
    model_config = ConfigDict(extra="ignore")

    target_entity_id: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    latest_assessment_id: Optional[str] = None
    latest_assessment_timestamp: Optional[str] = None
    confidence: FusionConfidence = FusionConfidence.UNKNOWN
    uncertainty: FusionUncertainty = FusionUncertainty.HIGH
    modalities_present: List[Modality] = Field(default_factory=list)
    sensor_health: List[SensorHealthIndicator] = Field(default_factory=list)
    latest_fused_observations: List[FusedObservation] = Field(default_factory=list)
    active_anomalies_count: int = 0
    total_assessments_recorded: int = 0


# =============================================================================
# 8. DETERMINISTIC SHA-256 FINGERPRINT CALCULATION (Section 34)
# =============================================================================

def compute_sensor_fusion_fingerprint(
    tenant_id: str,
    workspace_id: str,
    plant_id: Optional[str],
    target_entity_id: str,
    assessment_timestamp: str,
    evaluation_window_seconds: int,
    observations: List[SensorObservation],
    methodology: str = "DETERMINISTIC_MULTIMODAL_FUSION_V1",
    model_version: str = "1.0.0",
    fusion_strategy: str = "WEIGHTED_EVIDENCE_FUSION",
    weights: Optional[List[WeightingRule]] = None,
    context_keys: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Computes a canonical SHA-256 hash over all material inputs.
    Invariants:
    - Same input -> same fingerprint
    - Material input change -> different fingerprint
    - Reordered input -> same fingerprint
    - No dependence on random IDs, process IDs, or system clock.
    """
    # Canonicalize and sort observations
    sorted_obs = []
    for obs in observations:
        norm_unit = normalize_unit_string(obs.unit) or ""
        # Stringify value deterministically
        val_str = str(obs.value) if not isinstance(obs.value, float) else f"{obs.value:.6f}"
        sorted_obs.append({
            "sensor_id": obs.sensor_id.strip(),
            "modality": obs.modality.value,
            "measurement_type": obs.measurement_type.value,
            "observed_at": obs.observed_at.strip(),
            "value": val_str,
            "unit": norm_unit,
            "provenance": obs.provenance.value,
            "confidence": f"{obs.confidence:.4f}",
            "quality": f"{obs.quality:.4f}",
            "parent_id": obs.parent_observation_id or "",
            "lineage": sorted(obs.source_lineage or []),
        })

    # Sort deterministically by (sensor_id, modality, measurement_type, observed_at, value)
    sorted_obs.sort(key=lambda x: (
        x["sensor_id"],
        x["modality"],
        x["measurement_type"],
        x["observed_at"],
        x["value"]
    ))

    # Canonicalize weights
    weight_list = []
    if weights:
        for w in weights:
            weight_list.append({
                "factor_name": w.factor_name,
                "modality": w.modality.value,
                "weight": f"{w.weight:.4f}",
                "version": w.version,
            })
        weight_list.sort(key=lambda x: (x["factor_name"], x["modality"]))

    canonical_payload = {
        "tenant_id": tenant_id.strip(),
        "workspace_id": (workspace_id or "workspace_default").strip(),
        "plant_id": (plant_id or "").strip(),
        "target_entity_id": target_entity_id.strip(),
        "assessment_timestamp": assessment_timestamp.strip(),
        "evaluation_window_seconds": int(evaluation_window_seconds),
        "methodology": methodology.strip(),
        "model_version": model_version.strip(),
        "fusion_strategy": fusion_strategy.strip(),
        "observations": sorted_obs,
        "weights": weight_list,
        "context_keys": {k: str(v) for k, v in sorted((context_keys or {}).items())},
    }

    raw_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
