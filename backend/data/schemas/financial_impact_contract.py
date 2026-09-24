"""
backend/data/schemas/financial_impact_contract.py

SageCommand V3 — Financial Impact Intelligence Domain Contract (Prompt 25)

ANALYTICAL ONLY. This module defines pure data contracts for financial impact
assessment. It does NOT execute, mutate, or trigger any financial, operational,
supplier, customer, inventory, or physical systems.
"""

import hashlib
import json
import uuid
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Core Enumerations
# ---------------------------------------------------------------------------

class FinancialValueProvenance(str, Enum):
    """How a monetary value was established."""
    OBSERVED = "OBSERVED"       # Real value explicitly supplied by a trusted source
    DERIVED = "DERIVED"         # Deterministic calculation from observed values
    ESTIMATED = "ESTIMATED"     # Analytical estimate requiring stated assumptions
    SIMULATED = "SIMULATED"     # Scenario value generated for analysis
    UNKNOWN = "UNKNOWN"         # Insufficient evidence to establish any value


class FinancialImpactCategory(str, Enum):
    """Analytical impact dimensions."""
    REVENUE_EXPOSURE = "REVENUE_EXPOSURE"
    COST_EXPOSURE = "COST_EXPOSURE"
    SERVICE_PENALTY_EXPOSURE = "SERVICE_PENALTY_EXPOSURE"
    DOWNTIME_EXPOSURE = "DOWNTIME_EXPOSURE"
    SUPPLIER_EXPOSURE = "SUPPLIER_EXPOSURE"
    CAPACITY_EXPOSURE = "CAPACITY_EXPOSURE"
    CUSTOMER_EXPOSURE = "CUSTOMER_EXPOSURE"
    MAINTENANCE_EXPOSURE = "MAINTENANCE_EXPOSURE"


class FinancialConfidence(str, Enum):
    """Confidence in the financial impact estimate."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FinancialImpactScenario(str, Enum):
    """Analytical scenario type."""
    BASELINE = "BASELINE"
    EXPECTED = "EXPECTED"
    STRESS = "STRESS"
    CUSTOM = "CUSTOM"


class CurrencyAggregationStatus(str, Enum):
    """Status when aggregating across potentially multiple currencies."""
    AGGREGATED = "AGGREGATED"
    INCOMPATIBLE_CURRENCY = "INCOMPATIBLE_CURRENCY"
    SINGLE_CURRENCY = "SINGLE_CURRENCY"
    NO_MONETARY_VALUE = "NO_MONETARY_VALUE"


class AssumptionProvenance(str, Enum):
    """How an assumption was obtained."""
    USER_SUPPLIED = "USER_SUPPLIED"
    CONFIGURATION_SUPPLIED = "CONFIGURATION_SUPPLIED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Financial Value Model — Every monetary value must carry full context
# ---------------------------------------------------------------------------

class FinancialValue(BaseModel):
    """
    A monetary value with mandatory provenance. Never use bare numerics.
    If the amount cannot be established, use provenance=UNKNOWN and amount=None.
    """
    amount: Optional[float] = Field(
        default=None,
        description="Monetary amount. None means UNKNOWN/insufficient data."
    )
    currency: Optional[str] = Field(
        default=None,
        description="ISO 4217 currency code (e.g., USD, EUR, GBP, INR). "
                    "None if UNKNOWN."
    )
    value_type: str = Field(
        default="ANALYTICAL_ESTIMATE",
        description="What this amount represents (e.g., revenue_at_risk, penalty_exposure)"
    )
    provenance: FinancialValueProvenance = Field(
        default=FinancialValueProvenance.UNKNOWN,
        description="How this value was established."
    )
    source_reference: str = Field(
        default="",
        description="Reference to the source that established this value."
    )
    observed_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp when the source value was observed."
    )
    confidence: FinancialConfidence = Field(
        default=FinancialConfidence.INSUFFICIENT_DATA,
        description="Confidence in this monetary value."
    )

    @property
    def is_known(self) -> bool:
        return self.amount is not None and self.provenance != FinancialValueProvenance.UNKNOWN

    @property
    def is_monetary(self) -> bool:
        return self.amount is not None and self.currency is not None


# ---------------------------------------------------------------------------
# Assumption Model
# ---------------------------------------------------------------------------

class FinancialAssumption(BaseModel):
    """
    A typed assumption used in a financial impact calculation.
    Assumptions must be explicitly supplied; they must never be invented.
    """
    assumption_id: str = Field(
        default_factory=lambda: f"asmp_{uuid.uuid4().hex[:12]}",
        description="Unique assumption identifier."
    )
    name: str = Field(..., description="Machine-readable assumption name (e.g., cost_per_downtime_hour)")
    description: str = Field(default="", description="Human-readable explanation of the assumption.")
    value: Any = Field(..., description="The assumption value.")
    unit: str = Field(default="", description="Unit of the assumption value (e.g., USD/hour).")
    currency: Optional[str] = Field(default=None, description="ISO 4217 code if value is monetary.")
    source: str = Field(default="", description="Where this assumption came from.")
    provenance: AssumptionProvenance = Field(
        default=AssumptionProvenance.UNKNOWN,
        description="How this assumption was obtained."
    )
    effective_from: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp from which this assumption is valid."
    )
    effective_to: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp after which this assumption expires."
    )
    confidence: FinancialConfidence = Field(
        default=FinancialConfidence.MEDIUM,
        description="Confidence in this assumption."
    )
    user_supplied: bool = Field(
        default=False,
        description="True if explicitly supplied by the user/operator at call time."
    )

    def is_valid_at(self, timestamp: str) -> bool:
        """
        Returns True if this assumption is temporally valid at the given
        ISO-8601 timestamp. Future effective_from values are excluded.
        Expired assumptions (past effective_to) are excluded.
        """
        if self.effective_from and self.effective_from > timestamp:
            return False
        if self.effective_to and self.effective_to <= timestamp:
            return False
        return True


# ---------------------------------------------------------------------------
# Calculation Detail — Expose the arithmetic for transparency
# ---------------------------------------------------------------------------

class CalculationDetail(BaseModel):
    """Structured representation of a monetary calculation for transparency."""
    formula: str = Field(default="", description="Human-readable formula string.")
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named calculation inputs with their values."
    )
    result: Optional[float] = Field(
        default=None,
        description="Result of the calculation."
    )
    result_currency: Optional[str] = Field(
        default=None,
        description="Currency of the result."
    )
    assumption_ids: List[str] = Field(
        default_factory=list,
        description="IDs of assumptions used in this calculation."
    )
    notes: str = Field(default="", description="Calculation notes or caveats.")


# ---------------------------------------------------------------------------
# Financial Evidence
# ---------------------------------------------------------------------------

class FinancialEvidence(BaseModel):
    """Evidence supporting a financial impact factor."""
    evidence_id: str = Field(
        default_factory=lambda: f"fi_evd_{uuid.uuid4().hex[:12]}",
        description="Unique evidence identifier."
    )
    source_domain: str = Field(
        ...,
        description="Upstream intelligence source (e.g., SLA_CUSTOMER_RISK, "
                    "SUPPLIER_RISK, PREDICTIVE_MAINTENANCE, DEMAND_FORECAST, "
                    "INCIDENT, BLAST_RADIUS, ANOMALY, DATA_QUALITY)."
    )
    source_reference: str = Field(..., description="Source system record ID.")
    observation_timestamp: str = Field(..., description="ISO-8601 UTC timestamp of observation.")
    evidence_type: str = Field(..., description="Type of evidence (e.g., sla_breach_risk, maintenance_risk_score).")
    value: Any = Field(..., description="The actual observed or derived value.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence in this evidence [0,1].")
    provenance: FinancialValueProvenance = Field(
        default=FinancialValueProvenance.OBSERVED,
        description="How this evidence was obtained."
    )
    explanation: str = Field(default="", description="Human-readable explanation.")


# ---------------------------------------------------------------------------
# Financial Impact Factor — One impact dimension
# ---------------------------------------------------------------------------

class FinancialImpactFactor(BaseModel):
    """A single financial impact dimension with full calculation transparency."""
    category: FinancialImpactCategory = Field(..., description="Impact dimension.")
    value: FinancialValue = Field(..., description="Monetary value of this impact dimension.")
    calculation: CalculationDetail = Field(
        default_factory=CalculationDetail,
        description="Calculation detail for transparency."
    )
    evidence_ids: List[str] = Field(
        default_factory=list,
        description="IDs of supporting evidence records."
    )
    assumption_ids: List[str] = Field(
        default_factory=list,
        description="IDs of assumptions used."
    )
    provenance: FinancialValueProvenance = Field(
        default=FinancialValueProvenance.UNKNOWN,
        description="Provenance of the impact value."
    )
    confidence: FinancialConfidence = Field(
        default=FinancialConfidence.INSUFFICIENT_DATA,
        description="Confidence in this impact factor."
    )
    explanation: str = Field(default="", description="Human-readable explanation of this factor.")
    data_quality_issues: List[str] = Field(
        default_factory=list,
        description="Data quality issues that affect this factor."
    )


# ---------------------------------------------------------------------------
# Currency Conversion (explicit only — no implicit FX fetching)
# ---------------------------------------------------------------------------

class ExplicitCurrencyConversion(BaseModel):
    """
    An explicit, timestamped currency conversion rate.
    Never fetched implicitly; must be supplied by the caller.
    """
    from_currency: str = Field(..., description="Source ISO 4217 code.")
    to_currency: str = Field(..., description="Target ISO 4217 code.")
    rate: float = Field(..., gt=0.0, description="Conversion rate: 1 from_currency = rate to_currency.")
    rate_timestamp: str = Field(..., description="ISO-8601 UTC timestamp of the rate.")
    source: str = Field(default="", description="Source of the rate (e.g., ECB, user_supplied).")
    provenance: AssumptionProvenance = Field(default=AssumptionProvenance.USER_SUPPLIED)


# ---------------------------------------------------------------------------
# Scenario Context
# ---------------------------------------------------------------------------

class FinancialScenarioContext(BaseModel):
    """Metadata for a scenario analysis run."""
    scenario_id: str = Field(
        default_factory=lambda: f"scen_{uuid.uuid4().hex[:12]}",
        description="Unique scenario identifier."
    )
    scenario_name: FinancialImpactScenario = Field(
        default=FinancialImpactScenario.EXPECTED,
        description="Named scenario."
    )
    custom_name: str = Field(default="", description="Custom scenario label if scenario_name=CUSTOM.")
    description: str = Field(default="", description="Human-readable scenario description.")
    assumption_overrides: List[str] = Field(
        default_factory=list,
        description="assumption_ids that are overridden for this scenario."
    )
    provenance: FinancialValueProvenance = Field(
        default=FinancialValueProvenance.SIMULATED,
        description="Scenario outputs are SIMULATED unless using real inputs."
    )
    calculation_version: str = Field(default="v1.0", description="Calculation version used.")
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Upstream Integration Context
# ---------------------------------------------------------------------------

class FinancialIntegrationContext(BaseModel):
    """References to upstream intelligence sources consumed by this assessment."""
    sla_customer_risk_ids: List[str] = Field(default_factory=list)
    supplier_risk_ids: List[str] = Field(default_factory=list)
    demand_forecast_ids: List[str] = Field(default_factory=list)
    maintenance_assessment_ids: List[str] = Field(default_factory=list)
    blast_radius_ids: List[str] = Field(default_factory=list)
    rca_ids: List[str] = Field(default_factory=list)
    incident_ids: List[str] = Field(default_factory=list)
    anomaly_ids: List[str] = Field(default_factory=list)
    data_quality_assessment_ids: List[str] = Field(default_factory=list)
    digital_twin_state_ids: List[str] = Field(default_factory=list)
    knowledge_graph_node_ids: List[str] = Field(default_factory=list)
    ontology_class_refs: List[str] = Field(default_factory=list)
    event_ids: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Primary Assessment
# ---------------------------------------------------------------------------

class FinancialImpactAssessment(BaseModel):
    """
    The primary Financial Impact Intelligence assessment.

    ANALYTICAL ONLY — This object does not execute, mutate, or trigger any
    financial, operational, customer, supplier, inventory, or physical systems.
    """
    # --- Identity ---
    assessment_id: str = Field(
        default_factory=lambda: f"fi_{uuid.uuid4().hex[:12]}",
        description="Unique assessment identifier."
    )
    tenant_id: str = Field(..., description="Authoritative tenant identifier.")
    workspace_id: Optional[str] = Field(default=None, description="Workspace identifier.")
    plant_id: Optional[str] = Field(default=None, description="Industrial plant identifier.")
    customer_id: Optional[str] = Field(default=None, description="Customer identifier if applicable.")
    supplier_id: Optional[str] = Field(default=None, description="Supplier identifier if applicable.")
    asset_id: Optional[str] = Field(default=None, description="Asset identifier if applicable.")
    service_id: Optional[str] = Field(default=None, description="Service/order reference if applicable.")

    # --- Assessment Metadata ---
    assessment_timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 UTC timestamp of this assessment."
    )
    calculation_version: str = Field(default="v1.0", description="Calculation algorithm version.")
    schema_version: str = Field(default="1.0", description="Contract schema version.")
    input_fingerprint: str = Field(default="", description="Deterministic SHA-256 fingerprint of canonical inputs.")

    # --- Scenario ---
    scenario: FinancialScenarioContext = Field(
        default_factory=FinancialScenarioContext,
        description="Scenario context for this assessment."
    )

    # --- Impact Factors ---
    factors: List[FinancialImpactFactor] = Field(
        default_factory=list,
        description="Individual impact dimensions with full calculation transparency."
    )

    # --- Aggregation ---
    total_exposure: FinancialValue = Field(
        default_factory=lambda: FinancialValue(
            provenance=FinancialValueProvenance.UNKNOWN,
            confidence=FinancialConfidence.INSUFFICIENT_DATA
        ),
        description="Aggregated total exposure. Only populated when safe to aggregate."
    )
    aggregation_status: CurrencyAggregationStatus = Field(
        default=CurrencyAggregationStatus.NO_MONETARY_VALUE,
        description="Status of cross-factor monetary aggregation."
    )
    aggregation_currency: Optional[str] = Field(
        default=None,
        description="Currency used for aggregation (if aggregation_status=AGGREGATED)."
    )

    # --- Assessment-Level Confidence ---
    confidence: FinancialConfidence = Field(
        default=FinancialConfidence.INSUFFICIENT_DATA,
        description="Overall confidence in this assessment."
    )
    confidence_rationale: str = Field(
        default="",
        description="Explanation of the confidence rating."
    )

    # --- Evidence & Assumptions ---
    evidence: List[FinancialEvidence] = Field(
        default_factory=list,
        description="All evidence records referenced by factors."
    )
    assumptions: List[FinancialAssumption] = Field(
        default_factory=list,
        description="All assumptions used in calculations."
    )
    currency_conversions: List[ExplicitCurrencyConversion] = Field(
        default_factory=list,
        description="Explicit currency conversions used (if any)."
    )

    # --- Integration References ---
    integration_context: FinancialIntegrationContext = Field(
        default_factory=FinancialIntegrationContext,
        description="References to upstream intelligence consumed."
    )

    # --- Metadata ---
    data_quality_issues: List[str] = Field(
        default_factory=list,
        description="Data quality issues that affect this assessment."
    )
    known_limitations: List[str] = Field(
        default_factory=list,
        description="Documented limitations of this assessment."
    )
    provenance: str = Field(default="system", description="System provenance.")
    methodology: str = Field(
        default="deterministic_analytical_financial_impact_v1",
        description="Calculation methodology."
    )

    def generate_fingerprint(self) -> str:
        """
        Deterministic SHA-256 fingerprint of canonical inputs.
        Excludes UUIDs, non-deterministic timestamps, and assessment_id.
        """
        # Normalize evidence deterministically
        evidence_payload = sorted(
            [
                {
                    "domain": e.source_domain,
                    "ref": e.source_reference,
                    "ts": e.observation_timestamp,
                    "type": e.evidence_type,
                    "val": str(e.value),
                }
                for e in self.evidence
            ],
            key=lambda x: (x["domain"], x["ts"], x["type"], x["ref"]),
        )

        # Normalize assumptions deterministically
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

        payload = {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id or "",
            "plant_id": self.plant_id or "",
            "customer_id": self.customer_id or "",
            "supplier_id": self.supplier_id or "",
            "asset_id": self.asset_id or "",
            "service_id": self.service_id or "",
            "assessment_timestamp": self.assessment_timestamp,
            "calculation_version": self.calculation_version,
            "scenario_name": self.scenario.scenario_name.value,
            "evidence": evidence_payload,
            "assumptions": assumption_payload,
            "methodology": self.methodology,
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.input_fingerprint = hashlib.sha256(encoded).hexdigest()
        return self.input_fingerprint


# ---------------------------------------------------------------------------
# API Request / Response helpers
# ---------------------------------------------------------------------------

class FinancialImpactAnalyzeRequest(BaseModel):
    """Request body for POST /api/v3/financial-impact/analyze."""
    tenant_id: str
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None
    customer_id: Optional[str] = None
    supplier_id: Optional[str] = None
    asset_id: Optional[str] = None
    service_id: Optional[str] = None

    assessment_timestamp: Optional[str] = None
    calculation_version: str = "v1.0"

    scenario_name: FinancialImpactScenario = FinancialImpactScenario.EXPECTED
    custom_scenario_name: str = ""

    # Upstream evidence (structured payloads from upstream services)
    evidence_payloads: List[Dict[str, Any]] = Field(default_factory=list)

    # Assumptions (must be user/config supplied; never invented by the engine)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)

    # Optional explicit currency conversions
    currency_conversions: List[Dict[str, Any]] = Field(default_factory=list)

    # Integration references
    sla_assessment_id: Optional[str] = None
    supplier_risk_assessment_id: Optional[str] = None
    maintenance_assessment_id: Optional[str] = None
    demand_forecast_id: Optional[str] = None
    blast_radius_id: Optional[str] = None


class FinancialImpactSummaryItem(BaseModel):
    """Lightweight summary row for list endpoints."""
    assessment_id: str
    tenant_id: str
    workspace_id: Optional[str]
    customer_id: Optional[str]
    supplier_id: Optional[str]
    asset_id: Optional[str]
    assessment_timestamp: str
    scenario_name: str
    confidence: FinancialConfidence
    aggregation_status: CurrencyAggregationStatus
    total_amount: Optional[float]
    total_currency: Optional[str]
    input_fingerprint: str
