"""
backend/data/schemas/sustainability_contract.py

SageCommand V3 -- Sustainability Intelligence Domain Contract (Prompt 26)

ANALYTICAL ONLY. This module defines pure data contracts for sustainability
impact assessment. It does NOT execute, mutate, or trigger any operational,
financial, environmental-control, procurement, regulatory-filing, or physical
systems.

Sustainability Intelligence is an analytical system. It does not directly
control physical systems, execute remediation, purchase offsets, submit
regulatory filings, or mutate operational/financial records.

Prompt 7 additions: Explicit Assessment Input Contract
    SustainabilityMeasurement         -- §7.2 typed measurements
    SustainabilityActivityData        -- §7.3 typed activity data
    SustainabilityFactor              -- §7.4 typed conversion/emissions factors
    SustainabilityBaseline            -- §7.5 typed baseline inputs
    SustainabilityScenarioInput       -- §7.6 typed scenario inputs
    UpstreamAssessmentContext         -- §7.7 upstream intelligence references
    SustainabilityAssumptionInput     -- §7.8 explicit assumption inputs
    SustainabilityDataQualityContext  -- §7.9 data quality metadata inputs
    AssessmentTargetScope             -- §7.1 explicit scope identification
    InputEligibilityResult            -- §7.10 eligibility verdict per input
    SustainabilityAssessmentInput     -- master intake contract with eligibility
                                         check and input fingerprint generation
"""

import hashlib
import json
import uuid
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Core Enumerations
# ---------------------------------------------------------------------------

class SustainabilityValueProvenance(str, Enum):
    """How a sustainability value was established."""
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"


class SustainabilityDimension(str, Enum):
    """Analytical sustainability dimensions."""
    ENERGY = "ENERGY"
    EMISSIONS = "EMISSIONS"
    WATER = "WATER"
    WASTE = "WASTE"
    MATERIAL = "MATERIAL"
    RESOURCE = "RESOURCE"
    SUSTAINABILITY_RISK = "SUSTAINABILITY_RISK"


class SustainabilityConfidence(str, Enum):
    """Confidence in the sustainability estimate."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SustainabilityScenario(str, Enum):
    """Analytical scenario type."""
    BASELINE = "BASELINE"
    EXPECTED = "EXPECTED"
    STRESS = "STRESS"
    CUSTOM = "CUSTOM"


class SustainabilityRiskLevel(str, Enum):
    """Qualitative sustainability risk classification."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    MINIMAL = "MINIMAL"
    UNKNOWN = "UNKNOWN"


class AssumptionProvenance(str, Enum):
    """How a sustainability assumption was obtained."""
    USER_SUPPLIED = "USER_SUPPLIED"
    CONFIGURATION_SUPPLIED = "CONFIGURATION_SUPPLIED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class EmissionsGasType(str, Enum):
    """Greenhouse gas type. Never confuse CO2 and CO2e."""
    CO2E = "CO2e"
    CO2 = "CO2"
    CH4 = "CH4"
    N2O = "N2O"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Valid Unit Registries
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# New Enumerations for Explicit Input Contract (§7.1 – §7.6)
# ---------------------------------------------------------------------------

class MeasurementCategory(str, Enum):
    """Categories of direct operational/resource measurements (§7.2)."""
    ENERGY = "ENERGY"
    WATER = "WATER"
    WASTE = "WASTE"
    MATERIAL = "MATERIAL"
    RESOURCE = "RESOURCE"
    EMISSIONS = "EMISSIONS"
    PRODUCTION = "PRODUCTION"
    ACTIVITY = "ACTIVITY"


class AssessmentScopeType(str, Enum):
    """What entity/resource is being assessed (§7.1)."""
    ASSET = "ASSET"
    PROCESS = "PROCESS"
    PRODUCTION_LINE = "PRODUCTION_LINE"
    PLANT = "PLANT"
    SUPPLIER = "SUPPLIER"
    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"
    INCIDENT = "INCIDENT"
    EVENT = "EVENT"
    BLAST_RADIUS = "BLAST_RADIUS"
    SCENARIO = "SCENARIO"
    CUSTOM = "CUSTOM"


class FactorType(str, Enum):
    """Category of conversion / emissions factor (§7.4)."""
    GRID_EMISSIONS_FACTOR = "GRID_EMISSIONS_FACTOR"
    FUEL_EMISSIONS_FACTOR = "FUEL_EMISSIONS_FACTOR"
    MATERIAL_EMISSIONS_FACTOR = "MATERIAL_EMISSIONS_FACTOR"
    WATER_FACTOR = "WATER_FACTOR"
    WASTE_FACTOR = "WASTE_FACTOR"
    ENERGY_CONVERSION_FACTOR = "ENERGY_CONVERSION_FACTOR"
    CUSTOM = "CUSTOM"


# ---------------------------------------------------------------------------
# Valid Unit Registries
# ---------------------------------------------------------------------------

VALID_ENERGY_UNITS = {"kWh", "MWh", "GWh", "kJ", "MJ", "GJ", "BTU", "MMBTU"}
VALID_EMISSIONS_UNITS = {"kgCO2e", "tCO2e", "kgCO2", "tCO2", "gCO2e", "UNKNOWN"}
VALID_WATER_UNITS = {"liters", "m3", "gallons", "liters/unit", "m3/unit", "UNKNOWN"}
VALID_WASTE_UNITS = {"kg", "tonnes", "kg/unit", "tonnes/unit", "UNKNOWN"}
VALID_MATERIAL_UNITS = {"kg", "tonnes", "units", "kg/unit", "tonnes/unit", "UNKNOWN"}
VALID_ENERGY_INTENSITY_UNITS = {"kWh/unit", "MWh/unit", "kWh/kg", "MWh/tonne", "kWh/production_unit"}

# All units that are recognised anywhere in the contract.
ALL_VALID_UNITS: frozenset = frozenset(
    VALID_ENERGY_UNITS
    | VALID_EMISSIONS_UNITS
    | VALID_WATER_UNITS
    | VALID_WASTE_UNITS
    | VALID_MATERIAL_UNITS
    | VALID_ENERGY_INTENSITY_UNITS
    | {
        # Activity-data units (§7.3)
        "liters", "gallons", "kg", "tonnes", "units", "production_units",
        "hours", "km", "miles", "operating_hours", "downtime_hours",
        "transport_km", "affected_units",
    }
)


# ---------------------------------------------------------------------------
# Sustainability Value Model
# ---------------------------------------------------------------------------

class SustainabilityValue(BaseModel):
    """
    A sustainability measurement with mandatory unit and provenance.
    Every sustainability value must have an explicit unit.
    If the amount cannot be established, use provenance=UNKNOWN and amount=None.
    """
    amount: Optional[float] = Field(default=None)
    unit: str = Field(default="UNKNOWN")
    value_type: str = Field(default="ANALYTICAL_ESTIMATE")
    provenance: SustainabilityValueProvenance = Field(default=SustainabilityValueProvenance.UNKNOWN)
    source_reference: str = Field(default="")
    observed_at: Optional[str] = Field(default=None)
    confidence: SustainabilityConfidence = Field(default=SustainabilityConfidence.INSUFFICIENT_DATA)
    gas_type: Optional[EmissionsGasType] = Field(default=None)

    @property
    def is_known(self) -> bool:
        return self.amount is not None and self.provenance != SustainabilityValueProvenance.UNKNOWN

    @property
    def has_valid_unit(self) -> bool:
        return self.unit not in ("UNKNOWN", "", None)


# ---------------------------------------------------------------------------
# Emissions Factor Model
# ---------------------------------------------------------------------------

class EmissionsFactor(BaseModel):
    """
    A typed emissions conversion factor.
    Every emissions factor must carry full provenance, unit, and validity interval.
    Never silently assume a universal emissions factor.
    """
    factor_id: str = Field(default_factory=lambda: f"ef_{uuid.uuid4().hex[:12]}")
    name: str = Field(...)
    description: str = Field(default="")
    value: float = Field(...)
    numerator_unit: str = Field(...)
    denominator_unit: str = Field(...)
    gas_type: EmissionsGasType = Field(default=EmissionsGasType.CO2E)
    source: str = Field(default="")
    provenance: AssumptionProvenance = Field(default=AssumptionProvenance.UNKNOWN)
    effective_from: Optional[str] = Field(default=None)
    effective_to: Optional[str] = Field(default=None)
    confidence: SustainabilityConfidence = Field(default=SustainabilityConfidence.MEDIUM)

    def is_valid_at(self, timestamp: str) -> bool:
        """Returns True if this factor is temporally valid at the given ISO-8601 timestamp."""
        if self.effective_from and self.effective_from > timestamp:
            return False
        if self.effective_to and self.effective_to <= timestamp:
            return False
        return True


# ---------------------------------------------------------------------------
# Sustainability Assumption Model
# ---------------------------------------------------------------------------

class SustainabilityAssumption(BaseModel):
    """
    A typed assumption used in a sustainability impact calculation.
    Assumptions must be explicitly supplied; they must never be invented.
    """
    assumption_id: str = Field(default_factory=lambda: f"sa_{uuid.uuid4().hex[:12]}")
    name: str = Field(...)
    description: str = Field(default="")
    value: Any = Field(...)
    unit: str = Field(default="")
    source: str = Field(default="")
    provenance: AssumptionProvenance = Field(default=AssumptionProvenance.UNKNOWN)
    effective_from: Optional[str] = Field(default=None)
    effective_to: Optional[str] = Field(default=None)
    confidence: SustainabilityConfidence = Field(default=SustainabilityConfidence.MEDIUM)
    user_supplied: bool = Field(default=False)

    def is_valid_at(self, timestamp: str) -> bool:
        """Returns True if this assumption is temporally valid at the given ISO-8601 timestamp."""
        if self.effective_from and self.effective_from > timestamp:
            return False
        if self.effective_to and self.effective_to <= timestamp:
            return False
        return True


# ---------------------------------------------------------------------------
# Calculation Detail
# ---------------------------------------------------------------------------

class SustainabilityCalculationDetail(BaseModel):
    """Structured representation of a sustainability calculation for transparency."""
    formula: str = Field(default="")
    inputs: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[float] = Field(default=None)
    result_unit: Optional[str] = Field(default=None)
    assumption_ids: List[str] = Field(default_factory=list)
    factor_ids: List[str] = Field(default_factory=list)
    notes: str = Field(default="")


# ---------------------------------------------------------------------------
# Sustainability Evidence
# ---------------------------------------------------------------------------

class SustainabilityEvidence(BaseModel):
    """Evidence supporting a sustainability impact dimension."""
    evidence_id: str = Field(default_factory=lambda: f"sev_{uuid.uuid4().hex[:12]}")
    source_domain: str = Field(...)
    source_reference: str = Field(...)
    observation_timestamp: str = Field(...)
    evidence_type: str = Field(...)
    value: Any = Field(...)
    unit: str = Field(default="UNKNOWN")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: SustainabilityValueProvenance = Field(default=SustainabilityValueProvenance.OBSERVED)
    explanation: str = Field(default="")


# ---------------------------------------------------------------------------
# Intensity Metric
# ---------------------------------------------------------------------------

class SustainabilityIntensity(BaseModel):
    """
    A per-unit intensity metric. Denominator must be positive and valid.
    If denominator is missing, zero, or incompatible, result is UNKNOWN.
    """
    numerator: SustainabilityValue = Field(...)
    denominator_value: Optional[float] = Field(default=None)
    denominator_unit: Optional[str] = Field(default=None)
    result: Optional[float] = Field(default=None)
    result_unit: Optional[str] = Field(default=None)
    is_valid: bool = Field(default=False)
    invalidity_reason: str = Field(default="")


# ---------------------------------------------------------------------------
# Baseline Comparison
# ---------------------------------------------------------------------------

class BaselineComparison(BaseModel):
    """Comparison of a current value against a validated baseline."""
    baseline_id: str = Field(default="")
    baseline_timestamp: Optional[str] = Field(default=None)
    baseline_timestamp_end: Optional[str] = Field(default=None)
    baseline_source: str = Field(default="")
    baseline_value: SustainabilityValue = Field(...)
    current_value: SustainabilityValue = Field(...)
    delta: Optional[float] = Field(default=None)
    delta_unit: Optional[str] = Field(default=None)
    delta_pct: Optional[float] = Field(default=None)
    is_comparable: bool = Field(default=False)
    incomparability_reason: str = Field(default="")
    provenance: SustainabilityValueProvenance = Field(default=SustainabilityValueProvenance.UNKNOWN)
    calculation_version: str = Field(default="v1.0")


# ---------------------------------------------------------------------------
# Sustainability Impact Factor
# ---------------------------------------------------------------------------

class SustainabilityImpactFactor(BaseModel):
    """A single sustainability dimension with full calculation transparency."""
    dimension: SustainabilityDimension = Field(...)
    value: SustainabilityValue = Field(...)
    intensity: Optional[SustainabilityIntensity] = Field(default=None)
    baseline_comparison: Optional[BaselineComparison] = Field(default=None)
    calculation: SustainabilityCalculationDetail = Field(default_factory=SustainabilityCalculationDetail)
    evidence_ids: List[str] = Field(default_factory=list)
    assumption_ids: List[str] = Field(default_factory=list)
    factor_ids: List[str] = Field(default_factory=list)
    provenance: SustainabilityValueProvenance = Field(default=SustainabilityValueProvenance.UNKNOWN)
    confidence: SustainabilityConfidence = Field(default=SustainabilityConfidence.INSUFFICIENT_DATA)
    explanation: str = Field(default="")
    data_quality_issues: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Sustainability Risk Factor
# ---------------------------------------------------------------------------

class SustainabilityRiskFactor(BaseModel):
    """
    Qualitative sustainability risk classification.
    Analytically distinct from sustainability measurements.
    Risk level does NOT directly become a resource quantity.
    """
    risk_level: SustainabilityRiskLevel = Field(default=SustainabilityRiskLevel.UNKNOWN)
    dimension: SustainabilityDimension = Field(...)
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    rationale: str = Field(default="")
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: SustainabilityConfidence = Field(default=SustainabilityConfidence.INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Scenario Context
# ---------------------------------------------------------------------------

class SustainabilityScenarioContext(BaseModel):
    """Metadata for a scenario analysis run."""
    scenario_id: str = Field(default_factory=lambda: f"sscen_{uuid.uuid4().hex[:12]}")
    scenario_name: SustainabilityScenario = Field(default=SustainabilityScenario.EXPECTED)
    custom_name: str = Field(default="")
    description: str = Field(default="")
    assumption_overrides: List[str] = Field(default_factory=list)
    provenance: SustainabilityValueProvenance = Field(default=SustainabilityValueProvenance.SIMULATED)
    calculation_version: str = Field(default="v1.0")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))


# ---------------------------------------------------------------------------
# Upstream Integration Context
# ---------------------------------------------------------------------------

class SustainabilityIntegrationContext(BaseModel):
    """References to upstream intelligence sources consumed by this assessment."""
    data_quality_assessment_ids: List[str] = Field(default_factory=list)
    anomaly_ids: List[str] = Field(default_factory=list)
    event_ids: List[str] = Field(default_factory=list)
    incident_ids: List[str] = Field(default_factory=list)
    rca_ids: List[str] = Field(default_factory=list)
    blast_radius_ids: List[str] = Field(default_factory=list)
    maintenance_assessment_ids: List[str] = Field(default_factory=list)
    demand_forecast_ids: List[str] = Field(default_factory=list)
    supplier_risk_ids: List[str] = Field(default_factory=list)
    sla_customer_risk_ids: List[str] = Field(default_factory=list)
    financial_impact_assessment_ids: List[str] = Field(default_factory=list)
    digital_twin_state_ids: List[str] = Field(default_factory=list)
    knowledge_graph_node_ids: List[str] = Field(default_factory=list)
    ontology_class_refs: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Primary Assessment
# ---------------------------------------------------------------------------

class SustainabilityAssessment(BaseModel):
    """
    The primary Sustainability Intelligence assessment.

    ANALYTICAL ONLY -- This object does not execute, mutate, or trigger any
    operational, environmental-control, financial, procurement, regulatory,
    or physical systems.

    Sustainability Intelligence is an analytical system. It does not directly
    control physical systems, execute remediation, purchase offsets, submit
    regulatory filings, or mutate operational/financial records.
    """
    # --- Identity ---
    assessment_id: str = Field(default_factory=lambda: f"si_{uuid.uuid4().hex[:12]}")
    tenant_id: str = Field(...)
    workspace_id: Optional[str] = Field(default=None)
    plant_id: Optional[str] = Field(default=None)
    asset_id: Optional[str] = Field(default=None)
    supplier_id: Optional[str] = Field(default=None)
    customer_id: Optional[str] = Field(default=None)
    process_id: Optional[str] = Field(default=None)

    # --- Assessment Metadata ---
    assessment_timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    calculation_version: str = Field(default="v1.0")
    schema_version: str = Field(default="1.0")
    input_fingerprint: str = Field(default="")

    # --- Scenario ---
    scenario: SustainabilityScenarioContext = Field(default_factory=SustainabilityScenarioContext)

    # --- Impact Dimensions ---
    factors: List[SustainabilityImpactFactor] = Field(default_factory=list)

    # --- Risk Assessment ---
    risk_factors: List[SustainabilityRiskFactor] = Field(default_factory=list)

    # --- Assessment-Level Confidence ---
    confidence: SustainabilityConfidence = Field(default=SustainabilityConfidence.INSUFFICIENT_DATA)
    confidence_rationale: str = Field(default="")

    # --- Evidence and Assumptions ---
    evidence: List[SustainabilityEvidence] = Field(default_factory=list)
    assumptions: List[SustainabilityAssumption] = Field(default_factory=list)
    emissions_factors: List[EmissionsFactor] = Field(default_factory=list)

    # --- Integration References ---
    integration_context: SustainabilityIntegrationContext = Field(
        default_factory=SustainabilityIntegrationContext
    )

    # --- Metadata ---
    data_quality_issues: List[str] = Field(default_factory=list)
    known_limitations: List[str] = Field(default_factory=list)
    provenance: str = Field(default="system")
    methodology: str = Field(default="deterministic_analytical_sustainability_v1")
    analytical_disclaimer: str = Field(
        default=(
            "ANALYTICAL ONLY. This assessment does not represent carbon neutrality, "
            "net zero, ESG compliance, or regulatory compliance. All estimates are "
            "analytical only and must not be used as verified emissions reductions "
            "without independent validation."
        )
    )

    def generate_fingerprint(self) -> str:
        """
        Deterministic SHA-256 fingerprint of canonical inputs.
        Excludes UUIDs, non-deterministic timestamps, and assessment_id.
        """
        evidence_payload = sorted(
            [
                {
                    "domain": e.source_domain,
                    "ref": e.source_reference,
                    "ts": e.observation_timestamp,
                    "type": e.evidence_type,
                    "val": str(e.value),
                    "unit": e.unit,
                }
                for e in self.evidence
            ],
            key=lambda x: (x["domain"], x["ts"], x["type"], x["ref"]),
        )
        assumption_payload = sorted(
            [
                {
                    "name": a.name,
                    "val": str(a.value),
                    "unit": a.unit,
                    "eff_from": a.effective_from or "",
                    "eff_to": a.effective_to or "",
                }
                for a in self.assumptions
            ],
            key=lambda x: x["name"],
        )
        factor_payload = sorted(
            [
                {
                    "name": f.name,
                    "val": str(f.value),
                    "num_unit": f.numerator_unit,
                    "den_unit": f.denominator_unit,
                    "eff_from": f.effective_from or "",
                    "eff_to": f.effective_to or "",
                }
                for f in self.emissions_factors
            ],
            key=lambda x: x["name"],
        )
        payload = {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id or "",
            "plant_id": self.plant_id or "",
            "asset_id": self.asset_id or "",
            "supplier_id": self.supplier_id or "",
            "customer_id": self.customer_id or "",
            "process_id": self.process_id or "",
            "assessment_timestamp": self.assessment_timestamp,
            "calculation_version": self.calculation_version,
            "scenario_name": self.scenario.scenario_name.value,
            "evidence": evidence_payload,
            "assumptions": assumption_payload,
            "emissions_factors": factor_payload,
            "methodology": self.methodology,
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.input_fingerprint = hashlib.sha256(encoded).hexdigest()
        return self.input_fingerprint


# ---------------------------------------------------------------------------
# §7.2  SustainabilityMeasurement — typed direct observation
# ---------------------------------------------------------------------------

class SustainabilityMeasurement(BaseModel):
    """
    A single direct operational/resource measurement supplied as input.

    Rules (§7.2):
    - amount must be numeric and non-null.
    - unit must be a recognised, non-empty string (not 'UNKNOWN').
    - observed_at is mandatory.
    - source_reference and provenance are mandatory.
    - unitless measurements are rejected by the eligibility checker.
    """
    measurement_id: str = Field(
        default_factory=lambda: f"meas_{uuid.uuid4().hex[:12]}",
        description="Unique measurement identifier.",
    )
    category: MeasurementCategory = Field(..., description="Measurement category (§7.2).")
    amount: float = Field(..., description="Numeric measurement value. Must not be None.")
    unit: str = Field(..., description="Explicit, recognised unit string. Must not be 'UNKNOWN' or empty.")
    observed_at: str = Field(..., description="ISO-8601 UTC timestamp when this was observed.")
    source_reference: str = Field(..., description="Identifier of the source that produced this measurement.")
    provenance: SustainabilityValueProvenance = Field(
        default=SustainabilityValueProvenance.OBSERVED,
        description="How this measurement was obtained.",
    )
    confidence: Optional[SustainabilityConfidence] = Field(
        default=None,
        description="Confidence in this measurement, if available.",
    )
    notes: str = Field(default="", description="Optional measurement notes.")

    @property
    def has_valid_unit(self) -> bool:
        """True when unit is non-empty and not the sentinel 'UNKNOWN'."""
        return bool(self.unit) and self.unit.upper() != "UNKNOWN"


# ---------------------------------------------------------------------------
# §7.3  SustainabilityActivityData — typed operational activity input
# ---------------------------------------------------------------------------

class SustainabilityActivityData(BaseModel):
    """
    Operational activity from which sustainability quantities may be derived.

    Activity data is INPUT only.  Derived outputs (e.g. emissions from fuel)
    are never placed back here.  The distinction is enforced by the service
    layer and verified by the input/output boundary tests (§7.11).

    Examples: energy_consumed, fuel_consumed, production_units, downtime_hours.
    """
    activity_id: str = Field(
        default_factory=lambda: f"act_{uuid.uuid4().hex[:12]}",
        description="Unique activity-data identifier.",
    )
    activity_type: str = Field(
        ...,
        description=(
            "Machine-readable activity label. Examples: energy_consumed, "
            "fuel_consumed, water_consumed, waste_generated, production_units, "
            "operating_hours, downtime_hours, transport_distance, affected_units."
        ),
    )
    value: float = Field(..., description="Numeric activity quantity.")
    unit: str = Field(
        ...,
        description="Explicit unit. Must not be empty or 'UNKNOWN'.",
    )
    window_start: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC start of the activity window (inclusive).",
    )
    window_end: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC end of the activity window (exclusive).",
    )
    source: str = Field(
        ...,
        description="Source system or reference that reported this activity.",
    )
    provenance: SustainabilityValueProvenance = Field(
        default=SustainabilityValueProvenance.OBSERVED,
        description="How this activity value was obtained.",
    )
    confidence: Optional[SustainabilityConfidence] = Field(
        default=None,
        description="Confidence in this activity value, if available.",
    )

    @property
    def has_valid_unit(self) -> bool:
        return bool(self.unit) and self.unit.upper() != "UNKNOWN"


# ---------------------------------------------------------------------------
# §7.4  SustainabilityFactor — typed conversion / emissions factor input
# ---------------------------------------------------------------------------

class SustainabilityFactor(BaseModel):
    """
    An explicit, typed conversion or emissions factor supplied as input.

    Rules (§7.4):
    - Every factor must carry source, input_unit, output_unit, validity
      interval (effective_from, effective_to), and provenance.
    - A factor lacking any of these is flagged as INELIGIBLE by the
      eligibility checker — it is never silently treated as valid.
    - Unit mismatch is never silently converted; the assessment will
      produce an explicit limitation instead.
    """
    factor_id: str = Field(
        default_factory=lambda: f"sfac_{uuid.uuid4().hex[:12]}",
        description="Unique factor identifier.",
    )
    factor_type: FactorType = Field(..., description="Category of this factor (§7.4).")
    value: float = Field(..., description="Factor numeric value.")
    input_unit: str = Field(..., description="Denominator unit (what the factor is applied to).")
    output_unit: str = Field(..., description="Numerator unit (what the factor produces).")
    source_reference: str = Field(
        ...,
        description="Authoritative source for this factor (e.g. IEA 2025, IPCC AR6).",
    )
    methodology: str = Field(
        default="",
        description="Calculation methodology or standard (e.g. GHG Protocol Scope 2).",
    )
    effective_from: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp from which this factor is valid (inclusive).",
    )
    effective_to: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp after which this factor expires (exclusive).",
    )
    provenance: AssumptionProvenance = Field(
        default=AssumptionProvenance.UNKNOWN,
        description="How this factor was obtained.",
    )
    confidence: Optional[SustainabilityConfidence] = Field(
        default=None,
        description="Confidence in this factor value, if available.",
    )

    def is_valid_at(self, timestamp: str) -> bool:
        """True if factor is temporally valid at the given ISO-8601 timestamp."""
        if self.effective_from and self.effective_from > timestamp:
            return False
        if self.effective_to and self.effective_to <= timestamp:
            return False
        return True

    @property
    def is_fully_specified(self) -> bool:
        """True when all mandatory provenance fields are present (§7.4 validation rule)."""
        return (
            bool(self.source_reference)
            and bool(self.input_unit)
            and bool(self.output_unit)
            and self.provenance != AssumptionProvenance.UNKNOWN
        )


# ---------------------------------------------------------------------------
# §7.5  SustainabilityBaseline — typed baseline input
# ---------------------------------------------------------------------------

class SustainabilityBaseline(BaseModel):
    """
    An explicit, identified baseline supplied for comparison purposes.

    Rules (§7.5):
    - A baseline must never be silently inferred from an arbitrary historical
      record; it must be explicitly provided here.
    - The baseline_type field identifies what kind of reference it represents
      so that incompatible baseline comparisons produce an explicit limitation
      rather than a misleading delta.
    - Measurements within the baseline must satisfy the same unit/provenance
      rules as primary measurements.
    """
    baseline_id: str = Field(
        default_factory=lambda: f"bl_{uuid.uuid4().hex[:12]}",
        description="Unique baseline identifier.",
    )
    baseline_type: str = Field(
        ...,
        description=(
            "What kind of reference this baseline represents. "
            "Values: 'previous_period', 'approved_reference', "
            "'production_normalized', 'scenario_baseline', 'custom'."
        ),
    )
    baseline_timestamp_start: str = Field(
        ...,
        description="ISO-8601 UTC start of the baseline window (inclusive).",
    )
    baseline_timestamp_end: str = Field(
        ...,
        description="ISO-8601 UTC end of the baseline window (exclusive).",
    )
    measurements: List[SustainabilityMeasurement] = Field(
        default_factory=list,
        description="Measurements that form the baseline, with full provenance.",
    )
    source_reference: str = Field(
        ...,
        description="Source/authority that validated or produced this baseline.",
    )
    provenance: SustainabilityValueProvenance = Field(
        default=SustainabilityValueProvenance.OBSERVED,
        description="Provenance of the baseline values.",
    )
    calculation_version: str = Field(
        default="v1.0",
        description="Calculation version used to produce this baseline.",
    )
    notes: str = Field(default="", description="Optional notes about this baseline.")


# ---------------------------------------------------------------------------
# §7.6  SustainabilityScenarioInput — typed scenario input
# ---------------------------------------------------------------------------

class SustainabilityScenarioInput(BaseModel):
    """
    Explicit scenario definition supplied as input.

    Rules (§7.6):
    - Scenario assumptions are always distinguishable from observed measurements
      (they live here, not in the measurements list).
    - Scenario inputs never mutate source operational records.
    - scenario_type is one of the four supported values.
    """
    scenario_id: str = Field(
        default_factory=lambda: f"scin_{uuid.uuid4().hex[:12]}",
        description="Unique scenario identifier.",
    )
    scenario_type: SustainabilityScenario = Field(
        ...,
        description="Scenario type: BASELINE | EXPECTED | STRESS | CUSTOM.",
    )
    scenario_timestamp: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC effective timestamp for this scenario (if different from assessment).",
    )
    scenario_assumptions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Assumptions that define this scenario. "
            "These are scenario-specific overrides and must never be mistaken "
            "for observed measurements."
        ),
    )
    description: str = Field(
        default="",
        description="Human-readable description of what this scenario models.",
    )


# ---------------------------------------------------------------------------
# §7.7  UpstreamAssessmentContext — typed upstream intelligence references
# ---------------------------------------------------------------------------

class UpstreamAssessmentContext(BaseModel):
    """
    Explicit references to existing V3 analytical outputs consumed by this
    assessment.  Each ref must carry source/provenance so that upstream
    risk scores are never silently converted to sustainability quantities.

    Rules (§7.7):
    - Upstream references are REFERENCES, not raw inputs.  They identify
      which upstream records were consulted so the service layer can fetch
      and interpret them safely.
    - Cross-tenant and cross-workspace references are rejected by the
      eligibility checker.
    - Upstream risk scores must never automatically become sustainability
      quantities (enforced by the service layer).
    """
    data_quality_refs: List[str] = Field(
        default_factory=list,
        description="IDs of data-quality assessments from Prompt 14.",
    )
    anomaly_refs: List[str] = Field(
        default_factory=list,
        description="IDs of anomaly-detection assessments.",
    )
    event_refs: List[str] = Field(
        default_factory=list,
        description="IDs of operational events.",
    )
    incident_refs: List[str] = Field(
        default_factory=list,
        description="IDs of incident records.",
    )
    rca_refs: List[str] = Field(
        default_factory=list,
        description="IDs of root-cause-analysis results.",
    )
    blast_radius_refs: List[str] = Field(
        default_factory=list,
        description="IDs of blast-radius assessments.",
    )
    predictive_maintenance_refs: List[str] = Field(
        default_factory=list,
        description="IDs of predictive-maintenance assessments.",
    )
    demand_forecast_refs: List[str] = Field(
        default_factory=list,
        description="IDs of demand-forecast records.",
    )
    supplier_risk_refs: List[str] = Field(
        default_factory=list,
        description="IDs of supplier-risk assessments.",
    )
    sla_customer_risk_refs: List[str] = Field(
        default_factory=list,
        description="IDs of SLA/customer-risk assessments.",
    )
    financial_impact_refs: List[str] = Field(
        default_factory=list,
        description="IDs of financial-impact assessments.",
    )
    digital_twin_refs: List[str] = Field(
        default_factory=list,
        description="IDs of digital-twin states.",
    )
    ontology_refs: List[str] = Field(
        default_factory=list,
        description="Ontology class or instance references.",
    )
    knowledge_graph_refs: List[str] = Field(
        default_factory=list,
        description="Knowledge-graph node references.",
    )

    @property
    def all_refs(self) -> List[str]:
        """Flat list of all upstream reference IDs for fingerprinting."""
        return sorted(
            self.data_quality_refs
            + self.anomaly_refs
            + self.event_refs
            + self.incident_refs
            + self.rca_refs
            + self.blast_radius_refs
            + self.predictive_maintenance_refs
            + self.demand_forecast_refs
            + self.supplier_risk_refs
            + self.sla_customer_risk_refs
            + self.financial_impact_refs
            + self.digital_twin_refs
            + self.ontology_refs
            + self.knowledge_graph_refs
        )


# ---------------------------------------------------------------------------
# §7.8  SustainabilityAssumptionInput — explicit assumption input
# ---------------------------------------------------------------------------

class SustainabilityAssumptionInput(BaseModel):
    """
    An explicit assumption supplied when observed data is unavailable.

    Rules (§7.8):
    - Must carry assumption_id, name, value, unit, source, provenance,
      effective_from, effective_to, and confidence.
    - Assumptions are always distinguishable from measurements; an estimated
      result retains the assumption IDs that produced it.
    - Assumptions with UNKNOWN provenance or missing source are flagged as
      ineligible by the eligibility checker.
    """
    assumption_id: str = Field(
        default_factory=lambda: f"sai_{uuid.uuid4().hex[:12]}",
        description="Unique assumption identifier.",
    )
    name: str = Field(..., description="Machine-readable assumption name.")
    description: str = Field(default="", description="Human-readable explanation.")
    value: Any = Field(..., description="Assumption value.")
    unit: str = Field(default="", description="Unit of the assumption value.")
    source: str = Field(..., description="Where this assumption came from.")
    provenance: AssumptionProvenance = Field(
        ...,
        description="How this assumption was obtained. UNKNOWN is not acceptable for eligibility.",
    )
    effective_from: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC from which this assumption is valid.",
    )
    effective_to: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC after which this assumption expires.",
    )
    confidence: SustainabilityConfidence = Field(
        ...,
        description="Confidence in this assumption. Required — not optional.",
    )

    def is_valid_at(self, timestamp: str) -> bool:
        """True if this assumption is temporally valid at the given timestamp."""
        if self.effective_from and self.effective_from > timestamp:
            return False
        if self.effective_to and self.effective_to <= timestamp:
            return False
        return True

    @property
    def is_fully_specified(self) -> bool:
        """True when all eligibility-required fields are present."""
        return (
            bool(self.name)
            and bool(self.source)
            and self.provenance != AssumptionProvenance.UNKNOWN
        )


# ---------------------------------------------------------------------------
# §7.9  SustainabilityDataQualityContext — data-quality metadata input
# ---------------------------------------------------------------------------

class SustainabilityDataQualityContext(BaseModel):
    """
    Data-quality metadata from Prompt 14 that influences confidence and
    produces explicit limitations when quality is degraded.

    Rules (§7.9):
    - Quality metadata influences confidence and/or produces explicit
      limitations — it must NOT silently alter the underlying measurement.
    - quality_flags must be a list of explicit flag strings, never empty by
      convention (if unknown, leave as empty list).
    """
    completeness: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of expected measurements present [0, 1].",
    )
    freshness: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Staleness metric [0=very stale, 1=perfectly fresh].",
    )
    validity: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of measurements passing validity checks [0, 1].",
    )
    consistency: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Internal consistency score [0, 1].",
    )
    source_quality: Optional[str] = Field(
        default=None,
        description="Qualitative source quality label (e.g. HIGH, MEDIUM, LOW).",
    )
    quality_flags: List[str] = Field(
        default_factory=list,
        description="Explicit quality flags from Prompt 14 (e.g. MISSING_SENSOR_DATA).",
    )
    data_quality_assessment_id: Optional[str] = Field(
        default=None,
        description="ID of the upstream Prompt 14 data-quality assessment this was sourced from.",
    )

    @property
    def overall_quality_score(self) -> Optional[float]:
        """Average of available quality dimensions; None if none are set."""
        scores = [
            s for s in [self.completeness, self.freshness, self.validity, self.consistency]
            if s is not None
        ]
        return sum(scores) / len(scores) if scores else None


# ---------------------------------------------------------------------------
# §7.1  AssessmentTargetScope — explicit scope identification
# ---------------------------------------------------------------------------

class AssessmentTargetScope(BaseModel):
    """
    Explicitly identifies what is being assessed.  Scope must never be inferred
    from an arbitrary identifier (§7.1 requirement).
    """
    scope_type: AssessmentScopeType = Field(
        ...,
        description="The type of entity or resource being assessed.",
    )
    scope_id: Optional[str] = Field(
        default=None,
        description="Identifier of the specific entity (e.g. asset_id, supplier_id).",
    )
    scope_label: str = Field(
        default="",
        description="Human-readable label for the scoped entity.",
    )
    additional_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Any further identifiers relevant to this scope (e.g. production_line_id).",
    )


# ---------------------------------------------------------------------------
# §7.10  InputEligibilityResult — per-input eligibility verdict
# ---------------------------------------------------------------------------

class InputEligibilityResult(BaseModel):
    """
    The result of evaluating one eligibility rule against one input item.
    Ineligible inputs are reported explicitly — they never silently become zero.
    """
    input_id: str = Field(..., description="Identifier of the input being checked.")
    input_type: str = Field(
        ...,
        description="Class of input: measurement | activity_data | factor | baseline | assumption.",
    )
    is_eligible: bool = Field(..., description="Whether this input passed all eligibility rules.")
    ineligibility_reasons: List[str] = Field(
        default_factory=list,
        description="Explicit reasons for ineligibility. Empty when is_eligible=True.",
    )


# ---------------------------------------------------------------------------
# Master Input Contract  SustainabilityAssessmentInput  (§7.1 – §7.12)
# ---------------------------------------------------------------------------

class SustainabilityAssessmentInput(BaseModel):
    """
    The complete, typed input contract for a sustainability assessment.

    This is the canonical intake object.  Every field is explicitly typed;
    opaque/arbitrary collections of fields are not accepted.

    Assessment inputs feed the DETERMINISTIC CALCULATION boundary only.
    Calculated outputs (sustainability values, intensities, deltas, etc.) are
    never placed back here; the input/output boundary is preserved (§7.11).

    The generate_input_fingerprint() method produces a deterministic SHA-256
    over all material inputs (§7.12), suitable for idempotent caching.
    """

    # --- §7.1 Identity and scope ---
    tenant_id: str = Field(..., description="Authoritative tenant identifier.")
    workspace_id: Optional[str] = Field(default=None, description="Workspace identifier.")
    plant_id: Optional[str] = Field(default=None, description="Plant identifier when applicable.")
    assessment_timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp at which this assessment is being run.",
    )
    calculation_version: str = Field(
        default="v1.0",
        description="Version of the calculation algorithm to be applied.",
    )
    target_scope: AssessmentTargetScope = Field(
        ...,
        description="Explicit identification of what is being assessed (§7.1).",
    )

    # --- §7.2 Measurements ---
    measurements: List[SustainabilityMeasurement] = Field(
        default_factory=list,
        description="Direct operational/resource observations (§7.2). Unitless items are rejected.",
    )

    # --- §7.3 Activity data ---
    activity_data: List[SustainabilityActivityData] = Field(
        default_factory=list,
        description=(
            "Operational activity inputs from which sustainability quantities may be derived (§7.3). "
            "Remains distinct from derived outputs."
        ),
    )

    # --- §7.4 Conversion / emissions factors ---
    conversion_factors: List[SustainabilityFactor] = Field(
        default_factory=list,
        description="Explicit factors required for derived calculations (§7.4).",
    )

    # --- §7.5 Baseline ---
    baseline: Optional[SustainabilityBaseline] = Field(
        default=None,
        description="Explicitly identified baseline for comparison (§7.5). Never silently inferred.",
    )

    # --- §7.6 Scenario ---
    scenario: Optional[SustainabilityScenarioInput] = Field(
        default=None,
        description="Scenario definition when scenario analysis is requested (§7.6).",
    )

    # --- §7.7 Upstream context ---
    upstream_context: UpstreamAssessmentContext = Field(
        default_factory=UpstreamAssessmentContext,
        description="References to upstream V3 intelligence outputs consumed by this assessment (§7.7).",
    )

    # --- §7.8 Assumption inputs ---
    assumptions: List[SustainabilityAssumptionInput] = Field(
        default_factory=list,
        description="Explicit assumptions when observed data is unavailable (§7.8).",
    )

    # --- §7.9 Data quality context ---
    data_quality_context: Optional[SustainabilityDataQualityContext] = Field(
        default=None,
        description=(
            "Data-quality metadata from Prompt 14 that influences confidence "
            "and produces explicit limitations (§7.9). Never silently alters measurements."
        ),
    )

    # --- Input fingerprint (populated by generate_input_fingerprint()) ---
    input_fingerprint: str = Field(
        default="",
        description="Deterministic SHA-256 over all material inputs (§7.12). Populated after creation.",
    )

    # -----------------------------------------------------------------------
    # §7.10  Input eligibility checking
    # -----------------------------------------------------------------------

    def check_eligibility(
        self,
    ) -> Tuple[List[InputEligibilityResult], List[str]]:
        """
        Evaluate all assessment inputs against the 11 eligibility rules (§7.10).

        Returns
        -------
        results : list of InputEligibilityResult
            One entry per input item checked (measurements, activity_data,
            conversion_factors, assumptions).
        ineligible_ids : list of str
            The IDs of all ineligible inputs, for easy downstream use.

        Rules enforced
        --------------
        1.  Identity is valid (tenant_id, workspace_id non-empty when provided).
        2.  Unit is recognised (non-empty, not 'UNKNOWN').
        3.  Timestamp is valid (not empty; not future-dated relative to assessment).
        4.  Source/provenance is available (not empty, not UNKNOWN).
        5.  Temporal validity includes the assessment timestamp (effective_from/to).
        6.  (Factors) both input_unit and output_unit are specified.
        7.  (Measurements / activity) numeric amount is finite.
        8.  Scope matches (tenant/workspace/plant recorded on assessment input).
        9.  Input is not future-dated relative to assessment_timestamp.
        10. Input has not expired (effective_to is not in the past).
        11. (Assumptions) provenance is not UNKNOWN, source is not empty.
        """
        results: List[InputEligibilityResult] = []
        ts = self.assessment_timestamp

        def _check_measurement(m: SustainabilityMeasurement) -> InputEligibilityResult:
            reasons: List[str] = []
            # Rule 2 — unit must be non-empty, not 'UNKNOWN', and recognised in ALL_VALID_UNITS
            if not m.has_valid_unit or m.unit not in ALL_VALID_UNITS:
                reasons.append("UNITLESS_OR_UNKNOWN_UNIT")
            # Rule 3 — observed_at must be present and not future-dated
            if not m.observed_at:
                reasons.append("MISSING_OBSERVED_AT")
            elif m.observed_at > ts:
                reasons.append("FUTURE_DATED_MEASUREMENT")
            # Rule 4 — source must be present
            if not m.source_reference:
                reasons.append("MISSING_SOURCE_REFERENCE")
            # Rule 4 — provenance must not be UNKNOWN
            if m.provenance == SustainabilityValueProvenance.UNKNOWN:
                reasons.append("MISSING_PROVENANCE")
            # Rule 7 — amount must be finite
            try:
                if not (-1e15 < m.amount < 1e15):
                    reasons.append("AMOUNT_OUT_OF_RANGE")
            except (TypeError, ValueError):
                reasons.append("NON_NUMERIC_AMOUNT")
            return InputEligibilityResult(
                input_id=m.measurement_id,
                input_type="measurement",
                is_eligible=len(reasons) == 0,
                ineligibility_reasons=reasons,
            )

        def _check_activity(a: SustainabilityActivityData) -> InputEligibilityResult:
            reasons: List[str] = []
            if not a.has_valid_unit:
                reasons.append("UNITLESS_OR_UNKNOWN_UNIT")
            if not a.source:
                reasons.append("MISSING_SOURCE")
            if a.provenance == SustainabilityValueProvenance.UNKNOWN:
                reasons.append("MISSING_PROVENANCE")
            try:
                if not (-1e15 < a.value < 1e15):
                    reasons.append("AMOUNT_OUT_OF_RANGE")
            except (TypeError, ValueError):
                reasons.append("NON_NUMERIC_AMOUNT")
            return InputEligibilityResult(
                input_id=a.activity_id,
                input_type="activity_data",
                is_eligible=len(reasons) == 0,
                ineligibility_reasons=reasons,
            )

        def _check_factor(f: SustainabilityFactor) -> InputEligibilityResult:
            reasons: List[str] = []
            # Rule 6 — both units must be specified
            if not f.input_unit:
                reasons.append("MISSING_INPUT_UNIT")
            if not f.output_unit:
                reasons.append("MISSING_OUTPUT_UNIT")
            # Rule 4 — source must be present
            if not f.source_reference:
                reasons.append("MISSING_SOURCE_REFERENCE")
            # Rule 4 — provenance must not be UNKNOWN
            if f.provenance == AssumptionProvenance.UNKNOWN:
                reasons.append("MISSING_PROVENANCE")
            # Rule 5 — temporal validity
            if not f.is_valid_at(ts):
                if f.effective_from and f.effective_from > ts:
                    reasons.append("FUTURE_FACTOR")
                else:
                    reasons.append("EXPIRED_FACTOR")
            return InputEligibilityResult(
                input_id=f.factor_id,
                input_type="factor",
                is_eligible=len(reasons) == 0,
                ineligibility_reasons=reasons,
            )

        def _check_assumption(a: SustainabilityAssumptionInput) -> InputEligibilityResult:
            reasons: List[str] = []
            # Rule 11
            if not a.source:
                reasons.append("MISSING_SOURCE")
            if a.provenance == AssumptionProvenance.UNKNOWN:
                reasons.append("MISSING_PROVENANCE")
            # Rule 5 — temporal validity
            if not a.is_valid_at(ts):
                if a.effective_from and a.effective_from > ts:
                    reasons.append("FUTURE_ASSUMPTION")
                else:
                    reasons.append("EXPIRED_ASSUMPTION")
            return InputEligibilityResult(
                input_id=a.assumption_id,
                input_type="assumption",
                is_eligible=len(reasons) == 0,
                ineligibility_reasons=reasons,
            )

        for m in self.measurements:
            results.append(_check_measurement(m))
        for a in self.activity_data:
            results.append(_check_activity(a))
        for f in self.conversion_factors:
            results.append(_check_factor(f))
        for a in self.assumptions:
            results.append(_check_assumption(a))

        ineligible_ids = [r.input_id for r in results if not r.is_eligible]
        return results, ineligible_ids

    # -----------------------------------------------------------------------
    # §7.12  Input fingerprint
    # -----------------------------------------------------------------------

    def generate_input_fingerprint(self) -> str:
        """
        Deterministic SHA-256 fingerprint of all material assessment inputs (§7.12).

        Included in fingerprint
        -----------------------
        - tenant_id, workspace_id, plant_id
        - assessment_timestamp, calculation_version
        - target_scope (scope_type + scope_id)
        - measurements  (sorted by measurement_id)
        - activity_data (sorted by activity_id)
        - conversion_factors (sorted by factor_id)
        - baseline id and type (if present)
        - scenario id and type (if present)
        - assumptions (sorted by assumption_id)
        - upstream_context.all_refs (sorted)
        - data_quality_context quality flags (sorted)

        Excluded from fingerprint
        -------------------------
        - generated UUIDs that are purely transient identifiers (included
          only when they carry semantic identity — i.e. when they were set
          externally before calling this method)
        - memory addresses, process IDs, nondeterministic ordering
        - runtime-only transient state

        Two calls with the same material inputs must produce the same result.
        Any material change must produce a different result.
        """
        measurements_payload = sorted(
            [
                {
                    "id": m.measurement_id,
                    "category": m.category.value,
                    "amount": m.amount,
                    "unit": m.unit,
                    "observed_at": m.observed_at,
                    "source_reference": m.source_reference,
                    "provenance": m.provenance.value,
                }
                for m in self.measurements
            ],
            key=lambda x: x["id"],
        )

        activity_payload = sorted(
            [
                {
                    "id": a.activity_id,
                    "activity_type": a.activity_type,
                    "value": a.value,
                    "unit": a.unit,
                    "source": a.source,
                    "window_start": a.window_start or "",
                    "window_end": a.window_end or "",
                    "provenance": a.provenance.value,
                }
                for a in self.activity_data
            ],
            key=lambda x: x["id"],
        )

        factor_payload = sorted(
            [
                {
                    "id": f.factor_id,
                    "factor_type": f.factor_type.value,
                    "value": f.value,
                    "input_unit": f.input_unit,
                    "output_unit": f.output_unit,
                    "source_reference": f.source_reference,
                    "effective_from": f.effective_from or "",
                    "effective_to": f.effective_to or "",
                    "provenance": f.provenance.value,
                }
                for f in self.conversion_factors
            ],
            key=lambda x: x["id"],
        )

        assumption_payload = sorted(
            [
                {
                    "id": a.assumption_id,
                    "name": a.name,
                    "value": str(a.value),
                    "unit": a.unit,
                    "source": a.source,
                    "provenance": a.provenance.value,
                    "effective_from": a.effective_from or "",
                    "effective_to": a.effective_to or "",
                }
                for a in self.assumptions
            ],
            key=lambda x: x["id"],
        )

        baseline_payload: Optional[Dict] = None
        if self.baseline is not None:
            baseline_payload = {
                "baseline_id": self.baseline.baseline_id,
                "baseline_type": self.baseline.baseline_type,
                "baseline_timestamp_start": self.baseline.baseline_timestamp_start,
                "baseline_timestamp_end": self.baseline.baseline_timestamp_end,
                "source_reference": self.baseline.source_reference,
                "calculation_version": self.baseline.calculation_version,
            }

        scenario_payload: Optional[Dict] = None
        if self.scenario is not None:
            scenario_payload = {
                "scenario_id": self.scenario.scenario_id,
                "scenario_type": self.scenario.scenario_type.value,
                "scenario_timestamp": self.scenario.scenario_timestamp or "",
            }

        dq_payload: Optional[Dict] = None
        if self.data_quality_context is not None:
            dq_payload = {
                "quality_flags": sorted(self.data_quality_context.quality_flags),
                "completeness": self.data_quality_context.completeness,
                "freshness": self.data_quality_context.freshness,
                "validity": self.data_quality_context.validity,
                "consistency": self.data_quality_context.consistency,
                "source_quality": self.data_quality_context.source_quality,
                "assessment_id": self.data_quality_context.data_quality_assessment_id or "",
            }

        payload = {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id or "",
            "plant_id": self.plant_id or "",
            "assessment_timestamp": self.assessment_timestamp,
            "calculation_version": self.calculation_version,
            "scope_type": self.target_scope.scope_type.value,
            "scope_id": self.target_scope.scope_id or "",
            "measurements": measurements_payload,
            "activity_data": activity_payload,
            "conversion_factors": factor_payload,
            "assumptions": assumption_payload,
            "baseline": baseline_payload,
            "scenario": scenario_payload,
            "upstream_refs": self.upstream_context.all_refs,
            "data_quality_context": dq_payload,
        }

        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.input_fingerprint = hashlib.sha256(encoded).hexdigest()
        return self.input_fingerprint


# ---------------------------------------------------------------------------
# API Request / Response Helpers
# ---------------------------------------------------------------------------

class SustainabilityAnalyzeRequest(BaseModel):
    """
    Request body for POST /api/v3/sustainability/analyze.

    Supports two usage patterns:
    - Legacy (Prompt 26): Use the flat fields (evidence_payloads, assumptions,
      emissions_factors, …).  These are preserved for backward compatibility.
    - Typed input (Prompt 7):  Populate `typed_input` with a fully-formed
      `SustainabilityAssessmentInput`.  When `typed_input` is present, the
      service layer uses it in preference to the flat fields.

    Both patterns can coexist: typed_input is processed first; any remaining
    flat-field payloads are appended as legacy evidence.
    """
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    asset_id: Optional[str] = None
    supplier_id: Optional[str] = None
    customer_id: Optional[str] = None
    process_id: Optional[str] = None
    assessment_timestamp: Optional[str] = None
    calculation_version: str = "v1.0"
    scenario_name: SustainabilityScenario = SustainabilityScenario.EXPECTED
    custom_scenario_name: str = ""
    # --- Legacy flat payloads (backward-compatible) ---
    evidence_payloads: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    emissions_factors: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality_assessment_id: Optional[str] = None
    anomaly_id: Optional[str] = None
    incident_id: Optional[str] = None
    blast_radius_id: Optional[str] = None
    maintenance_assessment_id: Optional[str] = None
    demand_forecast_id: Optional[str] = None
    supplier_risk_assessment_id: Optional[str] = None
    sla_assessment_id: Optional[str] = None
    financial_impact_assessment_id: Optional[str] = None
    # --- Typed input contract (§7 explicit input contract) ---
    typed_input: Optional[SustainabilityAssessmentInput] = Field(
        default=None,
        description=(
            "Fully-typed assessment input contract (§7).  When provided, "
            "the service uses this in preference to the legacy flat fields."
        ),
    )


class SustainabilityScenarioRequest(BaseModel):
    """Request body for POST /api/v3/sustainability/scenario."""
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    asset_id: Optional[str] = None
    base_assessment_id: Optional[str] = None
    scenario_name: SustainabilityScenario = SustainabilityScenario.STRESS
    custom_scenario_name: str = ""
    scenario_description: str = ""
    scenario_assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    base_evidence_payloads: List[Dict[str, Any]] = Field(default_factory=list)
    assessment_timestamp: Optional[str] = None
    calculation_version: str = "v1.0"


class SustainabilitySummaryItem(BaseModel):
    """Lightweight summary row for list endpoints."""
    assessment_id: str
    tenant_id: str
    workspace_id: Optional[str]
    plant_id: Optional[str]
    asset_id: Optional[str]
    assessment_timestamp: str
    scenario_name: str
    confidence: SustainabilityConfidence
    dimensions_present: List[str]
    risk_level: SustainabilityRiskLevel
    input_fingerprint: str
