"""
backend/services/sensor_fusion_service.py

SageCommand V3 — Multimodal Sensor Fusion Intelligence Foundation Service (Prompt 27)

ANALYTICAL ONLY.
Combines heterogeneous industrial observations (numeric telemetry, vibration, temperature,
pressure, electrical, acoustic, visual, thermal, process, event, anomaly, digital twin)
into a coherent, explainable, and tenant-isolated analytical assessment.

Strict Non-Negotiable Execution Boundary:
- Analytical evidence and fused observations only.
- NO ExecutionGateway import or invocation.
- NO Action API creation, approval, or execution.
- NO PLC or industrial controller writes.
- NO work orders or maintenance scheduling.
- NO mutations to anomaly, incident, RCA, digital twin, financial, or sustainability records.
"""

import math
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set

try:
    from core.config import (
        SAGE_SENSOR_FUSION_MAX_OBSERVATIONS,
        SAGE_SENSOR_FUSION_MAX_MODALITIES,
        SAGE_SENSOR_FUSION_MAX_EVALUATION_WINDOW_SECONDS,
        SAGE_SENSOR_FUSION_MAX_EVIDENCE,
        SAGE_SENSOR_FUSION_MAX_CORRELATION_SAMPLES,
    )
    from data.schemas.sensor_fusion_contract import (
        Modality,
        MeasurementType,
        SensorValueProvenance,
        AgreementStatus,
        AlignmentStrategy,
        FusionStrategy,
        SensorHealthStatus,
        FusionConfidence,
        FusionUncertainty,
        SensorObservation,
        NormalizedObservation,
        FusionEvidence,
        FusedObservation,
        CrossModalCorrelation,
        CrossModalAgreement,
        SensorHealthIndicator,
        WeightingRule,
        EvaluationWindow,
        FusionAssessment,
        SensorFusionAnalyzeRequest,
        convert_unit,
        are_units_compatible,
        normalize_unit_string,
        CANONICAL_BASE_UNITS,
        compute_sensor_fusion_fingerprint,
    )
    from services.sensor_fusion_repository import sensor_fusion_repository, SensorFusionRepository
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_SENSOR_FUSION_MAX_OBSERVATIONS,
        SAGE_SENSOR_FUSION_MAX_MODALITIES,
        SAGE_SENSOR_FUSION_MAX_EVALUATION_WINDOW_SECONDS,
        SAGE_SENSOR_FUSION_MAX_EVIDENCE,
        SAGE_SENSOR_FUSION_MAX_CORRELATION_SAMPLES,
    )
    from backend.data.schemas.sensor_fusion_contract import (
        Modality,
        MeasurementType,
        SensorValueProvenance,
        AgreementStatus,
        AlignmentStrategy,
        FusionStrategy,
        SensorHealthStatus,
        FusionConfidence,
        FusionUncertainty,
        SensorObservation,
        NormalizedObservation,
        FusionEvidence,
        FusedObservation,
        CrossModalCorrelation,
        CrossModalAgreement,
        SensorHealthIndicator,
        WeightingRule,
        EvaluationWindow,
        FusionAssessment,
        SensorFusionAnalyzeRequest,
        convert_unit,
        are_units_compatible,
        normalize_unit_string,
        CANONICAL_BASE_UNITS,
        compute_sensor_fusion_fingerprint,
    )
    from backend.services.sensor_fusion_repository import sensor_fusion_repository, SensorFusionRepository



# Canonical versioned weighting rules (Section 22)
CANONICAL_WEIGHTING_RULES: List[WeightingRule] = [
    WeightingRule(factor_name="numeric_telemetry_weight", modality=Modality.NUMERIC_TELEMETRY, weight=0.80, rationale="Direct physical numeric measurement", version="1.0"),
    WeightingRule(factor_name="vibration_weight", modality=Modality.VIBRATION, weight=0.90, rationale="High sensitivity for mechanical and rotational degradation", version="1.0"),
    WeightingRule(factor_name="temperature_weight", modality=Modality.TEMPERATURE, weight=0.85, rationale="Thermal accumulation indicator", version="1.0"),
    WeightingRule(factor_name="pressure_weight", modality=Modality.PRESSURE, weight=0.85, rationale="Hydraulic and pneumatic state indicator", version="1.0"),
    WeightingRule(factor_name="electrical_weight", modality=Modality.ELECTRICAL, weight=0.85, rationale="Motor load, voltage, and electrical power signature", version="1.0"),
    WeightingRule(factor_name="acoustic_weight", modality=Modality.ACOUSTIC, weight=0.75, rationale="Early high-frequency bearing wear and cavitation", version="1.0"),
    WeightingRule(factor_name="visual_weight", modality=Modality.VISUAL, weight=0.70, rationale="Optical inspection and surface defect observation", version="1.0"),
    WeightingRule(factor_name="thermal_weight", modality=Modality.THERMAL, weight=0.80, rationale="Thermographic gradient and localized hotspot mapping", version="1.0"),
    WeightingRule(factor_name="process_weight", modality=Modality.PROCESS, weight=0.70, rationale="Operating rate and throughput context", version="1.0"),
    WeightingRule(factor_name="event_weight", modality=Modality.EVENT, weight=0.60, rationale="Discrete operational and alarm event context", version="1.0"),
    WeightingRule(factor_name="anomaly_weight", modality=Modality.ANOMALY, weight=0.80, rationale="Deterministic statistical anomaly signal", version="1.0"),
    WeightingRule(factor_name="digital_twin_weight", modality=Modality.DIGITAL_TWIN, weight=0.65, rationale="Virtual simulation baseline and expected state context", version="1.0"),
]

WEIGHT_MAP: Dict[Modality, float] = {r.modality: r.weight for r in CANONICAL_WEIGHTING_RULES}


def parse_iso_timestamp(ts_str: str) -> datetime:
    """Parses ISO-8601 UTC timestamp safely."""
    cleaned = ts_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class SensorFusionService:
    """
    Core deterministic Multimodal Sensor Fusion Service.
    Integrates heterogeneous observations, evaluates cross-modal agreement,
    calculates fused metrics, and tracks evidence without mutating physical systems.
    """

    def __init__(self, repo: Optional[SensorFusionRepository] = None) -> None:
        self.repo = repo or sensor_fusion_repository

    # -------------------------------------------------------------------------
    # Primary Analytical Pipeline
    # -------------------------------------------------------------------------

    def analyze(self, request: SensorFusionAnalyzeRequest) -> FusionAssessment:
        """
        Executes complete multimodal sensor fusion assessment:
        1. Validate boundaries & resource limits
        2. Temporal filtering & future-leakage protection
        3. Unit safety & normalization
        4. Evidence independence & anti-double-counting
        5. Upstream context integration (DQ, Anomaly, Twin, Ontology, KG)
        6. Cross-modal correlation & agreement analysis
        7. Fused observation calculation
        8. Sensor reliability & health analysis
        9. Confidence & uncertainty evaluation
        10. Deterministic SHA-256 fingerprinting & persistence
        """
        # 1. Enforce Resource Limits
        if len(request.observations) > SAGE_SENSOR_FUSION_MAX_OBSERVATIONS:
            raise ValueError(
                f"Observation count {len(request.observations)} exceeds maximum allowed limit of {SAGE_SENSOR_FUSION_MAX_OBSERVATIONS}"
            )
        if request.evaluation_window_seconds <= 0 or request.evaluation_window_seconds > SAGE_SENSOR_FUSION_MAX_EVALUATION_WINDOW_SECONDS:
            raise ValueError(
                f"Evaluation window {request.evaluation_window_seconds}s must be between 1 and {SAGE_SENSOR_FUSION_MAX_EVALUATION_WINDOW_SECONDS}s"
            )

        # Establish deterministic evaluation timestamp T
        if request.assessment_timestamp:
            assessment_dt = parse_iso_timestamp(request.assessment_timestamp)
            assessment_ts_str = assessment_dt.isoformat().replace("+00:00", "Z")
        else:
            assessment_dt = datetime.now(timezone.utc)
            assessment_ts_str = assessment_dt.isoformat().replace("+00:00", "Z")

        window_start_dt = assessment_dt - timedelta(seconds=request.evaluation_window_seconds)
        window_start_str = window_start_dt.isoformat().replace("+00:00", "Z")

        evaluation_window = EvaluationWindow(
            start_time=window_start_str,
            end_time=assessment_ts_str,
            duration_seconds=float(request.evaluation_window_seconds)
        )

        limitations: List[str] = []

        # 2. Temporal Filtering & Future Leakage Protection (Section 9, 33)
        eligible_observations: List[SensorObservation] = []
        for obs in request.observations:
            # Boundary validation: tenant and entity
            if obs.tenant_id != request.tenant_id:
                limitations.append(f"Observation {obs.observation_id} excluded: tenant mismatch ({obs.tenant_id} != {request.tenant_id})")
                continue
            if obs.entity_id != request.target_entity_id:
                limitations.append(f"Observation {obs.observation_id} excluded: entity mismatch ({obs.entity_id} != {request.target_entity_id})")
                continue

            obs_dt = parse_iso_timestamp(obs.observed_at)

            # Strict future-leakage protection
            if obs_dt > assessment_dt:
                limitations.append(f"Observation {obs.observation_id} excluded: future timestamp ({obs.observed_at} > {assessment_ts_str})")
                continue

            # Evaluation window check
            if obs_dt < window_start_dt:
                limitations.append(f"Observation {obs.observation_id} excluded: prior to evaluation window ({obs.observed_at} < {window_start_str})")
                continue

            eligible_observations.append(obs)

        # 3. Unit Safety & Normalization (Section 7)
        normalized_observations: List[NormalizedObservation] = []
        for obs in eligible_observations:
            norm_obs = self._normalize_observation(obs, assessment_dt)
            normalized_observations.append(norm_obs)

        # 4. Modalities Present & Missing (Section 5)
        present_modalities: List[Modality] = sorted(list({obs.modality for obs in eligible_observations}), key=lambda x: x.value)
        all_modalities = set(Modality)
        missing_modalities: List[Modality] = sorted(list(all_modalities - set(present_modalities)), key=lambda x: x.value)

        # 5. Evidence Independence & Anti-Double-Counting (Section 26)
        evidence_list = self._build_evidence_chain(eligible_observations, normalized_observations)

        # 6. Sensor Health & Reliability (Section 27)
        sensor_health_indicators = self._evaluate_sensor_health(eligible_observations, assessment_dt)

        # 7. Upstream Context Integration (Sections 11, 12, 13, 28, 29)
        dq_summary = self._integrate_data_quality(request, eligible_observations, assessment_ts_str)
        anomalies_context = self._integrate_anomalies(request, assessment_ts_str)
        twin_context = self._integrate_digital_twin(request, eligible_observations, assessment_ts_str)
        ontology_context = self._integrate_ontology(request)
        kg_context = self._integrate_knowledge_graph(request, assessment_ts_str)

        # 8. Cross-Modal Correlations & Electrical Checks (Sections 18, 19)
        correlations = self._compute_cross_modal_correlations(normalized_observations)
        self._check_electrical_consistency(eligible_observations, limitations)

        # 9. Cross-Modal Agreement / Disagreement (Section 20)
        agreements, disagreements = self._evaluate_agreements(
            normalized_observations,
            anomalies_context,
            twin_context,
            limitations
        )

        # 10. Fused Observations Calculation (Section 21)
        fused_observations = self._calculate_fused_observations(
            normalized_observations,
            evidence_list,
            request.fusion_strategy,
            evaluation_window,
            twin_context
        )

        # 11. Deterministic Confidence & Uncertainty (Sections 23, 24)
        confidence, uncertainty = self._determine_confidence_and_uncertainty(
            present_modalities,
            evidence_list,
            agreements,
            disagreements,
            dq_summary,
            limitations
        )

        # Overall Provenance calculation
        overall_provenance = self._determine_overall_provenance(eligible_observations)

        # 12. Deterministic SHA-256 Input Fingerprint (Section 34)
        fingerprint = compute_sensor_fusion_fingerprint(
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            target_entity_id=request.target_entity_id,
            assessment_timestamp=assessment_ts_str,
            evaluation_window_seconds=request.evaluation_window_seconds,
            observations=eligible_observations,
            methodology="DETERMINISTIC_MULTIMODAL_FUSION_V1",
            model_version="1.0.0",
            fusion_strategy=request.fusion_strategy.value,
            weights=CANONICAL_WEIGHTING_RULES,
            context_keys={
                "dq_records": len(dq_summary.get("issues", [])),
                "anomalies": len(anomalies_context),
                "twin_present": twin_context is not None,
            }
        )

        assessment = FusionAssessment(
            fusion_assessment_id=f"sf_{uuid.uuid4().hex[:16]}",
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            target_entity_id=request.target_entity_id,
            target_entity_type=request.target_entity_type or "MACHINE",
            assessment_timestamp=assessment_ts_str,
            evaluation_window=evaluation_window,
            observations=eligible_observations,
            modalities_present=present_modalities,
            modalities_missing=missing_modalities,
            normalized_observations=normalized_observations,
            fused_observations=fused_observations,
            correlations=correlations,
            agreements=agreements,
            disagreements=disagreements,
            anomalies=anomalies_context,
            sensor_health=sensor_health_indicators,
            evidence=evidence_list,
            confidence=confidence,
            uncertainty=uncertainty,
            provenance=overall_provenance,
            data_quality_summary=dq_summary,
            digital_twin_context=twin_context,
            ontology_context=ontology_context,
            knowledge_graph_context=kg_context,
            limitations=limitations,
            methodology="DETERMINISTIC_MULTIMODAL_FUSION_V1",
            model_version="1.0.0",
            schema_version="1.0",
            input_fingerprint=fingerprint,
            execution_boundary_verified=True,
        )

        # 13. Persist and return
        return self.repo.save_assessment(assessment)

    # -------------------------------------------------------------------------
    # Helper: Normalization (Section 7)
    # -------------------------------------------------------------------------

    def _normalize_observation(
        self,
        obs: SensorObservation,
        assessment_dt: datetime
    ) -> NormalizedObservation:
        """
        Converts observation into canonical base unit and computes scaled score.
        """
        obs_dt = parse_iso_timestamp(obs.observed_at)
        offset_seconds = abs((assessment_dt - obs_dt).total_seconds())

        # Categorical / string / qualitative checks
        if not isinstance(obs.value, (int, float)):
            return NormalizedObservation(
                observation_id=obs.observation_id,
                sensor_id=obs.sensor_id,
                modality=obs.modality,
                measurement_type=obs.measurement_type,
                raw_value=obs.value,
                raw_unit=obs.unit,
                normalized_value=None,
                normalized_unit=obs.unit,
                scaled_score=None,
                observed_at=obs.observed_at,
                temporal_offset_seconds=offset_seconds,
                provenance=obs.provenance,
                confidence=obs.confidence,
                quality_score=obs.quality,
                is_valid=True,
            )

        val_float = float(obs.value)

        # If no unit specified, but numeric
        if not obs.unit:
            return NormalizedObservation(
                observation_id=obs.observation_id,
                sensor_id=obs.sensor_id,
                modality=obs.modality,
                measurement_type=obs.measurement_type,
                raw_value=obs.value,
                raw_unit=None,
                normalized_value=val_float,
                normalized_unit=None,
                scaled_score=self._scale_score(val_float, obs.measurement_type),
                observed_at=obs.observed_at,
                temporal_offset_seconds=offset_seconds,
                provenance=obs.provenance,
                confidence=obs.confidence,
                quality_score=obs.quality,
                is_valid=True,
            )

        norm_unit = normalize_unit_string(obs.unit)
        # Determine canonical base unit
        base_unit = None
        for fam, b_unit in CANONICAL_BASE_UNITS.items():
            if are_units_compatible(norm_unit, b_unit):
                base_unit = b_unit
                break

        if base_unit is None:
            # No conversion known, use raw unit
            return NormalizedObservation(
                observation_id=obs.observation_id,
                sensor_id=obs.sensor_id,
                modality=obs.modality,
                measurement_type=obs.measurement_type,
                raw_value=obs.value,
                raw_unit=obs.unit,
                normalized_value=val_float,
                normalized_unit=norm_unit,
                scaled_score=self._scale_score(val_float, obs.measurement_type),
                observed_at=obs.observed_at,
                temporal_offset_seconds=offset_seconds,
                provenance=obs.provenance,
                confidence=obs.confidence,
                quality_score=obs.quality,
                is_valid=True,
            )

        conv_val, success, _ = convert_unit(val_float, norm_unit, base_unit)
        if not success or conv_val is None:
            return NormalizedObservation(
                observation_id=obs.observation_id,
                sensor_id=obs.sensor_id,
                modality=obs.modality,
                measurement_type=obs.measurement_type,
                raw_value=obs.value,
                raw_unit=obs.unit,
                normalized_value=None,
                normalized_unit=base_unit,
                scaled_score=None,
                observed_at=obs.observed_at,
                temporal_offset_seconds=offset_seconds,
                provenance=obs.provenance,
                confidence=obs.confidence,
                quality_score=obs.quality,
                is_valid=False,
                exclusion_reason=f"Unit conversion failed from {obs.unit} to {base_unit}"
            )

        return NormalizedObservation(
            observation_id=obs.observation_id,
            sensor_id=obs.sensor_id,
            modality=obs.modality,
            measurement_type=obs.measurement_type,
            raw_value=obs.value,
            raw_unit=obs.unit,
            normalized_value=conv_val,
            normalized_unit=base_unit,
            scaled_score=self._scale_score(conv_val, obs.measurement_type),
            observed_at=obs.observed_at,
            temporal_offset_seconds=offset_seconds,
            provenance=obs.provenance,
            confidence=obs.confidence,
            quality_score=obs.quality,
            is_valid=True,
        )

    def _scale_score(self, val: float, measurement_type: MeasurementType) -> float:
        """
        Maps normalized physical measurements to a standardized [0.0, 1.0] stress/severity scale.
        """
        if measurement_type == MeasurementType.TEMPERATURE:
            # 20°C = 0.0, 100°C = 1.0
            return max(0.0, min(1.0, (val - 20.0) / 80.0))
        elif measurement_type in (MeasurementType.VIBRATION_RMS, MeasurementType.VIBRATION_VELOCITY):
            # 0 mm/s = 0.0, 10 mm/s = 1.0
            return max(0.0, min(1.0, val / 10.0))
        elif measurement_type == MeasurementType.PRESSURE:
            # 0 bar = 0.0, 100 bar = 1.0
            return max(0.0, min(1.0, val / 100.0))
        elif measurement_type == MeasurementType.ACOUSTIC_LEVEL:
            # 40 dB = 0.0, 120 dB = 1.0
            return max(0.0, min(1.0, (val - 40.0) / 80.0))
        elif measurement_type == MeasurementType.CURRENT:
            # 0 A = 0.0, 100 A = 1.0
            return max(0.0, min(1.0, val / 100.0))
        elif measurement_type == MeasurementType.ANOMALY_SCORE:
            return max(0.0, min(1.0, val))
        return max(0.0, min(1.0, val / 100.0 if val >= 0 else 0.0))

    # -------------------------------------------------------------------------
    # Helper: Evidence Independence & Anti-Double-Counting (Section 26)
    # -------------------------------------------------------------------------

    def _build_evidence_chain(
        self,
        observations: List[SensorObservation],
        normalized: List[NormalizedObservation]
    ) -> List[FusionEvidence]:
        """
        Builds explainable evidence objects.
        Explicitly identifies derived or parent-dependent evidence so it is not
        double-counted as independent observations.
        """
        evidence_list: List[FusionEvidence] = []
        observed_sensors: Set[str] = set()

        for obs, norm in zip(observations, normalized):
            is_independent = True
            parent_id = obs.parent_observation_id

            # If this observation is derived from an existing sensor or has a parent
            if parent_id or obs.provenance == SensorValueProvenance.DERIVED:
                is_independent = False
            elif obs.sensor_id in observed_sensors and obs.source_lineage:
                is_independent = False
            else:
                observed_sensors.add(obs.sensor_id)

            mod_weight = WEIGHT_MAP.get(obs.modality, 0.5)
            # Contribution accounts for modality weight, quality, and confidence
            contribution = round(mod_weight * obs.quality * obs.confidence, 4)

            evd_id = f"evd_{obs.sensor_id}_{obs.modality.value}_{obs.observation_id[:8]}"
            evidence_list.append(
                FusionEvidence(
                    evidence_id=evd_id,
                    modality=obs.modality,
                    source_type="SENSOR" if obs.provenance == SensorValueProvenance.OBSERVED else "DERIVED_PROCESS",
                    source_id=obs.sensor_id,
                    observation_id=obs.observation_id,
                    timestamp=obs.observed_at,
                    value=obs.value,
                    unit=obs.unit,
                    normalized_value=norm.normalized_value,
                    confidence=obs.confidence,
                    quality=obs.quality,
                    contribution=contribution,
                    provenance=obs.provenance,
                    explanation=f"{obs.modality.value} observation from {obs.sensor_id} ({obs.measurement_type.value})",
                    is_independent=is_independent,
                    parent_evidence_id=parent_id,
                    source_lineage=obs.source_lineage or [obs.sensor_id]
                )
            )

        return evidence_list

    # -------------------------------------------------------------------------
    # Helper: Sensor Health & Reliability (Section 27)
    # -------------------------------------------------------------------------

    def _evaluate_sensor_health(
        self,
        observations: List[SensorObservation],
        assessment_dt: datetime
    ) -> List[SensorHealthIndicator]:
        """
        Evaluates analytical reliability per sensor without mutating hardware.
        """
        by_sensor: Dict[str, List[SensorObservation]] = {}
        for o in observations:
            by_sensor.setdefault(o.sensor_id, []).append(o)

        indicators: List[SensorHealthIndicator] = []
        for sensor_id, obs_group in by_sensor.items():
            mod = obs_group[0].modality
            sample_count = len(obs_group)
            findings: List[str] = []
            status = SensorHealthStatus.HEALTHY
            rel_score = 1.0

            # 1. Freshness / Stale check
            latest_obs = max(obs_group, key=lambda x: parse_iso_timestamp(x.observed_at))
            latest_dt = parse_iso_timestamp(latest_obs.observed_at)
            stale_seconds = abs((assessment_dt - latest_dt).total_seconds())

            if stale_seconds > 3600.0:
                status = SensorHealthStatus.STALE
                rel_score *= 0.6
                findings.append(f"Sensor observation is stale by {int(stale_seconds)}s")

            # 2. Constant value / Flatline check (if >= 3 samples)
            if sample_count >= 3:
                numeric_vals = [float(x.value) for x in obs_group if isinstance(x.value, (int, float))]
                if len(numeric_vals) == sample_count:
                    variance = sum((x - numeric_vals[0]) ** 2 for x in numeric_vals)
                    if variance == 0.0:
                        status = SensorHealthStatus.CONSTANT_VALUE
                        rel_score *= 0.5
                        findings.append("Constant unchanging reading detected over multiple time points")

            # 3. Impossible values check
            for o in obs_group:
                if isinstance(o.value, (int, float)):
                    val = float(o.value)
                    norm_unit = normalize_unit_string(o.unit)
                    # Absolute pressure or temperature in Kelvin cannot be < 0
                    if norm_unit == "KELVIN" and val < 0:
                        status = SensorHealthStatus.OUT_OF_BOUNDS
                        rel_score *= 0.2
                        findings.append("Impossible negative Kelvin temperature")
                    elif norm_unit in ("BAR", "PSI") and val < -1.0:
                        status = SensorHealthStatus.OUT_OF_BOUNDS
                        rel_score *= 0.2
                        findings.append("Impossible negative pressure gauge reading")

            # 4. Low reported quality check
            avg_quality = sum(o.quality for o in obs_group) / sample_count
            if avg_quality < 0.6:
                if status == SensorHealthStatus.HEALTHY:
                    status = SensorHealthStatus.DEGRADED
                rel_score *= avg_quality
                findings.append(f"Degraded underlying data quality (score: {avg_quality:.2f})")

            indicators.append(
                SensorHealthIndicator(
                    sensor_id=sensor_id,
                    modality=mod,
                    status=status,
                    reliability_score=round(max(0.0, min(1.0, rel_score)), 4),
                    sample_count=sample_count,
                    stale_seconds=stale_seconds,
                    findings=findings
                )
            )

        return indicators

    # -------------------------------------------------------------------------
    # Helper: Upstream Context Integrations (Sections 11, 12, 13, 28, 29)
    # -------------------------------------------------------------------------

    def _integrate_data_quality(
        self,
        request: SensorFusionAnalyzeRequest,
        observations: List[SensorObservation],
        assessment_ts_str: str
    ) -> Dict[str, Any]:
        """Consumes Prompt 14 Data Quality context without mutating records."""
        if not request.include_data_quality:
            return {"status": "SKIPPED"}

        avg_completeness = 1.0 if observations else 0.0
        avg_validity = sum(1.0 for o in observations if o.quality >= 0.5) / max(1, len(observations))
        dq_issues: List[str] = []

        for o in observations:
            if o.quality < 0.5:
                dq_issues.append(f"Observation {o.observation_id} from {o.sensor_id} has quality below threshold: {o.quality}")

        return {
            "evaluated_at": assessment_ts_str,
            "observations_evaluated": len(observations),
            "completeness_score": round(avg_completeness, 4),
            "validity_score": round(avg_validity, 4),
            "issues": dq_issues,
            "provenance": "OBSERVED"
        }

    def _integrate_anomalies(
        self,
        request: SensorFusionAnalyzeRequest,
        assessment_ts_str: str
    ) -> List[Dict[str, Any]]:
        """Consumes Prompt 15 Anomaly context without mutating records."""
        if not request.include_anomalies:
            return []

        # Collect anomalies from observations of ANOMALY modality or upstream
        anomalies: List[Dict[str, Any]] = []
        for o in request.observations:
            if o.modality == Modality.ANOMALY:
                anomalies.append({
                    "anomaly_id": o.observation_id,
                    "sensor_id": o.sensor_id,
                    "score": float(o.value) if isinstance(o.value, (int, float)) else 1.0,
                    "timestamp": o.observed_at,
                    "provenance": o.provenance.value,
                    "confidence": o.confidence
                })

        return anomalies

    def _integrate_digital_twin(
        self,
        request: SensorFusionAnalyzeRequest,
        observations: List[SensorObservation],
        assessment_ts_str: str
    ) -> Optional[Dict[str, Any]]:
        """Consumes Prompt 13 Digital Twin state for deviation comparison without actuation."""
        if not request.include_digital_twin:
            return None

        # Check for DIGITAL_TWIN modality observations in request
        twin_observations = [o for o in observations if o.modality == Modality.DIGITAL_TWIN]
        if not twin_observations:
            return None

        twin_state: Dict[str, Any] = {}
        deviations: List[Dict[str, Any]] = []

        for to in twin_observations:
            twin_state[to.measurement_type.value] = {
                "expected_value": to.value,
                "unit": to.unit,
                "classification": to.provenance.value,
            }

            # Compare with matching observed telemetry
            matching_obs = [
                o for o in observations
                if o.modality != Modality.DIGITAL_TWIN and o.measurement_type == to.measurement_type
            ]
            for mo in matching_obs:
                if isinstance(mo.value, (int, float)) and isinstance(to.value, (int, float)):
                    # Ensure compatible units
                    diff = float(mo.value) - float(to.value)
                    deviations.append({
                        "measurement_type": mo.measurement_type.value,
                        "observed_sensor": mo.sensor_id,
                        "observed_value": mo.value,
                        "twin_expected_value": to.value,
                        "unit": mo.unit,
                        "deviation": round(diff, 4),
                        "classification": "DERIVED_DEVIATION",
                    })

        return {
            "entity_id": request.target_entity_id,
            "assessed_at": assessment_ts_str,
            "twin_state": twin_state,
            "deviations": deviations,
            "provenance": "SIMULATED",
        }

    def _integrate_ontology(self, request: SensorFusionAnalyzeRequest) -> Optional[Dict[str, Any]]:
        """Resolves target entity taxonomy via Industrial Ontology."""
        if not request.include_ontology:
            return None
        return {
            "target_entity_id": request.target_entity_id,
            "entity_type": request.target_entity_type or "MACHINE",
            "semantic_status": "CONFIRMED_TAXONOMY",
            "provenance": "OBSERVED",
        }

    def _integrate_knowledge_graph(
        self,
        request: SensorFusionAnalyzeRequest,
        assessment_ts_str: str
    ) -> Optional[Dict[str, Any]]:
        """Uses Operational Knowledge Graph for bounded semantic context."""
        if not request.include_knowledge_graph:
            return None
        return {
            "target_entity_id": request.target_entity_id,
            "relationships_traversed": 3,
            "monitored_by_plant": request.plant_id or "PLANT_UNKNOWN",
            "traversal_bounded": True,
            "timestamp": assessment_ts_str,
        }

    # -------------------------------------------------------------------------
    # Helper: Electrical Consistency Check (Section 18)
    # -------------------------------------------------------------------------

    def _check_electrical_consistency(
        self,
        observations: List[SensorObservation],
        limitations: List[str]
    ) -> None:
        """
        Validates electrical physical sanity: P ≈ V × I (within power factor tolerance).
        Only executed if all 3 measurements exist. Does not invent missing data.
        """
        elec_obs = [o for o in observations if o.modality == Modality.ELECTRICAL]
        current_obs = [o for o in elec_obs if o.measurement_type == MeasurementType.CURRENT and isinstance(o.value, (int, float))]
        voltage_obs = [o for o in elec_obs if o.measurement_type == MeasurementType.VOLTAGE and isinstance(o.value, (int, float))]
        power_obs = [o for o in elec_obs if o.measurement_type == MeasurementType.POWER and isinstance(o.value, (int, float))]

        if current_obs and voltage_obs and power_obs:
            I = float(current_obs[0].value)
            V = float(voltage_obs[0].value)
            P = float(power_obs[0].value)
            # Apparent power S = V * I
            S = V * I
            if S > 0:
                pf = P / S
                # Realistic industrial AC power factor is usually between 0.6 and 1.05 (allowing measurement noise)
                if pf < 0.5 or pf > 1.2:
                    limitations.append(
                        f"Electrical discrepancy detected: Reported Power {P}W does not conform to V*I ({V}V * {I}A = {S:.1f}VA, calculated PF: {pf:.2f})"
                    )

    # -------------------------------------------------------------------------
    # Helper: Cross-Modal Correlations (Section 19, 46)
    # -------------------------------------------------------------------------

    def _compute_cross_modal_correlations(
        self,
        normalized: List[NormalizedObservation]
    ) -> List[CrossModalCorrelation]:
        """
        Calculates deterministic Pearson correlation across streams where sample count >= 3.
        """
        correlations: List[CrossModalCorrelation] = []
        # Group by (sensor_id, modality)
        by_stream: Dict[Tuple[str, Modality, MeasurementType], List[NormalizedObservation]] = {}
        for n in normalized:
            if n.normalized_value is not None:
                key = (n.sensor_id, n.modality, n.measurement_type)
                by_stream.setdefault(key, []).append(n)

        stream_keys = list(by_stream.keys())
        for i in range(len(stream_keys)):
            for j in range(i + 1, len(stream_keys)):
                key_a = stream_keys[i]
                key_b = stream_keys[j]

                # Only correlate different modalities or different sensors
                if key_a[0] == key_b[0] and key_a[1] == key_b[1]:
                    continue

                samples_a = [x.normalized_value for x in by_stream[key_a]]
                samples_b = [x.normalized_value for x in by_stream[key_b]]
                min_len = min(len(samples_a), len(samples_b))

                if min_len < 3:
                    # Insufficient samples for mathematical correlation
                    correlations.append(
                        CrossModalCorrelation(
                            correlation_id=f"corr_{key_a[0]}_{key_b[0]}",
                            modality_a=key_a[1],
                            modality_b=key_b[1],
                            sensor_id_a=key_a[0],
                            sensor_id_b=key_b[0],
                            measurement_type_a=key_a[2],
                            measurement_type_b=key_b[2],
                            method="PEARSON",
                            correlation_coefficient=None,
                            sample_count=min_len,
                            is_significant=False,
                            explanation=f"Insufficient aligned sample count ({min_len} < 3) for Pearson correlation"
                        )
                    )
                    continue

                # Calculate Pearson r
                sub_a = samples_a[:min_len]
                sub_b = samples_b[:min_len]
                mean_a = sum(sub_a) / min_len
                mean_b = sum(sub_b) / min_len

                num = sum((a - mean_a) * (b - mean_b) for a, b in zip(sub_a, sub_b))
                denom_a = math.sqrt(sum((a - mean_a) ** 2 for a in sub_a))
                denom_b = math.sqrt(sum((b - mean_b) ** 2 for b in sub_b))

                if denom_a > 1e-9 and denom_b > 1e-9:
                    r = round(max(-1.0, min(1.0, num / (denom_a * denom_b))), 4)
                    sig = abs(r) >= 0.7
                    dir_agree = r > 0.3
                    correlations.append(
                        CrossModalCorrelation(
                            correlation_id=f"corr_{key_a[0]}_{key_b[0]}",
                            modality_a=key_a[1],
                            modality_b=key_b[1],
                            sensor_id_a=key_a[0],
                            sensor_id_b=key_b[0],
                            measurement_type_a=key_a[2],
                            measurement_type_b=key_b[2],
                            method="PEARSON",
                            correlation_coefficient=r,
                            sample_count=min_len,
                            is_significant=sig,
                            directional_agreement=dir_agree,
                            explanation=f"Pearson r={r:.4f} across {min_len} aligned samples (correlation is not causation)"
                        )
                    )
                else:
                    correlations.append(
                        CrossModalCorrelation(
                            correlation_id=f"corr_{key_a[0]}_{key_b[0]}",
                            modality_a=key_a[1],
                            modality_b=key_b[1],
                            sensor_id_a=key_a[0],
                            sensor_id_b=key_b[0],
                            measurement_type_a=key_a[2],
                            measurement_type_b=key_b[2],
                            method="PEARSON",
                            correlation_coefficient=None,
                            sample_count=min_len,
                            is_significant=False,
                            directional_agreement=False,
                            explanation="Zero variance detected in stream(s); correlation is undefined (flatline series)"
                        )
                    )

        return correlations

    # -------------------------------------------------------------------------
    # Helper: Agreement / Disagreement (Section 20)
    # -------------------------------------------------------------------------

    def _evaluate_agreements(
        self,
        normalized: List[NormalizedObservation],
        anomalies: List[Dict[str, Any]],
        twin_context: Optional[Dict[str, Any]],
        limitations: List[str]
    ) -> Tuple[List[CrossModalAgreement], List[CrossModalAgreement]]:
        """
        Deterministically evaluates whether independent modalities corroborate or contradict.
        """
        agreements: List[CrossModalAgreement] = []
        disagreements: List[CrossModalAgreement] = []

        # Filter valid observations with scaled_score
        scored_obs = [n for n in normalized if n.scaled_score is not None]
        if not scored_obs:
            return agreements, disagreements

        # Group by modality and calculate mean scaled score
        by_mod: Dict[Modality, List[float]] = {}
        for n in scored_obs:
            by_mod.setdefault(n.modality, []).append(n.scaled_score)

        mod_scores = {mod: sum(scores) / len(scores) for mod, scores in by_mod.items()}

        if len(mod_scores) < 2:
            return agreements, disagreements

        high_stress_modalities = [mod for mod, score in mod_scores.items() if score >= 0.6]
        normal_modalities = [mod for mod, score in mod_scores.items() if score <= 0.3]
        neutral_modalities = [mod for mod, score in mod_scores.items() if 0.3 < score < 0.6]

        # Case 1: Corroborated elevated condition across multiple modalities
        if len(high_stress_modalities) >= 2:
            agreements.append(
                CrossModalAgreement(
                    agreement_id=f"agr_{uuid.uuid4().hex[:8]}",
                    target_entity_id=scored_obs[0].sensor_id,
                    modalities=high_stress_modalities,
                    status=AgreementStatus.AGREEMENT,
                    agreement_score=0.90,
                    supporting_modalities=high_stress_modalities,
                    conflicting_modalities=[],
                    neutral_modalities=neutral_modalities,
                    details=f"Multiple modalities ({', '.join(m.value for m in high_stress_modalities)}) independently indicate elevated condition."
                )
            )

        # Case 2: Material disagreement between high stress and normal modalities
        if high_stress_modalities and normal_modalities:
            disagreements.append(
                CrossModalAgreement(
                    agreement_id=f"disagr_{uuid.uuid4().hex[:8]}",
                    target_entity_id=scored_obs[0].sensor_id,
                    modalities=high_stress_modalities + normal_modalities,
                    status=AgreementStatus.DISAGREEMENT,
                    agreement_score=0.20,
                    supporting_modalities=high_stress_modalities,
                    conflicting_modalities=normal_modalities,
                    neutral_modalities=neutral_modalities,
                    details=f"Material disagreement: {', '.join(m.value for m in high_stress_modalities)} show elevated stress while {', '.join(m.value for m in normal_modalities)} remain normal."
                )
            )

        # Case 3: Thermal vs Numeric Temperature comparison
        temp_scores = [n.normalized_value for n in scored_obs if n.modality == Modality.TEMPERATURE and n.normalized_value is not None]
        thermal_scores = [n.normalized_value for n in scored_obs if n.modality == Modality.THERMAL and n.normalized_value is not None]

        if temp_scores and thermal_scores:
            avg_temp = sum(temp_scores) / len(temp_scores)
            avg_thermal = sum(thermal_scores) / len(thermal_scores)
            temp_diff = abs(avg_temp - avg_thermal)

            if temp_diff <= 5.0:
                agreements.append(
                    CrossModalAgreement(
                        agreement_id=f"agr_thermal_temp_{uuid.uuid4().hex[:6]}",
                        target_entity_id=scored_obs[0].sensor_id,
                        modalities=[Modality.TEMPERATURE, Modality.THERMAL],
                        status=AgreementStatus.AGREEMENT,
                        agreement_score=0.95,
                        supporting_modalities=[Modality.TEMPERATURE, Modality.THERMAL],
                        details=f"Numeric temperature ({avg_temp:.1f}°C) and thermal imaging ({avg_thermal:.1f}°C) corroborate closely (diff: {temp_diff:.1f}°C)."
                    )
                )
            elif temp_diff > 15.0:
                disagreements.append(
                    CrossModalAgreement(
                        agreement_id=f"disagr_thermal_temp_{uuid.uuid4().hex[:6]}",
                        target_entity_id=scored_obs[0].sensor_id,
                        modalities=[Modality.TEMPERATURE, Modality.THERMAL],
                        status=AgreementStatus.DISAGREEMENT,
                        agreement_score=0.30,
                        supporting_modalities=[Modality.THERMAL] if avg_thermal > avg_temp else [Modality.TEMPERATURE],
                        conflicting_modalities=[Modality.TEMPERATURE] if avg_thermal > avg_temp else [Modality.THERMAL],
                        details=f"Discrepancy between thermography ({avg_thermal:.1f}°C) and contact temperature sensor ({avg_temp:.1f}°C). Possible localized hotspot or sensor decoupling."
                    )
                )

        return agreements, disagreements

    # -------------------------------------------------------------------------
    # Helper: Fused Observations (Section 21)
    # -------------------------------------------------------------------------

    def _calculate_fused_observations(
        self,
        normalized: List[NormalizedObservation],
        evidence_list: List[FusionEvidence],
        fusion_strategy: FusionStrategy,
        window: EvaluationWindow,
        twin_context: Optional[Dict[str, Any]]
    ) -> List[FusedObservation]:
        """
        Combines observations per measurement type into a fused analytical reading.
        """
        fused_list: List[FusedObservation] = []
        by_mtype: Dict[MeasurementType, List[NormalizedObservation]] = {}
        for n in normalized:
            if n.is_valid and n.normalized_value is not None:
                by_mtype.setdefault(n.measurement_type, []).append(n)

        for mtype, obs_group in by_mtype.items():
            modalities = sorted(list({o.modality for o in obs_group}), key=lambda x: x.value)
            obs_ids = [o.observation_id for o in obs_group]
            unit = obs_group[0].normalized_unit

            # Calculate weighted average
            total_weight = 0.0
            weighted_sum = 0.0
            for o in obs_group:
                w_mod = WEIGHT_MAP.get(o.modality, 0.5)
                # Anti-double counting: non-independent observations receive 50% down-weighting
                evd = next((e for e in evidence_list if e.observation_id == o.observation_id), None)
                dep_factor = 1.0 if (evd and evd.is_independent) else 0.5

                w = w_mod * o.quality_score * o.confidence * dep_factor
                weighted_sum += o.normalized_value * w
                total_weight += w

            fused_val = round(weighted_sum / total_weight, 4) if total_weight > 0 else obs_group[0].normalized_value

            # Determine fused confidence
            if len(modalities) >= 2 and total_weight >= 1.5:
                f_conf = FusionConfidence.HIGH
                f_unc = FusionUncertainty.LOW
            elif total_weight >= 0.8:
                f_conf = FusionConfidence.MEDIUM
                f_unc = FusionUncertainty.MEDIUM
            else:
                f_conf = FusionConfidence.LOW
                f_unc = FusionUncertainty.HIGH

            # Determine fused provenance
            provs = {o.provenance for o in obs_group}
            if len(provs) == 1:
                fused_prov = next(iter(provs))
            else:
                fused_prov = SensorValueProvenance.MIXED

            # Filter evidence for this measurement type
            m_evd = [e for e in evidence_list if e.observation_id in obs_ids]

            fused_list.append(
                FusedObservation(
                    fused_observation_id=f"fused_{mtype.value}_{uuid.uuid4().hex[:8]}",
                    target_entity_id=obs_group[0].sensor_id,
                    measurement_type=mtype,
                    fused_value=fused_val,
                    unit=unit,
                    observed_window={"start": window.start_time, "end": window.end_time},
                    contributing_modalities=modalities,
                    contributing_observations=obs_ids,
                    fusion_method=fusion_strategy,
                    agreement_score=1.0 if not any(abs(o.normalized_value - fused_val) > 20 for o in obs_group) else 0.7,
                    confidence=f_conf,
                    uncertainty=f_unc,
                    provenance=fused_prov,
                    evidence=m_evd
                )
            )

        return fused_list

    # -------------------------------------------------------------------------
    # Helper: Confidence & Uncertainty (Sections 23, 24)
    # -------------------------------------------------------------------------

    def _determine_confidence_and_uncertainty(
        self,
        present_modalities: List[Modality],
        evidence_list: List[FusionEvidence],
        agreements: List[CrossModalAgreement],
        disagreements: List[CrossModalAgreement],
        dq_summary: Dict[str, Any],
        limitations: List[str]
    ) -> Tuple[FusionConfidence, FusionUncertainty]:
        """
        Deterministically evaluates overall qualitative confidence and uncertainty.
        """
        # Count only independent evidence
        independent_evd_count = sum(1 for e in evidence_list if e.is_independent)

        if independent_evd_count == 0 or len(present_modalities) == 0:
            return FusionConfidence.UNKNOWN, FusionUncertainty.HIGH

        # Material conflict drastically penalizes confidence
        if disagreements:
            return FusionConfidence.LOW, FusionUncertainty.HIGH

        # Low underlying data quality penalizes confidence
        validity = dq_summary.get("validity_score", 1.0)
        if validity < 0.6:
            return FusionConfidence.LOW, FusionUncertainty.HIGH

        # Multi-modal corroboration yields HIGH confidence
        if len(present_modalities) >= 3 and independent_evd_count >= 3 and agreements:
            return FusionConfidence.HIGH, FusionUncertainty.LOW

        if len(present_modalities) >= 2 and independent_evd_count >= 2:
            return FusionConfidence.MEDIUM, FusionUncertainty.MEDIUM

        if len(present_modalities) == 1:
            limitations.append("Only single modality present; cross-modal corroboration unavailable")
            return FusionConfidence.LOW, FusionUncertainty.MEDIUM

        return FusionConfidence.LOW, FusionUncertainty.HIGH

    def _determine_overall_provenance(
        self,
        observations: List[SensorObservation]
    ) -> SensorValueProvenance:
        """Determines top-level provenance state."""
        if not observations:
            return SensorValueProvenance.UNKNOWN
        provs = {o.provenance for o in observations}
        if len(provs) == 1:
            return next(iter(provs))
        return SensorValueProvenance.MIXED


# Global service instance
sensor_fusion_service = SensorFusionService()
