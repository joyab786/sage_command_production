"""
backend/services/financial_impact_service.py

SageCommand V3 — Financial Impact Intelligence Service (Prompt 25)

ANALYTICAL ONLY. This service translates upstream operational intelligence
into deterministic financial impact estimates. It does NOT execute, mutate,
or trigger any financial, operational, customer, supplier, inventory, or
physical systems. No payment processing, no invoice mutation, no ERP writes,
no procurement, no order changes.

Calculation chain:
    SOURCE EVIDENCE
    + VALIDATED ASSUMPTIONS
    + DETERMINISTIC CALCULATION
    = FINANCIAL EXPOSURE (or UNKNOWN / INSUFFICIENT_DATA)
"""

from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Tuple

try:
    from data.schemas.financial_impact_contract import (
        AssumptionProvenance,
        CalculationDetail,
        CurrencyAggregationStatus,
        ExplicitCurrencyConversion,
        FinancialAssumption,
        FinancialConfidence,
        FinancialEvidence,
        FinancialImpactAssessment,
        FinancialImpactCategory,
        FinancialImpactFactor,
        FinancialImpactScenario,
        FinancialIntegrationContext,
        FinancialScenarioContext,
        FinancialValue,
        FinancialValueProvenance,
    )
    from services.financial_impact_repository import financial_impact_repository
except ModuleNotFoundError:
    from backend.data.schemas.financial_impact_contract import (
        AssumptionProvenance,
        CalculationDetail,
        CurrencyAggregationStatus,
        ExplicitCurrencyConversion,
        FinancialAssumption,
        FinancialConfidence,
        FinancialEvidence,
        FinancialImpactAssessment,
        FinancialImpactCategory,
        FinancialImpactFactor,
        FinancialImpactScenario,
        FinancialIntegrationContext,
        FinancialScenarioContext,
        FinancialValue,
        FinancialValueProvenance,
    )
    from backend.services.financial_impact_repository import financial_impact_repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_assumption(
    name: str,
    assumptions: List[FinancialAssumption],
    assessment_timestamp: str,
) -> Optional[FinancialAssumption]:
    """
    Find a temporally valid assumption by name.
    Future effective_from and expired effective_to are excluded.
    Returns None if not found or not valid at assessment_timestamp.
    """
    for a in assumptions:
        if a.name == name and a.is_valid_at(assessment_timestamp):
            return a
    return None


def _unknown_value(category_label: str) -> FinancialValue:
    return FinancialValue(
        amount=None,
        currency=None,
        value_type=category_label,
        provenance=FinancialValueProvenance.UNKNOWN,
        confidence=FinancialConfidence.INSUFFICIENT_DATA,
    )


def _confidence_from_count(count: int, quality_ok: bool = True) -> FinancialConfidence:
    if not quality_ok or count == 0:
        return FinancialConfidence.INSUFFICIENT_DATA
    if count >= 3:
        return FinancialConfidence.HIGH
    if count >= 1:
        return FinancialConfidence.MEDIUM
    return FinancialConfidence.LOW


# ---------------------------------------------------------------------------
# Individual Impact Calculators
# ---------------------------------------------------------------------------

def _calc_downtime_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    DOWNTIME_EXPOSURE = duration_hours × cost_per_downtime_hour

    Requires:
    - evidence with evidence_type in ("downtime_hours", "downtime_duration_hours")
    - assumption named "cost_per_downtime_hour" with currency
    """
    downtime_evidence = [
        e for e in evidence
        if e.evidence_type in ("downtime_hours", "downtime_duration_hours", "expected_downtime_hours")
    ]
    cost_asmp = _resolve_assumption("cost_per_downtime_hour", assumptions, assessment_timestamp)

    if not downtime_evidence or cost_asmp is None:
        # Cannot calculate without both
        return None

    try:
        duration_hours = float(downtime_evidence[0].value)
        cost_rate = float(cost_asmp.value)
        currency = cost_asmp.currency or "UNKNOWN"
    except (TypeError, ValueError):
        return None

    exposure = duration_hours * cost_rate
    if cost_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(cost_asmp.assumption_id)

    calc = CalculationDetail(
        formula="duration_hours × cost_per_downtime_hour",
        inputs={
            "duration_hours": duration_hours,
            "cost_per_downtime_hour": cost_rate,
            "currency": currency,
        },
        result=exposure,
        result_currency=currency,
        assumption_ids=[cost_asmp.assumption_id],
        notes="Cost rate sourced from validated assumption; not invented.",
    )

    fv = FinancialValue(
        amount=exposure,
        currency=currency,
        value_type="downtime_exposure",
        provenance=FinancialValueProvenance.DERIVED,
        source_reference=cost_asmp.source,
        confidence=FinancialConfidence.MEDIUM,
    )

    return FinancialImpactFactor(
        category=FinancialImpactCategory.DOWNTIME_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in downtime_evidence],
        assumption_ids=[cost_asmp.assumption_id],
        provenance=FinancialValueProvenance.DERIVED,
        confidence=FinancialConfidence.MEDIUM,
        explanation=(
            f"Downtime exposure: {duration_hours:.2f} hours × "
            f"{cost_rate:.2f} {currency}/hour = {exposure:.2f} {currency}. "
            f"Cost rate from assumption '{cost_asmp.name}'."
        ),
    )


def _calc_sla_penalty_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    SERVICE_PENALTY_EXPOSURE = eligible_penalty_basis × applicable_rate

    Requires:
    - evidence with evidence_type "penalty_eligible_basis" (a monetary or unit value)
    - assumption named "penalty_rate" (fraction or fixed amount)
    - assumption named "penalty_basis_currency" if basis is monetary
    """
    basis_evidence = [
        e for e in evidence
        if e.evidence_type in ("penalty_eligible_basis", "sla_penalty_basis")
    ]
    penalty_asmp = _resolve_assumption("penalty_rate", assumptions, assessment_timestamp)

    if not basis_evidence or penalty_asmp is None:
        return None

    try:
        basis = float(basis_evidence[0].value)
        rate = float(penalty_asmp.value)
        currency = penalty_asmp.currency or "UNKNOWN"
    except (TypeError, ValueError):
        return None

    exposure = basis * rate
    if penalty_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(penalty_asmp.assumption_id)

    calc = CalculationDetail(
        formula="eligible_penalty_basis × applicable_rate",
        inputs={"eligible_basis": basis, "rate": rate, "currency": currency},
        result=exposure,
        result_currency=currency,
        assumption_ids=[penalty_asmp.assumption_id],
        notes="Penalty rate sourced from assumption. Contractual rates must be supplied explicitly.",
    )

    fv = FinancialValue(
        amount=exposure,
        currency=currency,
        value_type="service_penalty_exposure",
        provenance=FinancialValueProvenance.DERIVED,
        source_reference=penalty_asmp.source,
        confidence=FinancialConfidence.MEDIUM,
    )

    return FinancialImpactFactor(
        category=FinancialImpactCategory.SERVICE_PENALTY_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in basis_evidence],
        assumption_ids=[penalty_asmp.assumption_id],
        provenance=FinancialValueProvenance.DERIVED,
        confidence=FinancialConfidence.MEDIUM,
        explanation=(
            f"SLA penalty exposure: {basis:.2f} basis × {rate:.4f} rate = "
            f"{exposure:.2f} {currency}."
        ),
    )


def _calc_revenue_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    REVENUE_EXPOSURE — Only calculated when explicit revenue-at-risk evidence exists.

    Requires:
    - evidence with evidence_type in ("revenue_at_risk", "affected_commitments_value",
      "service_revenue_value") carrying an amount
    - assumption named "revenue_per_commitment" if commitments count evidence is used

    Never converts risk scores directly to revenue.
    """
    direct_evidence = [
        e for e in evidence
        if e.evidence_type in ("revenue_at_risk", "affected_commitments_value", "service_revenue_value")
    ]

    if not direct_evidence:
        return None

    try:
        amount = float(direct_evidence[0].value)
    except (TypeError, ValueError):
        return None

    # Currency must come from an assumption or the evidence itself
    currency_asmp = _resolve_assumption("revenue_currency", assumptions, assessment_timestamp)
    currency = (currency_asmp.value if currency_asmp else None) or "UNKNOWN"
    asmp_ids = [currency_asmp.assumption_id] if currency_asmp else []
    for aid in asmp_ids:
        if aid not in assumption_ids_used:
            assumption_ids_used.append(aid)

    calc = CalculationDetail(
        formula="directly from evidence source",
        inputs={"amount": amount, "currency": currency},
        result=amount,
        result_currency=currency,
        assumption_ids=asmp_ids,
        notes="Revenue value sourced directly from evidence. "
              "Not inferred from risk scores.",
    )

    fv = FinancialValue(
        amount=amount,
        currency=currency,
        value_type="revenue_at_risk",
        provenance=FinancialValueProvenance.OBSERVED
        if direct_evidence[0].provenance == FinancialValueProvenance.OBSERVED
        else FinancialValueProvenance.ESTIMATED,
        source_reference=direct_evidence[0].source_reference,
        observed_at=direct_evidence[0].observation_timestamp,
        confidence=FinancialConfidence.MEDIUM,
    )

    return FinancialImpactFactor(
        category=FinancialImpactCategory.REVENUE_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in direct_evidence],
        assumption_ids=asmp_ids,
        provenance=fv.provenance,
        confidence=FinancialConfidence.MEDIUM,
        explanation=(
            f"Revenue exposure: {amount:.2f} {currency} sourced directly from "
            f"evidence type '{direct_evidence[0].evidence_type}'."
        ),
    )


def _calc_supplier_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    SUPPLIER_EXPOSURE — Analytically derived from supplier risk evidence
    combined with explicit expedite/disruption cost assumption.

    Requires:
    - evidence with evidence_type "supplier_disruption_value" or
      "expedite_cost_estimate"
    - OR: evidence with evidence_type "supplier_affected_commitments" + assumption
      "expedite_cost_per_unit"
    """
    direct_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "supplier_disruption_value", "expedite_cost_estimate",
            "supplier_financial_exposure"
        )
    ]

    if direct_evidence:
        try:
            amount = float(direct_evidence[0].value)
        except (TypeError, ValueError):
            return None
        currency_asmp = _resolve_assumption("supplier_exposure_currency", assumptions, assessment_timestamp)
        currency = (currency_asmp.value if currency_asmp else None) or "UNKNOWN"
        asmp_ids = [currency_asmp.assumption_id] if currency_asmp else []
        for aid in asmp_ids:
            if aid not in assumption_ids_used:
                assumption_ids_used.append(aid)

        calc = CalculationDetail(
            formula="directly from supplier evidence",
            inputs={"amount": amount, "currency": currency},
            result=amount,
            result_currency=currency,
            assumption_ids=asmp_ids,
        )
        fv = FinancialValue(
            amount=amount,
            currency=currency,
            value_type="supplier_exposure",
            provenance=FinancialValueProvenance.ESTIMATED,
            confidence=FinancialConfidence.MEDIUM,
        )
        return FinancialImpactFactor(
            category=FinancialImpactCategory.SUPPLIER_EXPOSURE,
            value=fv,
            calculation=calc,
            evidence_ids=[e.evidence_id for e in direct_evidence],
            assumption_ids=asmp_ids,
            provenance=FinancialValueProvenance.ESTIMATED,
            confidence=FinancialConfidence.MEDIUM,
            explanation=f"Supplier disruption exposure: {amount:.2f} {currency}.",
        )

    # Try commitments × expedite cost
    commitments_evidence = [
        e for e in evidence
        if e.evidence_type == "supplier_affected_commitments"
    ]
    expedite_asmp = _resolve_assumption("expedite_cost_per_unit", assumptions, assessment_timestamp)

    if not commitments_evidence or expedite_asmp is None:
        return None

    try:
        units = float(commitments_evidence[0].value)
        cost = float(expedite_asmp.value)
        currency = expedite_asmp.currency or "UNKNOWN"
    except (TypeError, ValueError):
        return None

    exposure = units * cost
    if expedite_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(expedite_asmp.assumption_id)

    calc = CalculationDetail(
        formula="affected_commitments × expedite_cost_per_unit",
        inputs={"units": units, "expedite_cost_per_unit": cost, "currency": currency},
        result=exposure,
        result_currency=currency,
        assumption_ids=[expedite_asmp.assumption_id],
    )
    fv = FinancialValue(
        amount=exposure,
        currency=currency,
        value_type="supplier_exposure",
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
    )
    return FinancialImpactFactor(
        category=FinancialImpactCategory.SUPPLIER_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in commitments_evidence],
        assumption_ids=[expedite_asmp.assumption_id],
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
        explanation=(
            f"Supplier exposure: {units:.0f} affected units × "
            f"{cost:.2f} {currency}/unit = {exposure:.2f} {currency}."
        ),
    )


def _calc_capacity_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    CAPACITY_EXPOSURE = shortfall_units × revenue_per_unit (or cost_per_unit)

    Requires:
    - evidence with evidence_type "capacity_shortfall_units"
    - assumption named "revenue_per_unit" or "cost_per_shortfall_unit" with currency
    """
    shortfall_evidence = [
        e for e in evidence
        if e.evidence_type in ("capacity_shortfall_units", "demand_shortfall_units")
    ]
    rate_asmp = (
        _resolve_assumption("revenue_per_unit", assumptions, assessment_timestamp)
        or _resolve_assumption("cost_per_shortfall_unit", assumptions, assessment_timestamp)
    )

    if not shortfall_evidence or rate_asmp is None:
        return None

    try:
        units = float(shortfall_evidence[0].value)
        rate = float(rate_asmp.value)
        currency = rate_asmp.currency or "UNKNOWN"
    except (TypeError, ValueError):
        return None

    exposure = units * rate
    if rate_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(rate_asmp.assumption_id)

    calc = CalculationDetail(
        formula="shortfall_units × revenue_per_unit",
        inputs={"shortfall_units": units, "rate": rate, "currency": currency},
        result=exposure,
        result_currency=currency,
        assumption_ids=[rate_asmp.assumption_id],
    )
    fv = FinancialValue(
        amount=exposure,
        currency=currency,
        value_type="capacity_exposure",
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
    )
    return FinancialImpactFactor(
        category=FinancialImpactCategory.CAPACITY_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in shortfall_evidence],
        assumption_ids=[rate_asmp.assumption_id],
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
        explanation=(
            f"Capacity exposure: {units:.0f} shortfall units × "
            f"{rate:.2f} {currency}/unit = {exposure:.2f} {currency}."
        ),
    )


def _calc_customer_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    CUSTOMER_EXPOSURE — from SLA / customer risk + explicit monetary assumptions.

    Requires:
    - evidence with evidence_type "customer_value_at_risk" or "affected_customer_value"
    - OR: sla_breach_probability evidence + "customer_lifetime_value" assumption

    Never assumes every breach = lost revenue.
    """
    direct_evidence = [
        e for e in evidence
        if e.evidence_type in ("customer_value_at_risk", "affected_customer_value", "customer_financial_exposure")
    ]

    if direct_evidence:
        try:
            amount = float(direct_evidence[0].value)
        except (TypeError, ValueError):
            return None
        currency_asmp = _resolve_assumption("customer_currency", assumptions, assessment_timestamp)
        currency = (currency_asmp.value if currency_asmp else None) or "UNKNOWN"
        asmp_ids = [currency_asmp.assumption_id] if currency_asmp else []
        for aid in asmp_ids:
            if aid not in assumption_ids_used:
                assumption_ids_used.append(aid)

        calc = CalculationDetail(
            formula="directly from customer evidence",
            inputs={"amount": amount, "currency": currency},
            result=amount,
            result_currency=currency,
            assumption_ids=asmp_ids,
        )
        fv = FinancialValue(
            amount=amount,
            currency=currency,
            value_type="customer_exposure",
            provenance=FinancialValueProvenance.ESTIMATED,
            confidence=FinancialConfidence.MEDIUM,
        )
        return FinancialImpactFactor(
            category=FinancialImpactCategory.CUSTOMER_EXPOSURE,
            value=fv,
            calculation=calc,
            evidence_ids=[e.evidence_id for e in direct_evidence],
            assumption_ids=asmp_ids,
            provenance=FinancialValueProvenance.ESTIMATED,
            confidence=FinancialConfidence.MEDIUM,
            explanation=f"Customer exposure: {amount:.2f} {currency}.",
        )

    # Probability-based estimate
    breach_evidence = [
        e for e in evidence
        if e.evidence_type in ("sla_breach_probability", "breach_probability")
    ]
    clv_asmp = _resolve_assumption("customer_lifetime_value", assumptions, assessment_timestamp)

    if not breach_evidence or clv_asmp is None:
        return None

    try:
        probability = float(breach_evidence[0].value)
        clv = float(clv_asmp.value)
        currency = clv_asmp.currency or "UNKNOWN"
    except (TypeError, ValueError):
        return None

    # Probability must be [0,1]
    probability = max(0.0, min(1.0, probability))
    exposure = probability * clv
    if clv_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(clv_asmp.assumption_id)

    calc = CalculationDetail(
        formula="breach_probability × customer_lifetime_value",
        inputs={"breach_probability": probability, "clv": clv, "currency": currency},
        result=exposure,
        result_currency=currency,
        assumption_ids=[clv_asmp.assumption_id],
        notes="Probabilistic estimate; NOT claimed as realized loss.",
    )
    fv = FinancialValue(
        amount=exposure,
        currency=currency,
        value_type="customer_exposure_estimated",
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
    )
    return FinancialImpactFactor(
        category=FinancialImpactCategory.CUSTOMER_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in breach_evidence],
        assumption_ids=[clv_asmp.assumption_id],
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
        explanation=(
            f"Customer exposure (ESTIMATED): {probability:.1%} breach probability × "
            f"{clv:.2f} {currency} CLV = {exposure:.2f} {currency}. "
            "This is an analytical estimate, NOT a realized revenue loss."
        ),
    )


def _calc_maintenance_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    MAINTENANCE_EXPOSURE = expected_downtime_hours × cost_per_maintenance_hour
    OR maintenance_cost_estimate from direct evidence.

    Requires:
    - evidence with evidence_type in ("expected_maintenance_downtime_hours",
      "maintenance_cost_estimate")
    - assumption named "cost_per_maintenance_hour" or "maintenance_fixed_cost"
    """
    direct_evidence = [
        e for e in evidence
        if e.evidence_type in ("maintenance_cost_estimate", "expected_maintenance_cost")
    ]

    if direct_evidence:
        try:
            amount = float(direct_evidence[0].value)
        except (TypeError, ValueError):
            return None
        currency_asmp = _resolve_assumption("maintenance_cost_currency", assumptions, assessment_timestamp)
        currency = (currency_asmp.value if currency_asmp else None) or "UNKNOWN"
        asmp_ids = [currency_asmp.assumption_id] if currency_asmp else []
        for aid in asmp_ids:
            if aid not in assumption_ids_used:
                assumption_ids_used.append(aid)

        calc = CalculationDetail(
            formula="directly from maintenance cost evidence",
            inputs={"amount": amount, "currency": currency},
            result=amount,
            result_currency=currency,
            assumption_ids=asmp_ids,
        )
        fv = FinancialValue(
            amount=amount,
            currency=currency,
            value_type="maintenance_exposure",
            provenance=FinancialValueProvenance.ESTIMATED,
            confidence=FinancialConfidence.MEDIUM,
        )
        return FinancialImpactFactor(
            category=FinancialImpactCategory.MAINTENANCE_EXPOSURE,
            value=fv,
            calculation=calc,
            evidence_ids=[e.evidence_id for e in direct_evidence],
            assumption_ids=asmp_ids,
            provenance=FinancialValueProvenance.ESTIMATED,
            confidence=FinancialConfidence.MEDIUM,
            explanation=f"Maintenance cost exposure: {amount:.2f} {currency} from evidence.",
        )

    downtime_evidence = [
        e for e in evidence
        if e.evidence_type == "expected_maintenance_downtime_hours"
    ]
    cost_asmp = (
        _resolve_assumption("cost_per_maintenance_hour", assumptions, assessment_timestamp)
        or _resolve_assumption("maintenance_fixed_cost", assumptions, assessment_timestamp)
    )

    if not downtime_evidence or cost_asmp is None:
        return None

    try:
        hours = float(downtime_evidence[0].value)
        rate = float(cost_asmp.value)
        currency = cost_asmp.currency or "UNKNOWN"
    except (TypeError, ValueError):
        return None

    exposure = hours * rate
    if cost_asmp.assumption_id not in assumption_ids_used:
        assumption_ids_used.append(cost_asmp.assumption_id)

    calc = CalculationDetail(
        formula="expected_downtime_hours × cost_per_maintenance_hour",
        inputs={"hours": hours, "rate": rate, "currency": currency},
        result=exposure,
        result_currency=currency,
        assumption_ids=[cost_asmp.assumption_id],
    )
    fv = FinancialValue(
        amount=exposure,
        currency=currency,
        value_type="maintenance_exposure",
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
    )
    return FinancialImpactFactor(
        category=FinancialImpactCategory.MAINTENANCE_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in downtime_evidence],
        assumption_ids=[cost_asmp.assumption_id],
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.LOW,
        explanation=(
            f"Maintenance exposure: {hours:.2f} hours × "
            f"{rate:.2f} {currency}/hour = {exposure:.2f} {currency}."
        ),
    )


def _calc_cost_exposure(
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    assumption_ids_used: List[str],
    assessment_timestamp: str,
) -> Optional[FinancialImpactFactor]:
    """
    COST_EXPOSURE — General operational cost from direct evidence.

    Requires:
    - evidence with evidence_type in ("operational_cost_estimate",
      "emergency_cost_estimate", "overtime_cost_estimate", "expedited_cost")
    """
    direct_evidence = [
        e for e in evidence
        if e.evidence_type in (
            "operational_cost_estimate", "emergency_cost_estimate",
            "overtime_cost_estimate", "expedited_cost", "cost_exposure"
        )
    ]

    if not direct_evidence:
        return None

    try:
        amount = float(direct_evidence[0].value)
    except (TypeError, ValueError):
        return None

    currency_asmp = _resolve_assumption("operational_cost_currency", assumptions, assessment_timestamp)
    currency = (currency_asmp.value if currency_asmp else None) or "UNKNOWN"
    asmp_ids = [currency_asmp.assumption_id] if currency_asmp else []
    for aid in asmp_ids:
        if aid not in assumption_ids_used:
            assumption_ids_used.append(aid)

    calc = CalculationDetail(
        formula="directly from cost evidence",
        inputs={"amount": amount, "currency": currency},
        result=amount,
        result_currency=currency,
        assumption_ids=asmp_ids,
    )
    fv = FinancialValue(
        amount=amount,
        currency=currency,
        value_type="cost_exposure",
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.MEDIUM,
    )
    return FinancialImpactFactor(
        category=FinancialImpactCategory.COST_EXPOSURE,
        value=fv,
        calculation=calc,
        evidence_ids=[e.evidence_id for e in direct_evidence],
        assumption_ids=asmp_ids,
        provenance=FinancialValueProvenance.ESTIMATED,
        confidence=FinancialConfidence.MEDIUM,
        explanation=f"Operational cost exposure: {amount:.2f} {currency}.",
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregate_factors(
    factors: List[FinancialImpactFactor],
    currency_conversions: List[ExplicitCurrencyConversion],
    assessment_timestamp: str,
) -> Tuple[FinancialValue, CurrencyAggregationStatus, Optional[str]]:
    """
    Aggregate monetary factors into a total exposure.

    Rules:
    - Skip UNKNOWN factors.
    - If all known factors share one currency: aggregate directly.
    - If multiple currencies: try explicit conversion to first currency found.
    - If conversion unavailable: return INCOMPATIBLE_CURRENCY.
    - Return NO_MONETARY_VALUE if nothing is monetary.
    """
    monetary_factors = [
        f for f in factors
        if f.value.is_monetary
    ]

    if not monetary_factors:
        return (
            FinancialValue(
                provenance=FinancialValueProvenance.UNKNOWN,
                confidence=FinancialConfidence.INSUFFICIENT_DATA,
            ),
            CurrencyAggregationStatus.NO_MONETARY_VALUE,
            None,
        )

    currencies_present = list(dict.fromkeys(f.value.currency for f in monetary_factors))

    if len(currencies_present) == 1:
        total = sum(f.value.amount for f in monetary_factors)  # type: ignore[arg-type]
        currency = currencies_present[0]
        # Confidence is the minimum of component confidences
        conf_order = [
            FinancialConfidence.INSUFFICIENT_DATA,
            FinancialConfidence.LOW,
            FinancialConfidence.MEDIUM,
            FinancialConfidence.HIGH,
        ]
        min_conf = min(
            monetary_factors,
            key=lambda f: conf_order.index(f.confidence),
        ).confidence
        return (
            FinancialValue(
                amount=total,
                currency=currency,
                value_type="total_financial_exposure",
                provenance=FinancialValueProvenance.DERIVED,
                confidence=min_conf,
            ),
            CurrencyAggregationStatus.SINGLE_CURRENCY,
            currency,
        )

    # Multi-currency: attempt explicit conversion
    base_currency = currencies_present[0]
    conv_map: Dict[str, float] = {}
    for conv in currency_conversions:
        # Check temporal validity
        if conv.rate_timestamp <= assessment_timestamp:
            conv_map[f"{conv.from_currency}:{conv.to_currency}"] = conv.rate
            conv_map[f"{conv.to_currency}:{conv.from_currency}"] = 1.0 / conv.rate

    total = 0.0
    conversion_ok = True
    for f in monetary_factors:
        if f.value.currency == base_currency:
            total += f.value.amount  # type: ignore[operator]
        else:
            key = f"{f.value.currency}:{base_currency}"
            if key in conv_map:
                total += f.value.amount * conv_map[key]  # type: ignore[operator]
            else:
                conversion_ok = False
                break

    if not conversion_ok:
        return (
            FinancialValue(
                provenance=FinancialValueProvenance.UNKNOWN,
                confidence=FinancialConfidence.INSUFFICIENT_DATA,
            ),
            CurrencyAggregationStatus.INCOMPATIBLE_CURRENCY,
            None,
        )

    return (
        FinancialValue(
            amount=total,
            currency=base_currency,
            value_type="total_financial_exposure_converted",
            provenance=FinancialValueProvenance.DERIVED,
            confidence=FinancialConfidence.LOW,  # Conversion adds uncertainty
        ),
        CurrencyAggregationStatus.AGGREGATED,
        base_currency,
    )


# ---------------------------------------------------------------------------
# Confidence Calculation
# ---------------------------------------------------------------------------

def _calc_overall_confidence(
    factors: List[FinancialImpactFactor],
    evidence: List[FinancialEvidence],
    assumptions: List[FinancialAssumption],
    data_quality_issues: List[str],
) -> Tuple[FinancialConfidence, str]:
    """
    Overall confidence considers:
    - Number of known (non-UNKNOWN) factors
    - Evidence quality (evidence_count, staleness)
    - Assumption completeness
    - Data quality issues
    - Upstream model confidence
    - Currency compatibility
    """
    known_factors = [f for f in factors if f.value.is_known]
    if not known_factors:
        return (
            FinancialConfidence.INSUFFICIENT_DATA,
            "No monetary impact factors could be calculated from available evidence and assumptions.",
        )

    if len(data_quality_issues) > 2:
        return (
            FinancialConfidence.LOW,
            f"Multiple data quality issues present: {', '.join(data_quality_issues[:3])}.",
        )

    # Check if assumptions have low confidence
    low_conf_assumptions = [
        a for a in assumptions
        if a.confidence in (FinancialConfidence.LOW, FinancialConfidence.INSUFFICIENT_DATA)
    ]
    if low_conf_assumptions:
        return (
            FinancialConfidence.LOW,
            f"{len(low_conf_assumptions)} assumption(s) have low confidence.",
        )

    # Check stale evidence (simplistic: if provenance is UNKNOWN)
    unknown_evidence = [
        e for e in evidence
        if e.provenance == FinancialValueProvenance.UNKNOWN
    ]
    if unknown_evidence:
        return (
            FinancialConfidence.LOW,
            f"{len(unknown_evidence)} evidence item(s) have UNKNOWN provenance.",
        )

    if len(known_factors) >= 3 and len(evidence) >= 3:
        return (
            FinancialConfidence.HIGH,
            "Multiple corroborating evidence sources and validated assumptions.",
        )
    if len(known_factors) >= 1 and len(evidence) >= 1:
        return (
            FinancialConfidence.MEDIUM,
            "Sufficient evidence and assumptions for a medium-confidence estimate.",
        )
    return (
        FinancialConfidence.LOW,
        "Limited evidence or assumptions; estimate has high uncertainty.",
    )


# ---------------------------------------------------------------------------
# Main Service
# ---------------------------------------------------------------------------

class FinancialImpactService:
    """
    Deterministic Financial Impact Intelligence Service.

    Calculation flow:
    1. Validate inputs
    2. Normalize evidence (temporal leakage protection)
    3. Parse and validate assumptions (temporal validity)
    4. Determine eligible impact categories
    5. Calculate deterministic impacts (never invent monetary values)
    6. Aggregate (currency-safe)
    7. Calculate overall confidence
    8. Build assessment object
    9. Generate fingerprint
    10. Persist assessment
    11. Return typed result

    DOES NOT:
    - Execute any financial transactions
    - Mutate suppliers, customers, SLA records, inventory, or physical systems
    - Fetch live FX rates
    - Invoke the Execution Gateway or Action API
    - Generate LLM-based monetary values
    """

    def analyze(
        self,
        tenant_id: str,
        assessment_timestamp: str,
        evidence_payloads: List[Dict[str, Any]],
        raw_assumptions: List[Dict[str, Any]],
        raw_currency_conversions: List[Dict[str, Any]],
        scenario_name: FinancialImpactScenario = FinancialImpactScenario.EXPECTED,
        custom_scenario_name: str = "",
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        service_id: Optional[str] = None,
        calculation_version: str = "v1.0",
        sla_assessment_id: Optional[str] = None,
        supplier_risk_assessment_id: Optional[str] = None,
        maintenance_assessment_id: Optional[str] = None,
        demand_forecast_id: Optional[str] = None,
        blast_radius_id: Optional[str] = None,
    ) -> FinancialImpactAssessment:

        data_quality_issues: List[str] = []
        known_limitations: List[str] = []

        # 1. Normalize evidence — temporal leakage protection
        processed_evidence: List[FinancialEvidence] = []
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
                prov = FinancialValueProvenance(prov_raw) if prov_raw in FinancialValueProvenance._value2member_map_ else FinancialValueProvenance.UNKNOWN
                evd = FinancialEvidence(
                    source_domain=ep.get("source_domain", "UNKNOWN"),
                    source_reference=ep.get("source_reference", "unknown"),
                    observation_timestamp=obs_ts or assessment_timestamp,
                    evidence_type=ep.get("evidence_type", "unknown"),
                    value=ep.get("value"),
                    confidence=float(ep.get("confidence", 1.0)),
                    provenance=prov,
                    explanation=ep.get("explanation", ""),
                )
                processed_evidence.append(evd)
            except Exception:
                data_quality_issues.append("EVIDENCE_PARSE_ERROR")

        # 2. Parse and validate assumptions — temporal validity enforced
        validated_assumptions: List[FinancialAssumption] = []
        for ap in raw_assumptions:
            try:
                prov_raw = ap.get("provenance", "UNKNOWN")
                prov = AssumptionProvenance(prov_raw) if prov_raw in AssumptionProvenance._value2member_map_ else AssumptionProvenance.UNKNOWN
                conf_raw = ap.get("confidence", "MEDIUM")
                try:
                    conf = FinancialConfidence(conf_raw)
                except ValueError:
                    conf = FinancialConfidence.MEDIUM
                asmp = FinancialAssumption(
                    name=ap["name"],
                    description=ap.get("description", ""),
                    value=ap["value"],
                    unit=ap.get("unit", ""),
                    currency=ap.get("currency"),
                    source=ap.get("source", ""),
                    provenance=prov,
                    effective_from=ap.get("effective_from"),
                    effective_to=ap.get("effective_to"),
                    confidence=conf,
                    user_supplied=bool(ap.get("user_supplied", True)),
                )
                # Temporal validity check — exclude future assumptions
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
                "No validated monetary assumptions provided. "
                "Most impact categories require explicit assumptions to calculate."
            )

        # 3. Parse currency conversions
        parsed_conversions: List[ExplicitCurrencyConversion] = []
        for conv in raw_currency_conversions:
            try:
                c = ExplicitCurrencyConversion(
                    from_currency=conv["from_currency"],
                    to_currency=conv["to_currency"],
                    rate=float(conv["rate"]),
                    rate_timestamp=conv["rate_timestamp"],
                    source=conv.get("source", ""),
                    provenance=AssumptionProvenance(
                        conv.get("provenance", "USER_SUPPLIED")
                    ),
                )
                if c.rate_timestamp > assessment_timestamp:
                    data_quality_issues.append(
                        f"FUTURE_CONVERSION_RATE_EXCLUDED:{c.from_currency}:{c.to_currency}"
                    )
                    continue
                parsed_conversions.append(c)
            except Exception:
                data_quality_issues.append("CURRENCY_CONVERSION_PARSE_ERROR")

        # 4. Build scenario
        scenario = FinancialScenarioContext(
            scenario_name=scenario_name,
            custom_name=custom_scenario_name,
            description=f"Financial impact assessment scenario: {scenario_name.value}",
            provenance=(
                FinancialValueProvenance.SIMULATED
                if scenario_name in (FinancialImpactScenario.STRESS, FinancialImpactScenario.CUSTOM)
                else FinancialValueProvenance.ESTIMATED
            ),
            calculation_version=calculation_version,
        )

        # 5. Run impact calculators
        assumption_ids_used: List[str] = []
        factors: List[FinancialImpactFactor] = []

        calculators = [
            _calc_downtime_exposure,
            _calc_sla_penalty_exposure,
            _calc_revenue_exposure,
            _calc_supplier_exposure,
            _calc_capacity_exposure,
            _calc_customer_exposure,
            _calc_maintenance_exposure,
            _calc_cost_exposure,
        ]

        for calc_fn in calculators:
            try:
                factor = calc_fn(
                    processed_evidence,
                    validated_assumptions,
                    assumption_ids_used,
                    assessment_timestamp,
                )
                if factor is not None:
                    factors.append(factor)
            except Exception:
                data_quality_issues.append(f"CALCULATOR_ERROR:{calc_fn.__name__}")

        # Record UNKNOWN factors for categories with no calculable value
        calculated_categories = {f.category for f in factors}
        for cat in FinancialImpactCategory:
            if cat not in calculated_categories:
                factors.append(
                    FinancialImpactFactor(
                        category=cat,
                        value=_unknown_value(cat.value),
                        provenance=FinancialValueProvenance.UNKNOWN,
                        confidence=FinancialConfidence.INSUFFICIENT_DATA,
                        explanation=(
                            f"{cat.value}: UNKNOWN — insufficient evidence or "
                            "assumptions to calculate this exposure."
                        ),
                        data_quality_issues=["INSUFFICIENT_EVIDENCE_OR_ASSUMPTIONS"],
                    )
                )

        # 6. Aggregate
        total_exposure, aggregation_status, aggregation_currency = _aggregate_factors(
            factors, parsed_conversions, assessment_timestamp
        )
        if aggregation_status == CurrencyAggregationStatus.INCOMPATIBLE_CURRENCY:
            known_limitations.append(
                "Multiple incompatible currencies detected. "
                "Provide explicit timestamped conversion rates to aggregate."
            )

        # 7. Overall confidence
        confidence, confidence_rationale = _calc_overall_confidence(
            factors, processed_evidence, validated_assumptions, data_quality_issues
        )

        # 8. Integration context
        integration_ctx = FinancialIntegrationContext(
            sla_customer_risk_ids=[sla_assessment_id] if sla_assessment_id else [],
            supplier_risk_ids=[supplier_risk_assessment_id] if supplier_risk_assessment_id else [],
            maintenance_assessment_ids=[maintenance_assessment_id] if maintenance_assessment_id else [],
            demand_forecast_ids=[demand_forecast_id] if demand_forecast_id else [],
            blast_radius_ids=[blast_radius_id] if blast_radius_id else [],
        )

        # 9. Assemble assessment
        assessment = FinancialImpactAssessment(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            customer_id=customer_id,
            supplier_id=supplier_id,
            asset_id=asset_id,
            service_id=service_id,
            assessment_timestamp=assessment_timestamp,
            calculation_version=calculation_version,
            scenario=scenario,
            factors=factors,
            total_exposure=total_exposure,
            aggregation_status=aggregation_status,
            aggregation_currency=aggregation_currency,
            confidence=confidence,
            confidence_rationale=confidence_rationale,
            evidence=processed_evidence,
            assumptions=validated_assumptions,
            currency_conversions=parsed_conversions,
            integration_context=integration_ctx,
            data_quality_issues=data_quality_issues,
            known_limitations=known_limitations,
        )

        # 10. Fingerprint
        assessment.generate_fingerprint()

        # 11. Persist
        return financial_impact_repository.save_assessment(assessment)


financial_impact_service = FinancialImpactService()
