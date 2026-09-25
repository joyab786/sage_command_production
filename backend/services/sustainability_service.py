"""
backend/services/sustainability_service.py

SageCommand V3 — Sustainability Intelligence Service (Prompt 26)

ANALYTICAL ONLY. This service translates upstream operational intelligence
into deterministic sustainability impact estimates. It does NOT execute,
mutate, or trigger any operational, environmental-control, financial,
procurement, regulatory-filing, offset-purchasing, carbon-credit-trading,
or physical systems.

Sustainability Intelligence is an analytical system. It does not directly
control physical systems, execute remediation, purchase offsets, submit
regulatory filings, or mutate operational/financial records.

Calculation chain:
    SOURCE EVIDENCE
    + VALIDATED ASSUMPTIONS
    + VALIDATED EMISSIONS FACTORS
    + DETERMINISTIC CALCULATION
    = SUSTAINABILITY EXPOSURE (or UNKNOWN / INSUFFICIENT_DATA)
"""

from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Tuple

try:
    from data.schemas.sustainability_contract import (
        AssumptionProvenance,
        BaselineComparison,
        EmissionsFactor,
        EmissionsGasType,
        SustainabilityAssessment,
        SustainabilityAssumption,
        SustainabilityCalculationDetail,
        SustainabilityConfidence,
        SustainabilityDimension,
        SustainabilityEvidence,
        SustainabilityImpactFactor,
        SustainabilityIntegrationContext,
        SustainabilityIntensity,
        SustainabilityRiskFactor,
        SustainabilityRiskLevel,
        SustainabilityScenario,
        SustainabilityScenarioContext,
        SustainabilityValue,
        SustainabilityValueProvenance,
        SustainabilityAnalyzeRequest,
        SustainabilityScenarioRequest,
        VALID_ENERGY_UNITS,
        VALID_EMISSIONS_UNITS,
        VALID_WATER_UNITS,
        VALID_WASTE_UNITS,
        VALID_MATERIAL_UNITS,
    )
    from services.sustainability_repository import sustainability_repository
except ModuleNotFoundError:
    from backend.data.schemas.sustainability_contract import (
        AssumptionProvenance,
        BaselineComparison,
        EmissionsFactor,
        EmissionsGasType,
        SustainabilityAssessment,
        SustainabilityAssumption,
        SustainabilityCalculationDetail,
        SustainabilityConfidence,
        SustainabilityDimension,
        SustainabilityEvidence,
        SustainabilityImpactFactor,
        SustainabilityIntegrationContext,
        SustainabilityIntensity,
        SustainabilityRiskFactor,
        SustainabilityRiskLevel,
        SustainabilityScenario,
        SustainabilityScenarioContext,
        SustainabilityValue,
        SustainabilityValueProvenance,
        SustainabilityAnalyzeRequest,
        SustainabilityScenarioRequest,
        VALID_ENERGY_UNITS,
        VALID_EMISSIONS_UNITS,
        VALID_WATER_UNITS,
        VALID_WASTE_UNITS,
        VALID_MATERIAL_UNITS,
    )
    from backend.services.sustainability_repository import sustainability_repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _unknown_sv(dimension: SustainabilityDimension, unit: str = "UNKNOWN") -> SustainabilityValue:
    """Return an UNKNOWN sustainability value."""
    return SustainabilityValue(
        amount=None,
        unit=unit,
        value_type=dimension.value,
        provenance=SustainabilityValueProvenance.UNKNOWN,
        confidence=SustainabilityConfidence.INSUFFICIENT_DATA,
    )


def _resolve_assumption(
    name: str,
    assumptions: List[SustainabilityAssumption],
    assessment_timestamp: str,
) -> Optional[SustainabilityAssumption]:
    """
    Find a temporally valid assumption by name.
    Future effective_from and expired effective_to are excluded.
    Returns None if not found or not valid at assessment_timestamp.
    """
    for a in assumptions:
        if a.name == name and a.is_valid_at(assessment_timestamp):
            return a
    return None


def _resolve_factor(
    name: str,
    factors: List[EmissionsFactor],
    assessment_timestamp: str,
) -> Optional[EmissionsFactor]:
    """
    Find a temporally valid emissions factor by name.
    Returns None if not found or not valid at assessment_timestamp.
    """
    for f in factors:
        if f.name == name and f.is_valid_at(assessment_timestamp):
            return f
    return None


def _confidence_for_value(
    value: SustainabilityValue,
    evidence_count: int,
    has_factor: bool,
    quality_ok: bool,
) -> SustainabilityConfidence:
    """Compute confidence for a single sustainability value."""
    if not quality_ok or evidence_count == 0:
        return SustainabilityConfidence.INSUFFICIENT_DATA
    if value.provenance == SustainabilityValueProvenance.UNKNOWN:
        return SustainabilityConfidence.INSUFFICIENT_DATA
    if not has_factor and value.provenance == SustainabilityValueProvenance.ESTIMATED:
        return SustainabilityConfidence.LOW
    if evidence_count >= 3:
        return SustainabilityConfidence.HIGH
    if evidence_count >= 1:
        return SustainabilityConfidence.MEDIUM
    return SustainabilityConfidence.LOW


def _calc_intensity(
    numerator: SustainabilityValue,
    denominator_value: Optional[float],
    denominator_unit: Optional[str],
) -> SustainabilityIntensity:
    """
    Calculate an intensity metric (numerator / denominator).
    Returns an invalid intensity if denominator is missing, zero, or incompatible.
    """
    if denominator_value is None or denominator_value <= 0 or denominator_unit is None:
        reason = (
            "Denominator missing" if denominator_value is None
            else "Denominator zero or negative" if denominator_value <= 0
            else "Denominator unit missing"
        )
        return SustainabilityIntensity(
            numerator=numerator,
            denominator_value=denominator_value,
            denominator_unit=denominator_unit,
            is_valid=False,
            invalidity_reason=reason,
        )
    if numerator.amount is None or numerator.unit == "UNKNOWN":
        return SustainabilityIntensity(
            numerator=numerator,
            denominator_value=denominator_value,
            denominator_unit=denominator_unit,
            is_valid=False,
            invalidity_reason="Numerator amount is UNKNOWN",
        )
    result = numerator.amount / denominator_value
    result_unit = f"{numerator.unit}/{denominator_unit}"
    return SustainabilityIntensity(
        numerator=numerator,
        denominator_value=denominator_value,
        denominator_unit=denominator_unit,
        result=result,
        result_unit=result_unit,
        is_valid=True,
    )


# ---------------------------------------------------------------------------
# Individual dimension calculators
# ---------------------------------------------------------------------------

def _calc_energy(
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[SustainabilityImpactFactor]:
    """
    ENERGY dimension.
    Uses evidence_type in ("energy_kwh", "energy_consumption_kwh", "energy_mwh",
    "energy_consumption", "downtime_energy_kwh").
    Requires explicit unit in VALID_ENERGY_UNITS.
    Does NOT infer energy from risk scores.
    """
    energy_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "energy_kwh", "energy_consumption_kwh", "energy_consumption",
            "energy_mwh", "downtime_energy_kwh", "energy_consumption_mwh",
        )
        and e.unit in VALID_ENERGY_UNITS
    ]
    if not energy_evidence:
        return None

    try:
        amount = float(energy_evidence[0].value)
        unit = energy_evidence[0].unit
    except (TypeError, ValueError):
        return None

    # Production units for intensity (optional)
    prod_asmp = _resolve_assumption("production_units", assumptions, assessment_timestamp)
    prod_value = float(prod_asmp.value) if prod_asmp else None
    prod_unit = prod_asmp.unit if prod_asmp else None
    if prod_asmp and prod_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(prod_asmp.assumption_id)

    sv = SustainabilityValue(
        amount=amount,
        unit=unit,
        value_type="energy_consumption",
        provenance=SustainabilityValueProvenance(energy_evidence[0].provenance.value),
        source_reference=energy_evidence[0].source_reference,
        observed_at=energy_evidence[0].observation_timestamp,
        confidence=SustainabilityConfidence.HIGH
        if energy_evidence[0].provenance == SustainabilityValueProvenance.OBSERVED
        else SustainabilityConfidence.MEDIUM,
        gas_type=None,
    )

    intensity = _calc_intensity(sv, prod_value, prod_unit)

    calc = SustainabilityCalculationDetail(
        formula="directly from evidence source",
        inputs={"energy_amount": amount, "unit": unit},
        result=amount,
        result_unit=unit,
        assumption_ids=[prod_asmp.assumption_id] if prod_asmp else [],
        notes="Energy value sourced from evidence. Not inferred from risk scores.",
    )

    return SustainabilityImpactFactor(
        dimension=SustainabilityDimension.ENERGY,
        value=sv,
        intensity=intensity if intensity.is_valid else None,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in energy_evidence],
        assumption_ids=[prod_asmp.assumption_id] if prod_asmp else [],
        provenance=sv.provenance,
        confidence=sv.confidence,
        explanation=(
            f"Energy consumption: {amount:.4f} {unit}. "
            f"Provenance: {sv.provenance.value}. "
            + (f"Intensity: {intensity.result:.6f} {intensity.result_unit}." if intensity.is_valid else "")
        ),
    )


def _calc_emissions(
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    emissions_factors: List[EmissionsFactor],
    assumption_ids_used: List[str],
    factor_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[SustainabilityImpactFactor]:
    """
    EMISSIONS dimension.

    Supports three pathways:
    1. Direct observed CO2e evidence.
    2. energy × grid_emissions_factor (kWh × kgCO2e/kWh).
    3. material_quantity × material_emissions_factor.

    Never silently assumes a universal emissions factor.
    Never confuses CO2 and CO2e.
    """
    # Pathway 1: Direct emissions evidence
    direct_emissions = [
        e for e in evidence
        if e.evidence_type in ("co2e_kg", "emissions_co2e", "emissions_kgco2e", "co2e_tonnes")
        and e.unit in VALID_EMISSIONS_UNITS
    ]
    if direct_emissions:
        try:
            amount = float(direct_emissions[0].value)
            unit = direct_emissions[0].unit
        except (TypeError, ValueError):
            return None

        # Detect gas type from unit
        gas_type = EmissionsGasType.CO2E if "CO2e" in unit else EmissionsGasType.CO2

        sv = SustainabilityValue(
            amount=amount,
            unit=unit,
            value_type="emissions_co2e",
            provenance=SustainabilityValueProvenance(direct_emissions[0].provenance.value),
            source_reference=direct_emissions[0].source_reference,
            observed_at=direct_emissions[0].observation_timestamp,
            confidence=SustainabilityConfidence.HIGH
            if direct_emissions[0].provenance == SustainabilityValueProvenance.OBSERVED
            else SustainabilityConfidence.MEDIUM,
            gas_type=gas_type,
        )

        prod_asmp = _resolve_assumption("production_units", assumptions, assessment_timestamp)
        prod_value = float(prod_asmp.value) if prod_asmp else None
        prod_unit = prod_asmp.unit if prod_asmp else None
        if prod_asmp and prod_asmp.assumption_id not in assumption_ids_used:
            assumption_ids_used.append(prod_asmp.assumption_id)

        intensity = _calc_intensity(sv, prod_value, prod_unit)

        calc = SustainabilityCalculationDetail(
            formula="directly from evidence (observed emissions)",
            inputs={"amount": amount, "unit": unit},
            result=amount,
            result_unit=unit,
            notes="Emissions value sourced directly from evidence. Gas type preserved.",
        )

        return SustainabilityImpactFactor(
            dimension=SustainabilityDimension.EMISSIONS,
            value=sv,
            intensity=intensity if intensity.is_valid else None,
            calculation=calc,
            evidence_ids=[e.evidence_id for e in direct_emissions],
            provenance=sv.provenance,
            confidence=sv.confidence,
            explanation=f"Emissions: {amount:.4f} {unit} ({gas_type.value}). Direct evidence.",
        )

    # Pathway 2: energy × grid_emissions_factor
    energy_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "energy_kwh", "energy_consumption_kwh", "energy_consumption",
            "energy_mwh", "energy_consumption_mwh",
        )
        and e.unit in VALID_ENERGY_UNITS
    ]
    ef = _resolve_factor("grid_emissions_factor", emissions_factors, assessment_timestamp)

    if energy_evidence and ef:
        try:
            energy_amount = float(energy_evidence[0].value)
            energy_unit = energy_evidence[0].unit
        except (TypeError, ValueError):
            return None

        # Unit compatibility check: factor denominator must match energy unit
        if ef.denominator_unit != energy_unit:
            # Cannot safely multiply incompatible units
            return None

        emissions_amount = energy_amount * ef.value
        emissions_unit = ef.numerator_unit  # e.g., kgCO2e

        if emissions_unit not in VALID_EMISSIONS_UNITS:
            return None

        if ef.factor_id not in factor_ids_used:
            factor_ids_used.append(ef.factor_id)

        gas_type = EmissionsGasType.CO2E if "CO2e" in emissions_unit else EmissionsGasType.CO2

        prod_asmp = _resolve_assumption("production_units", assumptions, assessment_timestamp)
        prod_value = float(prod_asmp.value) if prod_asmp else None
        prod_unit = prod_asmp.unit if prod_asmp else None
        if prod_asmp and prod_asmp.assumption_id not in assumption_ids_used:
            assumption_ids_used.append(prod_asmp.assumption_id)

        sv = SustainabilityValue(
            amount=emissions_amount,
            unit=emissions_unit,
            value_type="emissions_co2e_derived",
            provenance=SustainabilityValueProvenance.DERIVED,
            source_reference=ef.source,
            confidence=ef.confidence,
            gas_type=gas_type,
        )

        intensity = _calc_intensity(sv, prod_value, prod_unit)

        calc = SustainabilityCalculationDetail(
            formula="energy_consumption × grid_emissions_factor",
            inputs={
                "energy_amount": energy_amount,
                "energy_unit": energy_unit,
                "factor_name": ef.name,
                "factor_value": ef.value,
                "factor_unit": f"{ef.numerator_unit}/{ef.denominator_unit}",
            },
            result=emissions_amount,
            result_unit=emissions_unit,
            factor_ids=[ef.factor_id],
            notes=(
                f"Emissions derived: {energy_amount:.4f} {energy_unit} × "
                f"{ef.value} {ef.numerator_unit}/{ef.denominator_unit} = "
                f"{emissions_amount:.4f} {emissions_unit}. "
                f"Factor source: {ef.source}. Gas type: {gas_type.value}."
            ),
        )

        return SustainabilityImpactFactor(
            dimension=SustainabilityDimension.EMISSIONS,
            value=sv,
            intensity=intensity if intensity.is_valid else None,
            calculation=calc,
            evidence_ids=[e.evidence_id for e in energy_evidence],
            assumption_ids=[prod_asmp.assumption_id] if prod_asmp else [],
            factor_ids=[ef.factor_id],
            provenance=SustainabilityValueProvenance.DERIVED,
            confidence=ef.confidence,
            explanation=(
                f"Emissions (DERIVED): {energy_amount:.4f} {energy_unit} × "
                f"{ef.value} {ef.numerator_unit}/{ef.denominator_unit} = "
                f"{emissions_amount:.4f} {emissions_unit}. Factor: '{ef.name}'."
            ),
        )

    # Pathway 3: material × material_emissions_factor
    material_evidence = [
        e for e in evidence
        if e.evidence_type in ("material_quantity_kg", "fuel_quantity_kg", "material_consumption")
        and e.unit in VALID_MATERIAL_UNITS
    ]
    mat_ef = _resolve_factor("material_emissions_factor", emissions_factors, assessment_timestamp)

    if material_evidence and mat_ef:
        try:
            mat_amount = float(material_evidence[0].value)
            mat_unit = material_evidence[0].unit
        except (TypeError, ValueError):
            return None

        if mat_ef.denominator_unit != mat_unit:
            return None

        emissions_amount = mat_amount * mat_ef.value
        emissions_unit = mat_ef.numerator_unit

        if emissions_unit not in VALID_EMISSIONS_UNITS:
            return None

        if mat_ef.factor_id not in factor_ids_used:
            factor_ids_used.append(mat_ef.factor_id)

        gas_type = EmissionsGasType.CO2E if "CO2e" in emissions_unit else EmissionsGasType.CO2

        sv = SustainabilityValue(
            amount=emissions_amount,
            unit=emissions_unit,
            value_type="emissions_co2e_material_derived",
            provenance=SustainabilityValueProvenance.DERIVED,
            source_reference=mat_ef.source,
            confidence=mat_ef.confidence,
            gas_type=gas_type,
        )

        calc = SustainabilityCalculationDetail(
            formula="material_quantity × material_emissions_factor",
            inputs={
                "material_amount": mat_amount,
                "material_unit": mat_unit,
                "factor_name": mat_ef.name,
                "factor_value": mat_ef.value,
                "factor_unit": f"{mat_ef.numerator_unit}/{mat_ef.denominator_unit}",
            },
            result=emissions_amount,
            result_unit=emissions_unit,
            factor_ids=[mat_ef.factor_id],
        )

        return SustainabilityImpactFactor(
            dimension=SustainabilityDimension.EMISSIONS,
            value=sv,
            calculation=calc,
            evidence_ids=[e.evidence_id for e in material_evidence],
            factor_ids=[mat_ef.factor_id],
            provenance=SustainabilityValueProvenance.DERIVED,
            confidence=mat_ef.confidence,
            explanation=(
                f"Emissions (MATERIAL DERIVED): {mat_amount:.4f} {mat_unit} × "
                f"{mat_ef.value} {mat_ef.numerator_unit}/{mat_ef.denominator_unit} = "
                f"{emissions_amount:.4f} {emissions_unit}."
            ),
        )

    return None


def _calc_water(
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[SustainabilityImpactFactor]:
    """
    WATER dimension.
    Uses explicit evidence_type in ("water_consumption_liters", "water_m3",
    "water_consumption").
    Does NOT fabricate water consumption.
    If no valid water measurement or factor exists: UNKNOWN.
    """
    water_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "water_consumption_liters", "water_m3", "water_consumption",
            "water_liters", "water_usage_m3",
        )
        and e.unit in VALID_WATER_UNITS
    ]
    if not water_evidence:
        return None

    try:
        amount = float(water_evidence[0].value)
        unit = water_evidence[0].unit
    except (TypeError, ValueError):
        return None

    prod_asmp = _resolve_assumption("production_units", assumptions, assessment_timestamp)
    prod_value = float(prod_asmp.value) if prod_asmp else None
    prod_unit = prod_asmp.unit if prod_asmp else None
    if prod_asmp and prod_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(prod_asmp.assumption_id)

    sv = SustainabilityValue(
        amount=amount,
        unit=unit,
        value_type="water_consumption",
        provenance=SustainabilityValueProvenance(water_evidence[0].provenance.value),
        source_reference=water_evidence[0].source_reference,
        observed_at=water_evidence[0].observation_timestamp,
        confidence=SustainabilityConfidence.HIGH
        if water_evidence[0].provenance == SustainabilityValueProvenance.OBSERVED
        else SustainabilityConfidence.MEDIUM,
    )

    intensity = _calc_intensity(sv, prod_value, prod_unit)

    calc = SustainabilityCalculationDetail(
        formula="directly from water evidence",
        inputs={"water_amount": amount, "unit": unit},
        result=amount,
        result_unit=unit,
    )

    return SustainabilityImpactFactor(
        dimension=SustainabilityDimension.WATER,
        value=sv,
        intensity=intensity if intensity.is_valid else None,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in water_evidence],
        assumption_ids=[prod_asmp.assumption_id] if prod_asmp else [],
        provenance=sv.provenance,
        confidence=sv.confidence,
        explanation=f"Water consumption: {amount:.4f} {unit}.",
    )


def _calc_waste(
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[SustainabilityImpactFactor]:
    """
    WASTE dimension.
    Uses explicit evidence_type in ("waste_kg", "waste_tonnes",
    "waste_quantity", "waste_generation_kg").
    Does NOT infer hazardous/non-hazardous without evidence.
    """
    waste_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "waste_kg", "waste_tonnes", "waste_quantity",
            "waste_generation_kg", "waste_generation_tonnes",
        )
        and e.unit in VALID_WASTE_UNITS
    ]
    if not waste_evidence:
        return None

    try:
        amount = float(waste_evidence[0].value)
        unit = waste_evidence[0].unit
    except (TypeError, ValueError):
        return None

    prod_asmp = _resolve_assumption("production_units", assumptions, assessment_timestamp)
    prod_value = float(prod_asmp.value) if prod_asmp else None
    prod_unit = prod_asmp.unit if prod_asmp else None
    if prod_asmp and prod_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(prod_asmp.assumption_id)

    # Waste category from evidence metadata
    waste_category = str(waste_evidence[0].explanation) if waste_evidence[0].explanation else "UNCLASSIFIED"

    sv = SustainabilityValue(
        amount=amount,
        unit=unit,
        value_type="waste_quantity",
        provenance=SustainabilityValueProvenance(waste_evidence[0].provenance.value),
        source_reference=waste_evidence[0].source_reference,
        observed_at=waste_evidence[0].observation_timestamp,
        confidence=SustainabilityConfidence.HIGH
        if waste_evidence[0].provenance == SustainabilityValueProvenance.OBSERVED
        else SustainabilityConfidence.MEDIUM,
    )

    intensity = _calc_intensity(sv, prod_value, prod_unit)

    calc = SustainabilityCalculationDetail(
        formula="directly from waste evidence",
        inputs={"waste_amount": amount, "unit": unit, "category": waste_category},
        result=amount,
        result_unit=unit,
    )

    return SustainabilityImpactFactor(
        dimension=SustainabilityDimension.WASTE,
        value=sv,
        intensity=intensity if intensity.is_valid else None,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in waste_evidence],
        assumption_ids=[prod_asmp.assumption_id] if prod_asmp else [],
        provenance=sv.provenance,
        confidence=sv.confidence,
        explanation=f"Waste: {amount:.4f} {unit}. Category: {waste_category}.",
    )


def _calc_material(
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[SustainabilityImpactFactor]:
    """
    MATERIAL dimension.
    Uses evidence_type in ("material_consumption_kg", "raw_material_kg",
    "material_consumption", "material_quantity_kg").
    Every quantity must have amount, unit, source, timestamp, provenance, confidence.
    """
    material_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "material_consumption_kg", "raw_material_kg",
            "material_consumption", "material_quantity_kg",
            "material_usage_tonnes",
        )
        and e.unit in VALID_MATERIAL_UNITS
    ]
    if not material_evidence:
        return None

    try:
        amount = float(material_evidence[0].value)
        unit = material_evidence[0].unit
    except (TypeError, ValueError):
        return None

    prod_asmp = _resolve_assumption("production_units", assumptions, assessment_timestamp)
    prod_value = float(prod_asmp.value) if prod_asmp else None
    prod_unit = prod_asmp.unit if prod_asmp else None
    if prod_asmp and prod_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(prod_asmp.assumption_id)

    sv = SustainabilityValue(
        amount=amount,
        unit=unit,
        value_type="material_consumption",
        provenance=SustainabilityValueProvenance(material_evidence[0].provenance.value),
        source_reference=material_evidence[0].source_reference,
        observed_at=material_evidence[0].observation_timestamp,
        confidence=SustainabilityConfidence.HIGH
        if material_evidence[0].provenance == SustainabilityValueProvenance.OBSERVED
        else SustainabilityConfidence.MEDIUM,
    )

    intensity = _calc_intensity(sv, prod_value, prod_unit)

    calc = SustainabilityCalculationDetail(
        formula="directly from material evidence",
        inputs={"material_amount": amount, "unit": unit},
        result=amount,
        result_unit=unit,
    )

    return SustainabilityImpactFactor(
        dimension=SustainabilityDimension.MATERIAL,
        value=sv,
        intensity=intensity if intensity.is_valid else None,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in material_evidence],
        assumption_ids=[prod_asmp.assumption_id] if prod_asmp else [],
        provenance=sv.provenance,
        confidence=sv.confidence,
        explanation=f"Material consumption: {amount:.4f} {unit}.",
    )


def _calc_resource(
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[SustainabilityImpactFactor]:
    """
    RESOURCE dimension (general resource utilization).
    Uses evidence_type in ("resource_utilization", "resource_consumption",
    "resource_units").
    """
    resource_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "resource_utilization", "resource_consumption",
            "resource_units", "resource_quantity",
        )
    ]
    if not resource_evidence:
        return None

    try:
        amount = float(resource_evidence[0].value)
        unit = resource_evidence[0].unit or "units"
    except (TypeError, ValueError):
        return None

    sv = SustainabilityValue(
        amount=amount,
        unit=unit,
        value_type="resource_consumption",
        provenance=SustainabilityValueProvenance(resource_evidence[0].provenance.value),
        source_reference=resource_evidence[0].source_reference,
        observed_at=resource_evidence[0].observation_timestamp,
        confidence=SustainabilityConfidence.MEDIUM,
    )

    calc = SustainabilityCalculationDetail(
        formula="directly from resource evidence",
        inputs={"resource_amount": amount, "unit": unit},
        result=amount,
        result_unit=unit,
    )

    return SustainabilityImpactFactor(
        dimension=SustainabilityDimension.RESOURCE,
        value=sv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in resource_evidence],
        provenance=sv.provenance,
        confidence=sv.confidence,
        explanation=f"Resource consumption: {amount:.4f} {unit}.",
    )


def _calc_sustainability_risk(
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    assessment_timestamp: str,
) -> List[SustainabilityRiskFactor]:
    """
    Sustainability risk classification.
    Analytically distinct from sustainability measurements.
    Risk level does NOT directly become a resource quantity or monetary value.
    Risk score does NOT directly become CO2e without an explicit validated model.
    """
    risk_factors = []

    for dim in SustainabilityDimension:
        # Look for risk evidence for this dimension
        risk_evidence = [
            e for e in evidence
            if e.evidence_type == f"sustainability_risk_{dim.value.lower()}"
            or e.evidence_type == "sustainability_risk_score"
        ]

        # Look for a risk level in assumptions
        risk_asmp = _resolve_assumption(
            f"sustainability_risk_{dim.value.lower()}", assumptions, assessment_timestamp
        )

        level = SustainabilityRiskLevel.UNKNOWN
        score = None
        rationale = "Insufficient evidence to classify sustainability risk."
        conf = SustainabilityConfidence.INSUFFICIENT_DATA
        ev_ids = []

        if risk_evidence:
            ev_ids = [e.evidence_id for e in risk_evidence]
            try:
                score_val = float(risk_evidence[0].value)
                score = score_val
                # Map score to risk level (0-100 scale) — explicit threshold model
                if score >= 80:
                    level = SustainabilityRiskLevel.CRITICAL
                elif score >= 60:
                    level = SustainabilityRiskLevel.HIGH
                elif score >= 40:
                    level = SustainabilityRiskLevel.MEDIUM
                elif score >= 20:
                    level = SustainabilityRiskLevel.LOW
                else:
                    level = SustainabilityRiskLevel.MINIMAL
                rationale = (
                    f"Risk score {score:.1f}/100 → {level.value}. "
                    "Score sourced from evidence. Classification uses explicit threshold model."
                )
                conf = SustainabilityConfidence.MEDIUM
            except (TypeError, ValueError):
                pass

        elif risk_asmp:
            try:
                score_val = float(risk_asmp.value)
                score = score_val
                if score >= 80:
                    level = SustainabilityRiskLevel.CRITICAL
                elif score >= 60:
                    level = SustainabilityRiskLevel.HIGH
                elif score >= 40:
                    level = SustainabilityRiskLevel.MEDIUM
                elif score >= 20:
                    level = SustainabilityRiskLevel.LOW
                else:
                    level = SustainabilityRiskLevel.MINIMAL
                rationale = (
                    f"Risk score {score:.1f}/100 → {level.value} (from assumption). "
                    "ESTIMATED — requires evidence-backed measurement for HIGH confidence."
                )
                conf = SustainabilityConfidence.LOW
            except (TypeError, ValueError):
                pass

        risk_factors.append(
            SustainabilityRiskFactor(
                risk_level=level,
                dimension=dim,
                score=score,
                rationale=rationale,
                evidence_ids=ev_ids,
                confidence=conf,
            )
        )

    return risk_factors


# ---------------------------------------------------------------------------
# Confidence Calculation
# ---------------------------------------------------------------------------

def _calc_overall_confidence(
    factors: List[SustainabilityImpactFactor],
    evidence: List[SustainabilityEvidence],
    assumptions: List[SustainabilityAssumption],
    data_quality_issues: List[str],
) -> Tuple[SustainabilityConfidence, str]:
    """
    Overall confidence considers:
    - Number of known (non-UNKNOWN) factors
    - Evidence quality and staleness
    - Assumption completeness
    - Data quality issues
    - Upstream confidence propagation
    """
    known_factors = [f for f in factors if f.value.is_known]
    if not known_factors:
        return (
            SustainabilityConfidence.INSUFFICIENT_DATA,
            "No sustainability impact factors could be calculated from available evidence and assumptions.",
        )

    dq_issue_count = len([i for i in data_quality_issues if not i.startswith("INFO:")])
    if dq_issue_count > 2:
        return (
            SustainabilityConfidence.LOW,
            f"Multiple data quality issues present: {', '.join(data_quality_issues[:3])}.",
        )

    low_conf_assumptions = [
        a for a in assumptions
        if a.confidence in (SustainabilityConfidence.LOW, SustainabilityConfidence.INSUFFICIENT_DATA)
    ]
    if low_conf_assumptions:
        return (
            SustainabilityConfidence.LOW,
            f"{len(low_conf_assumptions)} assumption(s) have low confidence.",
        )

    unknown_evidence = [
        e for e in evidence
        if e.provenance == SustainabilityValueProvenance.UNKNOWN
    ]
    if unknown_evidence:
        return (
            SustainabilityConfidence.LOW,
            f"{len(unknown_evidence)} evidence item(s) have UNKNOWN provenance.",
        )

    if len(known_factors) >= 3 and len(evidence) >= 3:
        return (
            SustainabilityConfidence.HIGH,
            "Multiple corroborating evidence sources and validated assumptions.",
        )
    if len(known_factors) >= 1 and len(evidence) >= 1:
        return (
            SustainabilityConfidence.MEDIUM,
            "Sufficient evidence and assumptions for a medium-confidence estimate.",
        )
    return (
        SustainabilityConfidence.LOW,
        "Limited evidence or assumptions; estimate has high uncertainty.",
    )


# ---------------------------------------------------------------------------
# Main Service Class
# ---------------------------------------------------------------------------

class SustainabilityService:
    """
    Deterministic Sustainability Intelligence Service.

    Calculation flow:
    1. Validate inputs
    2. Normalize evidence (temporal leakage protection)
    3. Parse and validate assumptions (temporal validity)
    4. Parse and validate emissions factors (temporal validity)
    5. Determine eligible dimensions
    6. Calculate deterministic sustainability values
    7. Calculate intensity metrics
    8. Calculate baseline deltas (if baseline provided)
    9. Classify sustainability risk (analytically separate)
    10. Calculate scenario outputs
    11. Calculate overall confidence
    12. Build integration context
    13. Assemble assessment
    14. Generate deterministic fingerprint
    15. Persist
    16. Return typed result

    DOES NOT:
    - Execute any operational, environmental-control, financial, or physical actions
    - Control physical systems or PLC/devices
    - Execute energy control, automated shutdown, or machine throttling
    - Purchase carbon credits or offsets
    - Submit regulatory filings or ESG disclosures
    - Mutate incidents, events, anomalies, demand forecasts, or supplier records
    - Invoke the Execution Gateway or Action API
    - Claim carbon neutrality, net zero, ESG compliance, or regulatory compliance
    """

    def analyze(
        self,
        tenant_id: str,
        assessment_timestamp: str,
        evidence_payloads: List[Dict[str, Any]],
        raw_assumptions: List[Dict[str, Any]],
        raw_emissions_factors: List[Dict[str, Any]],
        scenario_name: SustainabilityScenario = SustainabilityScenario.EXPECTED,
        custom_scenario_name: str = "",
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        process_id: Optional[str] = None,
        calculation_version: str = "v1.0",
        data_quality_assessment_id: Optional[str] = None,
        anomaly_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        blast_radius_id: Optional[str] = None,
        maintenance_assessment_id: Optional[str] = None,
        demand_forecast_id: Optional[str] = None,
        supplier_risk_assessment_id: Optional[str] = None,
        sla_assessment_id: Optional[str] = None,
        financial_impact_assessment_id: Optional[str] = None,
    ) -> SustainabilityAssessment:

        data_quality_issues: List[str] = []
        known_limitations: List[str] = []

        # 1. Normalize evidence — temporal leakage protection
        processed_evidence: List[SustainabilityEvidence] = []
        for ep in evidence_payloads:
            obs_ts = ep.get("observation_timestamp", "")
            # Exclude evidence whose observation is in the future relative to assessment
            if obs_ts and obs_ts > assessment_timestamp:
                data_quality_issues.append(
                    f"FUTURE_EVIDENCE_EXCLUDED:{ep.get('source_reference', 'unknown')}"
                )
                continue
            try:
                prov_raw = ep.get("provenance", "UNKNOWN")
                prov = (
                    SustainabilityValueProvenance(prov_raw)
                    if prov_raw in SustainabilityValueProvenance._value2member_map_
                    else SustainabilityValueProvenance.UNKNOWN
                )
                evd = SustainabilityEvidence(
                    source_domain=ep.get("source_domain", "UNKNOWN"),
                    source_reference=ep.get("source_reference", "unknown"),
                    observation_timestamp=obs_ts or assessment_timestamp,
                    evidence_type=ep.get("evidence_type", "unknown"),
                    value=ep.get("value"),
                    unit=ep.get("unit", "UNKNOWN"),
                    confidence=float(ep.get("confidence", 1.0)),
                    provenance=prov,
                    explanation=ep.get("explanation", ""),
                )
                processed_evidence.append(evd)
            except Exception:
                data_quality_issues.append("EVIDENCE_PARSE_ERROR")

        # 2. Parse and validate assumptions — temporal validity enforced
        validated_assumptions: List[SustainabilityAssumption] = []
        for ap in raw_assumptions:
            try:
                prov_raw = ap.get("provenance", "UNKNOWN")
                prov = (
                    AssumptionProvenance(prov_raw)
                    if prov_raw in AssumptionProvenance._value2member_map_
                    else AssumptionProvenance.UNKNOWN
                )
                conf_raw = ap.get("confidence", "MEDIUM")
                try:
                    conf = SustainabilityConfidence(conf_raw)
                except ValueError:
                    conf = SustainabilityConfidence.MEDIUM

                asmp = SustainabilityAssumption(
                    name=ap["name"],
                    description=ap.get("description", ""),
                    value=ap["value"],
                    unit=ap.get("unit", ""),
                    source=ap.get("source", ""),
                    provenance=prov,
                    effective_from=ap.get("effective_from"),
                    effective_to=ap.get("effective_to"),
                    confidence=conf,
                    user_supplied=bool(ap.get("user_supplied", True)),
                )
                # Temporal validity — exclude future assumptions
                if asmp.effective_from and asmp.effective_from > assessment_timestamp:
                    data_quality_issues.append(
                        f"FUTURE_ASSUMPTION_EXCLUDED:{asmp.name}"
                    )
                    continue
                # Exclude expired assumptions
                if asmp.effective_to and asmp.effective_to <= assessment_timestamp:
                    data_quality_issues.append(
                        f"EXPIRED_ASSUMPTION_EXCLUDED:{asmp.name}"
                    )
                    continue
                validated_assumptions.append(asmp)
            except Exception:
                data_quality_issues.append("ASSUMPTION_PARSE_ERROR")

        if not validated_assumptions:
            known_limitations.append(
                "No validated assumptions provided. "
                "Intensity metrics and emissions derivations require explicit assumptions."
            )

        # 3. Parse and validate emissions factors — temporal validity enforced
        validated_factors: List[EmissionsFactor] = []
        for fp in raw_emissions_factors:
            try:
                prov_raw = fp.get("provenance", "UNKNOWN")
                prov = (
                    AssumptionProvenance(prov_raw)
                    if prov_raw in AssumptionProvenance._value2member_map_
                    else AssumptionProvenance.UNKNOWN
                )
                conf_raw = fp.get("confidence", "MEDIUM")
                try:
                    conf = SustainabilityConfidence(conf_raw)
                except ValueError:
                    conf = SustainabilityConfidence.MEDIUM

                gas_raw = fp.get("gas_type", "CO2e")
                try:
                    gas_type = EmissionsGasType(gas_raw)
                except ValueError:
                    gas_type = EmissionsGasType.CO2E

                ef = EmissionsFactor(
                    name=fp["name"],
                    description=fp.get("description", ""),
                    value=float(fp["value"]),
                    numerator_unit=fp["numerator_unit"],
                    denominator_unit=fp["denominator_unit"],
                    gas_type=gas_type,
                    source=fp.get("source", ""),
                    provenance=prov,
                    effective_from=fp.get("effective_from"),
                    effective_to=fp.get("effective_to"),
                    confidence=conf,
                )
                # Temporal validity — exclude future factors
                if ef.effective_from and ef.effective_from > assessment_timestamp:
                    data_quality_issues.append(
                        f"FUTURE_FACTOR_EXCLUDED:{ef.name}"
                    )
                    continue
                # Exclude expired factors
                if ef.effective_to and ef.effective_to <= assessment_timestamp:
                    data_quality_issues.append(
                        f"EXPIRED_FACTOR_EXCLUDED:{ef.name}"
                    )
                    continue
                validated_factors.append(ef)
            except Exception:
                data_quality_issues.append("EMISSIONS_FACTOR_PARSE_ERROR")

        # 4. Build scenario
        is_simulated = scenario_name in (
            SustainabilityScenario.STRESS, SustainabilityScenario.CUSTOM
        )
        scenario = SustainabilityScenarioContext(
            scenario_name=scenario_name,
            custom_name=custom_scenario_name,
            description=f"Sustainability assessment scenario: {scenario_name.value}",
            provenance=SustainabilityValueProvenance.SIMULATED
            if is_simulated
            else SustainabilityValueProvenance.ESTIMATED,
            calculation_version=calculation_version,
        )

        # 5. Run dimension calculators
        assumption_ids_used: List[str] = []
        factor_ids_used: List[str] = []
        factors: List[SustainabilityImpactFactor] = []

        # Energy
        energy_factor = _calc_energy(
            processed_evidence, validated_assumptions, assumption_ids_used, assessment_timestamp
        )
        if energy_factor:
            factors.append(energy_factor)

        # Emissions
        emissions_factor_result = _calc_emissions(
            processed_evidence, validated_assumptions, validated_factors,
            assumption_ids_used, factor_ids_used, assessment_timestamp
        )
        if emissions_factor_result:
            factors.append(emissions_factor_result)

        # Water
        water_factor = _calc_water(
            processed_evidence, validated_assumptions, assumption_ids_used, assessment_timestamp
        )
        if water_factor:
            factors.append(water_factor)

        # Waste
        waste_factor = _calc_waste(
            processed_evidence, validated_assumptions, assumption_ids_used, assessment_timestamp
        )
        if waste_factor:
            factors.append(waste_factor)

        # Material
        material_factor = _calc_material(
            processed_evidence, validated_assumptions, assumption_ids_used, assessment_timestamp
        )
        if material_factor:
            factors.append(material_factor)

        # Resource
        resource_factor = _calc_resource(
            processed_evidence, validated_assumptions, assumption_ids_used, assessment_timestamp
        )
        if resource_factor:
            factors.append(resource_factor)

        # Ensure all dimensions are represented (UNKNOWN if no data)
        calculated_dims = {f.dimension for f in factors}
        for dim in SustainabilityDimension:
            if dim == SustainabilityDimension.SUSTAINABILITY_RISK:
                continue  # Handled separately
            if dim not in calculated_dims:
                factors.append(
                    SustainabilityImpactFactor(
                        dimension=dim,
                        value=_unknown_sv(dim),
                        provenance=SustainabilityValueProvenance.UNKNOWN,
                        confidence=SustainabilityConfidence.INSUFFICIENT_DATA,
                        explanation=(
                            f"{dim.value}: UNKNOWN — insufficient evidence or "
                            "assumptions to calculate this dimension."
                        ),
                        data_quality_issues=["INSUFFICIENT_EVIDENCE_OR_ASSUMPTIONS"],
                    )
                )

        # 6. Sustainability risk classification (analytically separate)
        risk_factors = _calc_sustainability_risk(
            processed_evidence, validated_assumptions, assessment_timestamp
        )

        # 7. Overall confidence
        confidence, confidence_rationale = _calc_overall_confidence(
            factors, processed_evidence, validated_assumptions, data_quality_issues
        )

        # 8. Integration context
        integration_ctx = SustainabilityIntegrationContext(
            data_quality_assessment_ids=[data_quality_assessment_id]
            if data_quality_assessment_id
            else [],
            anomaly_ids=[anomaly_id] if anomaly_id else [],
            incident_ids=[incident_id] if incident_id else [],
            blast_radius_ids=[blast_radius_id] if blast_radius_id else [],
            maintenance_assessment_ids=[maintenance_assessment_id]
            if maintenance_assessment_id
            else [],
            demand_forecast_ids=[demand_forecast_id] if demand_forecast_id else [],
            supplier_risk_ids=[supplier_risk_assessment_id]
            if supplier_risk_assessment_id
            else [],
            sla_customer_risk_ids=[sla_assessment_id] if sla_assessment_id else [],
            financial_impact_assessment_ids=[financial_impact_assessment_id]
            if financial_impact_assessment_id
            else [],
        )

        # 9. Assemble assessment
        assessment = SustainabilityAssessment(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            asset_id=asset_id,
            supplier_id=supplier_id,
            customer_id=customer_id,
            process_id=process_id,
            assessment_timestamp=assessment_timestamp,
            calculation_version=calculation_version,
            schema_version="1.0",
            scenario=scenario,
            factors=factors,
            risk_factors=risk_factors,
            confidence=confidence,
            confidence_rationale=confidence_rationale,
            evidence=processed_evidence,
            assumptions=validated_assumptions,
            emissions_factors=validated_factors,
            integration_context=integration_ctx,
            data_quality_issues=data_quality_issues,
            known_limitations=known_limitations,
            methodology="deterministic_analytical_sustainability_v1",
        )

        # 10. Generate deterministic fingerprint
        assessment.generate_fingerprint()

        # 11. Persist and return
        return sustainability_repository.save_assessment(assessment)

    def analyze_scenario(
        self,
        tenant_id: str,
        assessment_timestamp: str,
        scenario_name: SustainabilityScenario,
        scenario_assumptions: List[Dict[str, Any]],
        base_evidence_payloads: List[Dict[str, Any]],
        raw_emissions_factors: List[Dict[str, Any]],
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        custom_scenario_name: str = "",
        calculation_version: str = "v1.0",
    ) -> SustainabilityAssessment:
        """
        Run a scenario analysis. Scenario-derived values are marked SIMULATED.
        This method does NOT mutate operational records.
        """
        return self.analyze(
            tenant_id=tenant_id,
            assessment_timestamp=assessment_timestamp,
            evidence_payloads=base_evidence_payloads,
            raw_assumptions=scenario_assumptions,
            raw_emissions_factors=raw_emissions_factors,
            scenario_name=scenario_name,
            custom_scenario_name=custom_scenario_name,
            workspace_id=workspace_id,
            plant_id=plant_id,
            asset_id=asset_id,
            calculation_version=calculation_version,
        )


sustainability_service = SustainabilityService()
