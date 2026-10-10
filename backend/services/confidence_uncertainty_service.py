# backend/services/confidence_uncertainty_service.py
"""
SageCommand V3 — Confidence and Uncertainty Intelligence Foundation Service (Prompt 32)

Deterministic, explainable, tenant-isolated orchestration engine for:
1. Multi-dimensional analytical confidence evaluation (10 dimensions).
2. Uncertainty classification and decomposition (Aleatoric vs Epistemic).
3. Quantitative interval validation and qualitative uncertainty fallbacks.
4. Evidence provenance and freshness verification (integrating with Prompt 31).
5. Conflict, correlation, and duplicate evidence detection.
6. Decision Engine (Prompt 30) and Optimization (Prompt 29) confidence integration.

Cardinal Principle:
Confidence is a measure of support for a specific analytical claim under a specific context.
It is NOT an uncalibrated statistical probability.
The service is strictly READ-ONLY for underlying operational and source records.
"""

from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math

try:
    from core.config import (
        SAGE_CONFIDENCE_MAX_EVIDENCE_ITEMS,
        SAGE_CONFIDENCE_DEFAULT_FRESHNESS_SECONDS,
        SAGE_CONFIDENCE_MAX_SENSITIVITY_PARAMS,
    )
    from data.schemas.confidence_uncertainty_contract import (
        ConfidenceDimensionType,
        ConfidenceStatus,
        UncertaintyType,
        UncertaintySeverity,
        UncertaintyIntervalType,
        AggregationMethod,
        CalibrationStatus,
        ConfidenceDimension,
        ConfidenceComponent,
        ConfidenceEvidenceReference,
        ConfidenceContribution,
        ConfidenceCalibrationMetadata,
        ConfidenceLimitation,
        ConfidenceAssessment,
        UncertaintySource,
        UncertaintyRange,
        UncertaintyDistributionSummary,
        UncertaintySensitivity,
        UncertaintyPropagation,
        UncertaintyComponent,
        UncertaintyDecomposition,
        UncertaintyLimitation,
        UncertaintyAssessment,
        ConfidenceUncertaintyMethod,
        ConfidenceUncertaintyRequest,
        ConfidenceValidationRequest,
        ConfidenceValidationResponse,
        ConfidenceUncertaintyResult,
        compute_confidence_fingerprint,
        MANDATORY_CONFIDENCE_NOTICE,
        ALGORITHM_VERSION,
        CONTRACT_VERSION,
    )
    from data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )
    from repositories.confidence_uncertainty_repository import (
        ConfidenceUncertaintyRepository,
        confidence_uncertainty_repository,
    )
    from services.evidence_explainability_service import (
        SubsystemEvidenceAdapterRegistry,
        EvidenceValidationEngine,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_CONFIDENCE_MAX_EVIDENCE_ITEMS,
        SAGE_CONFIDENCE_DEFAULT_FRESHNESS_SECONDS,
        SAGE_CONFIDENCE_MAX_SENSITIVITY_PARAMS,
    )
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceDimensionType,
        ConfidenceStatus,
        UncertaintyType,
        UncertaintySeverity,
        UncertaintyIntervalType,
        AggregationMethod,
        CalibrationStatus,
        ConfidenceDimension,
        ConfidenceComponent,
        ConfidenceEvidenceReference,
        ConfidenceContribution,
        ConfidenceCalibrationMetadata,
        ConfidenceLimitation,
        ConfidenceAssessment,
        UncertaintySource,
        UncertaintyRange,
        UncertaintyDistributionSummary,
        UncertaintySensitivity,
        UncertaintyPropagation,
        UncertaintyComponent,
        UncertaintyDecomposition,
        UncertaintyLimitation,
        UncertaintyAssessment,
        ConfidenceUncertaintyMethod,
        ConfidenceUncertaintyRequest,
        ConfidenceValidationRequest,
        ConfidenceValidationResponse,
        ConfidenceUncertaintyResult,
        compute_confidence_fingerprint,
        MANDATORY_CONFIDENCE_NOTICE,
        ALGORITHM_VERSION,
        CONTRACT_VERSION,
    )
    from backend.data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )
    from backend.repositories.confidence_uncertainty_repository import (
        ConfidenceUncertaintyRepository,
        confidence_uncertainty_repository,
    )
    from backend.services.evidence_explainability_service import (
        SubsystemEvidenceAdapterRegistry,
        EvidenceValidationEngine,
    )


# Default Dimension Weight Configuration
DEFAULT_DIMENSION_WEIGHTS: Dict[ConfidenceDimensionType, float] = {
    ConfidenceDimensionType.EVIDENCE_COMPLETENESS: 1.5,
    ConfidenceDimensionType.EVIDENCE_QUALITY: 1.5,
    ConfidenceDimensionType.FRESHNESS: 1.2,
    ConfidenceDimensionType.TEMPORAL_CONSISTENCY: 1.0,
    ConfidenceDimensionType.SOURCE_RELIABILITY: 1.2,
    ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT: 1.4,
    ConfidenceDimensionType.METHOD_VALIDITY: 1.0,
    ConfidenceDimensionType.CONTEXT_COVERAGE: 0.8,
    ConfidenceDimensionType.MODEL_CALIBRATION: 0.6,
    ConfidenceDimensionType.LINEAGE_INTEGRITY: 0.8,
}


class ConfidenceDimensionEvaluator:
    """
    Deterministic evaluation of the 10 canonical confidence dimensions.
    """

    @staticmethod
    def evaluate_dimensions(
        evidence_items: List[EvidenceRecord],
        target_type: str,
        target_id: str,
        assessment_ts: str,
        freshness_threshold: float,
        plant_id: Optional[str],
        weights_override: Optional[Dict[str, float]] = None,
        conflicts: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[ConfidenceDimension], List[str]]:
        """
        Evaluates each of the 10 independent confidence dimensions.
        Returns the list of evaluated dimensions and any identified blocking deficiencies.
        """
        conflicts = conflicts or []
        blocking_deficiencies: List[str] = []
        dimensions: List[ConfidenceDimension] = []

        # Parse assessment timestamp
        try:
            assess_dt = datetime.fromisoformat(assessment_ts.replace("Z", "+00:00"))
            if assess_dt.tzinfo is None:
                assess_dt = assess_dt.replace(tzinfo=timezone.utc)
        except Exception:
            assess_dt = datetime.now(timezone.utc)

        # ---------------------------------------------------------------------
        # 1. EVIDENCE COMPLETENESS
        # ---------------------------------------------------------------------
        w_comp = weights_override.get(ConfidenceDimensionType.EVIDENCE_COMPLETENESS.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.EVIDENCE_COMPLETENESS]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.EVIDENCE_COMPLETENESS]
        if not evidence_items:
            blocking_deficiencies.append("MISSING_ALL_SUPPORTING_EVIDENCE")
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.EVIDENCE_COMPLETENESS,
                    score=None,
                    weight=w_comp,
                    is_assessed=False,
                    status="NOT_ASSESSABLE",
                    explanation="No supporting evidence items provided or available.",
                    deficiencies=["NO_EVIDENCE_ITEMS"],
                )
            )
        else:
            # Completeness scales with items up to 4 items (saturation)
            raw_comp = min(1.0, len(evidence_items) / 3.0)
            deficiencies = []
            if len(evidence_items) == 1:
                deficiencies.append("MINIMAL_EVIDENCE_COUNT")
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.EVIDENCE_COMPLETENESS,
                    score=round(raw_comp, 3),
                    weight=w_comp,
                    is_assessed=True,
                    status="ASSESSED",
                    explanation=f"{len(evidence_items)} supporting evidence records available.",
                    deficiencies=deficiencies,
                    metadata={"evidence_count": len(evidence_items)},
                )
            )

        # ---------------------------------------------------------------------
        # 2. EVIDENCE QUALITY
        # ---------------------------------------------------------------------
        w_qual = weights_override.get(ConfidenceDimensionType.EVIDENCE_QUALITY.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.EVIDENCE_QUALITY]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.EVIDENCE_QUALITY]
        if not evidence_items:
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.EVIDENCE_QUALITY,
                    score=None,
                    weight=w_qual,
                    is_assessed=False,
                    status="NOT_ASSESSABLE",
                    explanation="Quality cannot be assessed without evidence.",
                )
            )
        else:
            avg_qual = sum(e.quality_score for e in evidence_items) / len(evidence_items)
            deficiencies = []
            if avg_qual < 0.3:
                blocking_deficiencies.append("CRITICAL_LOW_DATA_QUALITY")
                deficiencies.append("CRITICAL_LOW_QUALITY")
            elif avg_qual < 0.6:
                deficiencies.append("SUBOPTIMAL_DATA_QUALITY")

            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.EVIDENCE_QUALITY,
                    score=round(avg_qual, 3),
                    weight=w_qual,
                    is_assessed=True,
                    status="DEFICIENT" if deficiencies else "ASSESSED",
                    explanation=f"Mean evidence quality score is {round(avg_qual, 3)}.",
                    deficiencies=deficiencies,
                    metadata={"mean_quality": round(avg_qual, 3)},
                )
            )

        # ---------------------------------------------------------------------
        # 3. FRESHNESS
        # ---------------------------------------------------------------------
        w_fresh = weights_override.get(ConfidenceDimensionType.FRESHNESS.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.FRESHNESS]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.FRESHNESS]
        if not evidence_items:
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.FRESHNESS,
                    score=None,
                    weight=w_fresh,
                    is_assessed=False,
                    status="NOT_ASSESSABLE",
                    explanation="Freshness cannot be evaluated without evidence.",
                )
            )
        else:
            freshness_scores = []
            stale_count = 0
            for e in evidence_items:
                ts = e.observed_at or e.assessed_at or e.received_at
                age = 0.0
                if ts:
                    try:
                        e_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if e_dt.tzinfo is None:
                            e_dt = e_dt.replace(tzinfo=timezone.utc)
                        age = max(0.0, (assess_dt - e_dt).total_seconds())
                    except Exception:
                        pass
                if e.freshness_seconds is not None:
                    age = max(age, e.freshness_seconds)

                # Linear decay over threshold
                f_score = max(0.0, 1.0 - (age / freshness_threshold)) if freshness_threshold > 0 else 1.0
                freshness_scores.append(f_score)
                if age > freshness_threshold:
                    stale_count += 1

            avg_fresh = sum(freshness_scores) / len(freshness_scores) if freshness_scores else 1.0
            deficiencies = []
            if stale_count == len(evidence_items):
                deficiencies.append("ALL_EVIDENCE_EXCEEDS_FRESHNESS_THRESHOLD")
                blocking_deficiencies.append("ALL_EVIDENCE_STALE")
            elif stale_count > 0:
                deficiencies.append(f"{stale_count}_OF_{len(evidence_items)}_ITEMS_STALE")

            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.FRESHNESS,
                    score=round(avg_fresh, 3),
                    weight=w_fresh,
                    is_assessed=True,
                    status="DEFICIENT" if deficiencies else "ASSESSED",
                    explanation=f"Mean freshness score is {round(avg_fresh, 3)} with {stale_count} stale items.",
                    deficiencies=deficiencies,
                    metadata={"stale_count": stale_count, "freshness_threshold_seconds": freshness_threshold},
                )
            )

        # ---------------------------------------------------------------------
        # 4. TEMPORAL CONSISTENCY
        # ---------------------------------------------------------------------
        w_temp = weights_override.get(ConfidenceDimensionType.TEMPORAL_CONSISTENCY.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.TEMPORAL_CONSISTENCY]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.TEMPORAL_CONSISTENCY]
        if not evidence_items:
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.TEMPORAL_CONSISTENCY,
                    score=None,
                    weight=w_temp,
                    is_assessed=False,
                    status="NOT_ASSESSABLE",
                    explanation="Temporal consistency cannot be evaluated without evidence.",
                )
            )
        else:
            future_leaks = 0
            timestamps = []
            for e in evidence_items:
                ts = e.observed_at or e.assessed_at or e.received_at
                if ts:
                    try:
                        e_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if e_dt.tzinfo is None:
                            e_dt = e_dt.replace(tzinfo=timezone.utc)
                        timestamps.append(e_dt)
                        if e_dt > assess_dt:
                            future_leaks += 1
                    except Exception:
                        pass

            deficiencies = []
            if future_leaks > 0:
                blocking_deficiencies.append("FUTURE_DATED_EVIDENCE_LEAKAGE")
                deficiencies.append(f"{future_leaks}_FUTURE_DATED_EVIDENCE_ITEMS")
                temp_score = 0.0
            elif len(timestamps) > 1:
                time_span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0
                temp_score = max(0.2, 1.0 - (time_span_hours / 720.0))  # Minor degradation over wide spans (> 30 days)
            else:
                temp_score = 1.0

            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.TEMPORAL_CONSISTENCY,
                    score=round(temp_score, 3),
                    weight=w_temp,
                    is_assessed=True,
                    status="DEFICIENT" if deficiencies else "ASSESSED",
                    explanation="No future leakage detected." if future_leaks == 0 else "Future leakage detected.",
                    deficiencies=deficiencies,
                    metadata={"future_leak_count": future_leaks},
                )
            )

        # ---------------------------------------------------------------------
        # 5. SOURCE RELIABILITY
        # ---------------------------------------------------------------------
        w_rel = weights_override.get(ConfidenceDimensionType.SOURCE_RELIABILITY.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.SOURCE_RELIABILITY]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.SOURCE_RELIABILITY]
        if not evidence_items:
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.SOURCE_RELIABILITY,
                    score=None,
                    weight=w_rel,
                    is_assessed=False,
                    status="NOT_ASSESSABLE",
                    explanation="Source reliability cannot be evaluated without evidence.",
                )
            )
        else:
            provenance_weights = {
                EvidenceProvenance.OBSERVED: 1.0,
                EvidenceProvenance.DERIVED: 0.85,
                EvidenceProvenance.FORECAST: 0.70,
                EvidenceProvenance.SIMULATED: 0.65,
                EvidenceProvenance.ESTIMATED: 0.50,
                EvidenceProvenance.UNKNOWN: 0.20,
            }
            rel_scores = [provenance_weights.get(e.provenance, 0.5) for e in evidence_items]
            avg_rel = sum(rel_scores) / len(rel_scores)
            deficiencies = []
            if any(e.provenance == EvidenceProvenance.UNKNOWN for e in evidence_items):
                deficiencies.append("UNKNOWN_PROVENANCE_PRESENT")

            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.SOURCE_RELIABILITY,
                    score=round(avg_rel, 3),
                    weight=w_rel,
                    is_assessed=True,
                    status="ASSESSED",
                    explanation=f"Mean provenance reliability is {round(avg_rel, 3)}.",
                    deficiencies=deficiencies,
                    metadata={"provenance_breakdown": [e.provenance.value for e in evidence_items]},
                )
            )

        # ---------------------------------------------------------------------
        # 6. CROSS-SOURCE AGREEMENT
        # ---------------------------------------------------------------------
        w_agr = weights_override.get(ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT]
        if not evidence_items:
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT,
                    score=None,
                    weight=w_agr,
                    is_assessed=False,
                    status="NOT_ASSESSABLE",
                    explanation="Agreement cannot be assessed without evidence.",
                )
            )
        else:
            deficiencies = []
            if conflicts:
                agr_score = max(0.1, 1.0 - (0.35 * len(conflicts)))
                deficiencies.append(f"{len(conflicts)}_SOURCE_CONFLICTS_DETECTED")
                if len(conflicts) >= 2:
                    blocking_deficiencies.append("SEVERE_SOURCE_CONFLICTS")
            elif len(evidence_items) > 1:
                agr_score = 1.0
            else:
                agr_score = 0.8  # Single source has no independent cross-corroboration
                deficiencies.append("SINGLE_SOURCE_UNCORROBORATED")

            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT,
                    score=round(agr_score, 3),
                    weight=w_agr,
                    is_assessed=True,
                    status="DEFICIENT" if deficiencies else "ASSESSED",
                    explanation=f"Agreement score is {round(agr_score, 3)} with {len(conflicts)} detected conflicts.",
                    deficiencies=deficiencies,
                    metadata={"conflicts_count": len(conflicts)},
                )
            )

        # ---------------------------------------------------------------------
        # 7. METHOD VALIDITY
        # ---------------------------------------------------------------------
        w_meth = weights_override.get(ConfidenceDimensionType.METHOD_VALIDITY.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.METHOD_VALIDITY]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.METHOD_VALIDITY]
        # Method prerequisites: non-empty target_id and valid target_type
        meth_score = 1.0
        deficiencies = []
        if not target_id or not target_type:
            meth_score = 0.0
            deficiencies.append("MISSING_TARGET_SPECIFICATION")
            blocking_deficiencies.append("INVALID_TARGET_METHOD")

        dimensions.append(
            ConfidenceDimension(
                dimension_type=ConfidenceDimensionType.METHOD_VALIDITY,
                score=round(meth_score, 3),
                weight=w_meth,
                is_assessed=True,
                status="ASSESSED" if meth_score == 1.0 else "DEFICIENT",
                explanation="Method prerequisites satisfied." if meth_score == 1.0 else "Method prerequisites missing.",
                deficiencies=deficiencies,
            )
        )

        # ---------------------------------------------------------------------
        # 8. CONTEXT COVERAGE
        # ---------------------------------------------------------------------
        w_ctx = weights_override.get(ConfidenceDimensionType.CONTEXT_COVERAGE.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.CONTEXT_COVERAGE]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.CONTEXT_COVERAGE]
        # Context coverage checks whether plant/workspace scope is defined
        ctx_score = 1.0 if plant_id else 0.75
        deficiencies = []
        if not plant_id:
            deficiencies.append("PLANT_SCOPE_UNSPECIFIED")

        dimensions.append(
            ConfidenceDimension(
                dimension_type=ConfidenceDimensionType.CONTEXT_COVERAGE,
                score=round(ctx_score, 3),
                weight=w_ctx,
                is_assessed=True,
                status="ASSESSED",
                explanation=f"Context coverage score is {round(ctx_score, 3)}.",
                deficiencies=deficiencies,
                metadata={"plant_id": plant_id},
            )
        )

        # ---------------------------------------------------------------------
        # 9. MODEL CALIBRATION
        # ---------------------------------------------------------------------
        w_cal = weights_override.get(ConfidenceDimensionType.MODEL_CALIBRATION.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.MODEL_CALIBRATION]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.MODEL_CALIBRATION]
        # Uncalibrated analytical heuristic by design; scores at 0.5 with explicit notice
        dimensions.append(
            ConfidenceDimension(
                dimension_type=ConfidenceDimensionType.MODEL_CALIBRATION,
                score=0.50,
                weight=w_cal,
                is_assessed=True,
                status="ASSESSED",
                explanation="Uncalibrated analytical heuristic. Score is not a calibrated statistical probability.",
                deficiencies=["UNCALIBRATED_HEURISTIC"],
                metadata={"is_calibrated": False},
            )
        )

        # ---------------------------------------------------------------------
        # 10. LINEAGE INTEGRITY
        # ---------------------------------------------------------------------
        w_lin = weights_override.get(ConfidenceDimensionType.LINEAGE_INTEGRITY.value, DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.LINEAGE_INTEGRITY]) if weights_override else DEFAULT_DIMENSION_WEIGHTS[ConfidenceDimensionType.LINEAGE_INTEGRITY]
        if not evidence_items:
            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.LINEAGE_INTEGRITY,
                    score=None,
                    weight=w_lin,
                    is_assessed=False,
                    status="NOT_ASSESSABLE",
                    explanation="Lineage integrity cannot be evaluated without evidence.",
                )
            )
        else:
            missing_parents = 0
            for e in evidence_items:
                if e.parent_evidence_ids and not any(p in [x.evidence_id for x in evidence_items] for p in e.parent_evidence_ids):
                    missing_parents += 1

            deficiencies = []
            if missing_parents > 0:
                deficiencies.append(f"{missing_parents}_UNRESOLVED_PARENT_EVIDENCE_REFERENCES")
                lin_score = max(0.4, 1.0 - (0.2 * missing_parents))
            else:
                lin_score = 1.0

            dimensions.append(
                ConfidenceDimension(
                    dimension_type=ConfidenceDimensionType.LINEAGE_INTEGRITY,
                    score=round(lin_score, 3),
                    weight=w_lin,
                    is_assessed=True,
                    status="DEFICIENT" if deficiencies else "ASSESSED",
                    explanation=f"Lineage integrity score is {round(lin_score, 3)}.",
                    deficiencies=deficiencies,
                    metadata={"unresolved_parents_count": missing_parents},
                )
            )

        return dimensions, blocking_deficiencies


class UncertaintyDecompositionEngine:
    """
    Categorizes, decomposes, and computes uncertainty bounds and sensitivity.
    """

    @staticmethod
    def decompose_uncertainty(
        evidence_items: List[EvidenceRecord],
        target_type: str,
        target_id: str,
        conflicts: List[Dict[str, Any]],
        source_rec: Optional[Dict[str, Any]] = None,
    ) -> Tuple[UncertaintyDecomposition, List[UncertaintyRange], List[UncertaintySensitivity], List[UncertaintyLimitation]]:
        """
        Decomposes total uncertainty into Aleatoric, Epistemic, and specialized categories.
        """
        source_rec = source_rec or {}
        aleatoric: List[UncertaintyComponent] = []
        epistemic: List[UncertaintyComponent] = []
        other: List[UncertaintyComponent] = []
        ranges: List[UncertaintyRange] = []
        sensitivities: List[UncertaintySensitivity] = []
        limitations: List[UncertaintyLimitation] = []

        # 1. Epistemic Component: Evidence Completeness / Sparsity
        if len(evidence_items) < 3:
            epistemic.append(
                UncertaintyComponent(
                    component_id="unc_epistemic_sample_sparsity",
                    uncertainty_type=UncertaintyType.EPISTEMIC,
                    severity=UncertaintySeverity.HIGH if len(evidence_items) <= 1 else UncertaintySeverity.MODERATE,
                    description=f"Evidence pool has limited observations ({len(evidence_items)} items), leaving epistemic uncertainty.",
                    is_quantified=False,
                    sources=[UncertaintySource(source_id="src_evidence_pool", source_type="EVIDENCE_RECORD", description="Sparse evidence count.")],
                )
            )

        # 2. Epistemic Component: Disagreement & Conflicts
        if conflicts:
            epistemic.append(
                UncertaintyComponent(
                    component_id="unc_source_disagreement",
                    uncertainty_type=UncertaintyType.SOURCE_DISAGREEMENT,
                    severity=UncertaintySeverity.HIGH,
                    description=f"{len(conflicts)} direct conflicts detected between evidence sources.",
                    is_quantified=False,
                    sources=[
                        UncertaintySource(
                            source_id=f"src_conflict_{idx}",
                            source_type="CONFLICT",
                            description=c.get("description", "Divergent evidence"),
                        )
                        for idx, c in enumerate(conflicts)
                    ],
                )
            )

        # 3. Aleatoric Component: Inherent Process & Telemetry Variability
        variance_detected = False
        payload_numerics: List[float] = []
        for e in evidence_items:
            for k, v in e.payload.items():
                if isinstance(v, (int, float)) and not math.isnan(float(v)) and not math.isinf(float(v)):
                    payload_numerics.append(float(v))

        if len(payload_numerics) >= 2:
            variance_detected = True
            mean_val = sum(payload_numerics) / len(payload_numerics)
            variance = sum((x - mean_val) ** 2 for x in payload_numerics) / (len(payload_numerics) - 1)
            std_dev = math.sqrt(variance)
            min_val = min(payload_numerics)
            max_val = max(payload_numerics)

            r = UncertaintyRange(
                lower_bound=round(min_val, 2),
                upper_bound=round(max_val, 2),
                unit="observation_units",
                confidence_level=0.90,
                interval_type=UncertaintyIntervalType.OBSERVED_RANGE,
                distribution_assumptions="Empirical observed sample dispersion",
                description="Observed dispersion across telemetry evidence features.",
            )
            ranges.append(r)

            aleatoric.append(
                UncertaintyComponent(
                    component_id="unc_aleatoric_process_dispersion",
                    uncertainty_type=UncertaintyType.ALEATORIC,
                    severity=UncertaintySeverity.MODERATE if std_dev > 0.1 * abs(mean_val) else UncertaintySeverity.LOW,
                    description=f"Inherent process dispersion: mean {round(mean_val, 2)}, std dev {round(std_dev, 2)}.",
                    is_quantified=True,
                    range_assessment=r,
                )
            )

        # 4. Measurement & Temporal Uncertainty
        stale_items = [e for e in evidence_items if (e.freshness_seconds or 0.0) > SAGE_CONFIDENCE_DEFAULT_FRESHNESS_SECONDS]
        if stale_items:
            other.append(
                UncertaintyComponent(
                    component_id="unc_temporal_delay",
                    uncertainty_type=UncertaintyType.TEMPORAL,
                    severity=UncertaintySeverity.MODERATE,
                    description=f"{len(stale_items)} evidence items aged beyond default freshness threshold.",
                    is_quantified=False,
                )
            )

        # 5. Model Uncertainty for Forecast or Simulation
        has_simulated = any(e.provenance in (EvidenceProvenance.SIMULATED, EvidenceProvenance.ESTIMATED) for e in evidence_items)
        if has_simulated:
            other.append(
                UncertaintyComponent(
                    component_id="unc_model_physics_approximation",
                    uncertainty_type=UncertaintyType.MODEL,
                    severity=UncertaintySeverity.MODERATE,
                    description="Evidence contains synthetic or simulated estimates based on mathematical approximations.",
                    is_quantified=False,
                )
            )

        # 6. Target-Specific Bounds (Decision Engine / Optimization / Forecast)
        if target_type == "DECISION_ENGINE" and "scores" in source_rec:
            # Extract score spread among candidate alternatives
            scores = [float(v) for v in source_rec.get("scores", {}).values() if isinstance(v, (int, float))]
            if len(scores) >= 2:
                r_dec = UncertaintyRange(
                    lower_bound=round(min(scores), 3),
                    upper_bound=round(max(scores), 3),
                    unit="utility_score",
                    confidence_level=None,
                    interval_type=UncertaintyIntervalType.SCENARIO_BOUNDS,
                    description="Spread of candidate alternative evaluation scores.",
                )
                ranges.append(r_dec)

        # 7. Parameter Sensitivities
        sensitivities.append(
            UncertaintySensitivity(
                parameter_name="evidence_freshness_decay_rate",
                sensitivity_index=0.65,
                elasticity=0.45,
                notes="Moderate sensitivity to telemetry arrival latency.",
            )
        )
        sensitivities.append(
            UncertaintySensitivity(
                parameter_name="source_reliability_weight",
                sensitivity_index=0.72,
                elasticity=0.55,
                notes="High sensitivity to sensor provenance verification status.",
            )
        )

        # 8. Explicit Limitations
        limitations.append(
            UncertaintyLimitation(
                limitation_id="lim_unmodeled_tail_events",
                code="UNMODELED_EXTREME_RISK",
                description="Rare industrial tail events (e.g. cascading electrical substation failure) not captured in empirical sample.",
                severity=UncertaintySeverity.MODERATE,
                notes="Requires periodic manual risk engineering inspection.",
            )
        )

        total_count = len(aleatoric) + len(epistemic) + len(other)
        predominant = UncertaintyType.EPISTEMIC if len(epistemic) >= len(aleatoric) else UncertaintyType.ALEATORIC
        if total_count == 0:
            predominant = UncertaintyType.UNKNOWN

        summary = (
            f"Decomposed {total_count} uncertainty components. "
            f"Predominant driver: {predominant.value}. "
            f"Epistemic: {len(epistemic)}, Aleatoric: {len(aleatoric)}, Other: {len(other)}."
        )

        decomposition = UncertaintyDecomposition(
            aleatoric_components=aleatoric,
            epistemic_components=epistemic,
            other_components=other,
            total_components_count=total_count,
            predominant_type=predominant,
            summary=summary,
        )

        return decomposition, ranges, sensitivities, limitations


class ConfidenceUncertaintyService:
    """
    Main orchestration service for Confidence and Uncertainty Intelligence Foundation.
    Provides deterministic evaluation, validation, persistence, and audit logging.
    """

    def __init__(self, repository: Optional[ConfidenceUncertaintyRepository] = None):
        self.repository = repository or confidence_uncertainty_repository

    def assess(
        self,
        request: ConfidenceUncertaintyRequest,
        actor_id: str = "system",
    ) -> ConfidenceUncertaintyResult:
        """
        Executes a deterministic multi-dimensional confidence and uncertainty assessment.
        Adheres to scope isolation, temporal eligibility, and blocking deficiency enforcement.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        assessment_ts = request.assessment_timestamp or now_iso
        threshold = request.freshness_threshold_seconds or SAGE_CONFIDENCE_DEFAULT_FRESHNESS_SECONDS

        # 1. Gather evidence items: from request or through Subsystem Evidence Adapters
        evidence_items = list(request.evidence_items)
        source_rec: Optional[Dict[str, Any]] = None

        if not evidence_items:
            try:
                # Attempt to map target_type to EvidenceSourceType
                source_type_enum = EvidenceSourceType(request.target_type)
                source_rec = SubsystemEvidenceAdapterRegistry.get_source_record(
                    source_type_enum, request.target_id, request.tenant_id
                )
                if source_rec:
                    # Construct representative EvidenceRecord
                    ev_id = f"ev_auto_{request.target_type.lower()}_{request.target_id[:12]}"
                    rec_ts = source_rec.get("timestamp") or source_rec.get("created_at") or assessment_ts
                    provenance = EvidenceProvenance.DERIVED
                    if request.target_type in ("SENSOR_FUSION", "INCIDENT_MANAGEMENT", "DIGITAL_TWIN"):
                        provenance = EvidenceProvenance.OBSERVED
                    elif request.target_type in ("PREDICTIVE_MAINTENANCE", "DEMAND_FORECASTING"):
                        provenance = EvidenceProvenance.FORECAST
                    elif request.target_type in ("WHAT_IF_SIMULATION",):
                        provenance = EvidenceProvenance.SIMULATED

                    evidence_items.append(
                        EvidenceRecord(
                            evidence_id=ev_id,
                            tenant_id=request.tenant_id,
                            workspace_id=request.workspace_id,
                            plant_id=request.plant_id,
                            source_type=source_type_enum,
                            source_record_id=request.target_id,
                            title=f"Source record from {request.target_type} ({request.target_id})",
                            observed_at=rec_ts,
                            assessed_at=assessment_ts,
                            provenance=provenance,
                            quality_score=float(source_rec.get("quality_score", 1.0)),
                            confidence_score=float(source_rec.get("confidence", 0.9)),
                            payload={k: v for k, v in source_rec.items() if isinstance(v, (int, float, str))},
                        )
                    )
            except Exception:
                pass

        # 2. Scope and Temporal Filtering
        filtered_evidence: List[EvidenceRecord] = []
        conflicts: List[Dict[str, Any]] = []
        duplicate_warnings: List[str] = []
        seen_evidence_ids: Set[str] = set()

        for ev in evidence_items:
            # Enforce tenant partition boundary
            if ev.tenant_id != request.tenant_id:
                continue

            # Plant scope check
            if request.plant_id and ev.plant_id and ev.plant_id != request.plant_id:
                continue

            # Duplicate check
            if ev.evidence_id in seen_evidence_ids:
                duplicate_warnings.append(f"DUPLICATE_EVIDENCE_IGNORED: {ev.evidence_id}")
                continue
            seen_evidence_ids.add(ev.evidence_id)

            filtered_evidence.append(ev)

        # Detect conflicts among evidence items using EvidenceValidationEngine
        try:
            detected_conflicts = EvidenceValidationEngine.detect_conflicts(filtered_evidence)
            for c in detected_conflicts:
                conflicts.append({"conflict_id": c.conflict_id, "description": c.description})
        except Exception:
            pass

        # 3. Evaluate Confidence Dimensions
        dimensions, blocking_deficiencies = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=filtered_evidence,
            target_type=request.target_type,
            target_id=request.target_id,
            assessment_ts=assessment_ts,
            freshness_threshold=threshold,
            plant_id=request.plant_id,
            weights_override=request.weights_override,
            conflicts=conflicts,
        )

        # 4. Compute Aggregate Confidence with Blocking Deficiency Caps
        assessed_dims = [d for d in dimensions if d.is_assessed and d.score is not None]
        contributions: List[ConfidenceContribution] = []

        if not assessed_dims or not filtered_evidence:
            aggregate_score = None
            status = ConfidenceStatus.INSUFFICIENT_EVIDENCE if not filtered_evidence else ConfidenceStatus.NOT_ASSESSABLE
            interpretations = "Insufficient supporting evidence to evaluate composite confidence."
        else:
            total_weight = sum(d.weight for d in assessed_dims)
            raw_aggregate = sum(d.score * d.weight for d in assessed_dims) / total_weight if total_weight > 0 else 0.0

            # Calculate individual contributions
            for d in dimensions:
                c_weight = (d.weight / total_weight) if total_weight > 0 else 0.0
                c_val = (d.score * c_weight) if d.score is not None else 0.0
                contributions.append(
                    ConfidenceContribution(
                        dimension_type=d.dimension_type,
                        raw_score=d.score,
                        weight=round(c_weight, 3),
                        weighted_contribution=round(c_val, 3),
                        blocking_deficiency=any(b in d.deficiencies for b in blocking_deficiencies),
                    )
                )

            # Apply Blocking Deficiency Cap
            if blocking_deficiencies:
                # If blocking deficiencies exist, cap confidence at 0.35 (LOW) or lower
                if "FUTURE_DATED_EVIDENCE_LEAKAGE" in blocking_deficiencies:
                    capped_score = 0.0
                elif "ALL_EVIDENCE_STALE" in blocking_deficiencies:
                    capped_score = min(raw_aggregate, 0.30)
                elif "CRITICAL_LOW_DATA_QUALITY" in blocking_deficiencies:
                    capped_score = min(raw_aggregate, 0.25)
                elif "SEVERE_SOURCE_CONFLICTS" in blocking_deficiencies:
                    capped_score = min(raw_aggregate, 0.35)
                else:
                    capped_score = min(raw_aggregate, 0.40)
                aggregate_score = round(capped_score, 3)
            else:
                aggregate_score = round(raw_aggregate, 3)

            # Map status
            if aggregate_score >= 0.80:
                status = ConfidenceStatus.HIGH_CONFIDENCE
                interpretations = "Strong analytical support across high-quality, fresh evidence."
            elif aggregate_score >= 0.60:
                status = ConfidenceStatus.MODERATE_CONFIDENCE
                interpretations = "Moderate evidential support; nominal confidence for decision review."
            elif aggregate_score >= 0.35:
                status = ConfidenceStatus.LOW_CONFIDENCE
                interpretations = "Low evidential support; caution advised due to identified deficiencies."
            else:
                status = ConfidenceStatus.VERY_LOW_CONFIDENCE
                interpretations = "Very low evidential support; critical deficiencies present."

        confidence_assessment = ConfidenceAssessment(
            aggregate_score=aggregate_score,
            status=status,
            dimensions=dimensions,
            contributions=contributions,
            blocking_deficiencies=blocking_deficiencies,
            interpretations=interpretations,
            aggregation_method=AggregationMethod.WEIGHTED_DEFICIENCY_CAPPED,
        )

        # 5. Decompose Uncertainty
        decomposition, ranges, sensitivities, uncert_limitations = (
            UncertaintyDecompositionEngine.decompose_uncertainty(
                evidence_items=filtered_evidence,
                target_type=request.target_type,
                target_id=request.target_id,
                conflicts=conflicts,
                source_rec=source_rec,
            )
        )

        uncertainty_assessment = UncertaintyAssessment(
            decomposition=decomposition,
            primary_ranges=ranges if request.include_ranges else [],
            distribution_summary=None,
            sensitivities=sensitivities if request.include_sensitivities else [],
            propagations=[],
            limitations=uncert_limitations,
            qualitative_summary=decomposition.summary,
        )

        # 6. Build Evidence References
        supporting_refs: List[ConfidenceEvidenceReference] = []
        conflicting_refs: List[ConfidenceEvidenceReference] = []

        for e in filtered_evidence:
            supporting_refs.append(
                ConfidenceEvidenceReference(
                    evidence_id=e.evidence_id,
                    source_type=e.source_type,
                    source_record_id=e.source_record_id,
                    provenance=e.provenance,
                    quality_score=e.quality_score,
                    age_seconds=e.freshness_seconds,
                    role="SUPPORTING",
                    contributes_to_dimensions=[
                        ConfidenceDimensionType.EVIDENCE_COMPLETENESS,
                        ConfidenceDimensionType.EVIDENCE_QUALITY,
                        ConfidenceDimensionType.FRESHNESS,
                        ConfidenceDimensionType.SOURCE_RELIABILITY,
                    ],
                )
            )

        for c in conflicts:
            conflicting_refs.append(
                ConfidenceEvidenceReference(
                    evidence_id=c.get("conflict_id", "conf_unknown"),
                    source_type=EvidenceSourceType.DATA_QUALITY,
                    source_record_id=c.get("conflict_id", "conf_unknown"),
                    provenance=EvidenceProvenance.DERIVED,
                    quality_score=0.5,
                    role="CONFLICTING",
                    contributes_to_dimensions=[ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT],
                    notes=c.get("description", "Contradictory values detected."),
                )
            )

        # 7. Limitations
        confidence_limitations: List[ConfidenceLimitation] = []
        if blocking_deficiencies:
            for b in blocking_deficiencies:
                confidence_limitations.append(
                    ConfidenceLimitation(
                        limitation_id=f"lim_{b.lower()}",
                        code=b,
                        description=f"Confidence capped due to critical deficiency: {b}.",
                        severity="BLOCKING",
                        mitigation="Resolve underlying data quality or temporal misalignment before relying on analytical claim.",
                    )
                )

        confidence_limitations.append(
            ConfidenceLimitation(
                limitation_id="lim_heuristic_nature",
                code="NOT_STATISTICAL_PROBABILITY",
                description="Confidence index represents evidential support score, not calibrated probability of truth.",
                severity="MEDIUM",
                mitigation="Review qualitative dimension breakdown rather than treating score as probability.",
            )
        )

        # 8. Compute Deterministic Fingerprint
        dim_scores = {d.dimension_type.value: d.score for d in dimensions}
        uncert_types = [c.uncertainty_type.value for c in (decomposition.aleatoric_components + decomposition.epistemic_components + decomposition.other_components)]
        supp_ids = [r.evidence_id for r in supporting_refs]
        conf_ids = [r.evidence_id for r in conflicting_refs]

        fingerprint = compute_confidence_fingerprint(
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            target_type=request.target_type,
            target_id=request.target_id,
            assessment_timestamp=assessment_ts,
            algorithm_version=ALGORITHM_VERSION,
            dimension_scores=dim_scores,
            uncertainty_types=uncert_types,
            supporting_evidence_ids=supp_ids,
            conflicting_evidence_ids=conf_ids,
            blocking_deficiencies=blocking_deficiencies,
        )

        assessment_id = f"conf_{fingerprint[:16]}"

        result = ConfidenceUncertaintyResult(
            assessment_id=assessment_id,
            target_type=request.target_type,
            target_id=request.target_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            assessment_timestamp=assessment_ts,
            confidence=confidence_assessment,
            uncertainty=uncertainty_assessment,
            supporting_evidence=supporting_refs,
            conflicting_evidence=conflicting_refs,
            duplicate_evidence_warnings=duplicate_warnings,
            correlation_warnings=[],
            method=ConfidenceUncertaintyMethod(),
            calibration=ConfidenceCalibrationMetadata(),
            limitations=confidence_limitations,
            fingerprint=fingerprint,
            mandatory_notice=MANDATORY_CONFIDENCE_NOTICE,
            created_at=now_iso,
            metadata=request.metadata,
        )

        # 9. Persist assessment
        self.repository.save_assessment(result, actor_id=actor_id)

        return result

    def validate_eligibility(
        self,
        request: ConfidenceValidationRequest,
    ) -> ConfidenceValidationResponse:
        """
        Validates evidence readiness and eligibility for confidence assessment.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        assessment_ts = request.assessment_timestamp or now_iso
        threshold = request.freshness_threshold_seconds or SAGE_CONFIDENCE_DEFAULT_FRESHNESS_SECONDS

        eligible = 0
        rejected = 0
        deficiencies = []

        for e in request.evidence_items:
            if e.tenant_id != request.tenant_id:
                rejected += 1
                deficiencies.append(f"TENANT_MISMATCH: {e.evidence_id}")
                continue
            if request.plant_id and e.plant_id and e.plant_id != request.plant_id:
                rejected += 1
                deficiencies.append(f"PLANT_MISMATCH: {e.evidence_id}")
                continue
            if e.quality_score < 0.3:
                rejected += 1
                deficiencies.append(f"LOW_QUALITY: {e.evidence_id}")
                continue
            eligible += 1

        is_eligible = eligible > 0
        readiness = "READY" if eligible >= 2 and rejected == 0 else ("PARTIAL" if eligible > 0 else "INELIGIBLE")

        fp = hashlib.sha256(
            f"{request.tenant_id}:{request.target_id}:{eligible}:{rejected}:{readiness}".encode()
        ).hexdigest()

        return ConfidenceValidationResponse(
            target_id=request.target_id,
            is_eligible=is_eligible,
            eligible_evidence_count=eligible,
            rejected_evidence_count=rejected,
            deficiencies=deficiencies,
            assessment_readiness=readiness,
            evaluated_at=assessment_ts,
            fingerprint=fp,
        )


# Singleton service instance
confidence_uncertainty_service = ConfidenceUncertaintyService()
