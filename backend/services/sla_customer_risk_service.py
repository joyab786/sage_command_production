import datetime
from typing import List, Optional, Dict, Any

from data.schemas.sla_customer_risk_contract import (
    SLACustomerRiskAssessment, SLARiskStatus, SLARiskLevel, SLARiskConfidence, 
    SLARiskFactor, SLAEvidence, SLAHistoricalPerformance, SLACapacityExposure, SLADemandExposure, SLAContextBounds
)
from services.sla_customer_risk_repository import sla_customer_risk_repository

class SLACustomerRiskService:
    
    def analyze(self, 
                tenant_id: str,
                customer_id: str,
                service_id: str,
                observation_start: str,
                observation_end: str,
                assessment_timestamp: str,
                commitment_due_at: Optional[str] = None,
                expected_completion_at: Optional[str] = None,
                evidence_payloads: List[Dict[str, Any]] = None,
                historical_data: Dict[str, Any] = None,
                capacity_data: Dict[str, Any] = None,
                demand_data: Dict[str, Any] = None,
                workspace_id: Optional[str] = None) -> SLACustomerRiskAssessment:
        
        evidence_payloads = evidence_payloads or []
        historical_data = historical_data or {}
        capacity_data = capacity_data or {}
        demand_data = demand_data or {}
        
        # 1. Process Evidence filtering out future leakage
        processed_evidence: List[SLAEvidence] = []
        for e_data in evidence_payloads:
            obs_ts = e_data.get("observation_timestamp", "")
            if obs_ts and obs_ts > assessment_timestamp:
                continue # Temporal leakage protection
                
            eff_ts = e_data.get("effective_timestamp")
            if eff_ts and eff_ts > assessment_timestamp:
                continue
                
            e = SLAEvidence(
                source_domain=e_data.get("source_domain", "UNKNOWN"),
                source_reference=e_data.get("source_reference", "unknown"),
                observation_timestamp=obs_ts,
                effective_timestamp=eff_ts,
                evidence_type=e_data.get("evidence_type", "observation"),
                value=e_data.get("value"),
                contribution=float(e_data.get("contribution", 0.0)),
                confidence=float(e_data.get("confidence", 1.0)),
                provenance=e_data.get("provenance", "OBSERVED"),
                explanation=e_data.get("explanation", "")
            )
            processed_evidence.append(e)

        # 2. Extract Historical
        total_commitments = historical_data.get("total_commitments", 0)
        breach_count = historical_data.get("breach_count", 0)
        late_count = historical_data.get("late_count", 0)
        avg_delay = float(historical_data.get("average_delay_hours", 0.0))
        worst_delay = float(historical_data.get("worst_delay_hours", 0.0))
        compliance_rate = 0.0
        if total_commitments > 0:
            compliance_rate = ((total_commitments - breach_count) / total_commitments) * 100.0

        history = SLAHistoricalPerformance(
            total_commitments=total_commitments,
            breach_count=breach_count,
            late_count=late_count,
            compliance_rate=compliance_rate,
            average_delay_hours=avg_delay,
            worst_delay_hours=worst_delay,
            trend=historical_data.get("trend", "STABLE")
        )

        # 3. Capacity & Demand
        cap_exposure = SLACapacityExposure(
            utilization_percent=float(capacity_data.get("utilization_percent", 0.0)),
            shortfall_units=int(capacity_data.get("shortfall_units", 0)),
            projected_pressure=capacity_data.get("projected_pressure", "LOW")
        )

        dem_exposure = SLADemandExposure(
            forecast_exceeds_capacity=bool(demand_data.get("forecast_exceeds_capacity", False)),
            demand_acceleration=demand_data.get("demand_acceleration", "FLAT"),
            forecast_uncertainty=float(demand_data.get("forecast_uncertainty", 0.0))
        )

        # 4. Deterministic Scoring Logic
        base_score = 0.0
        factors = []
        data_quality_issues = []
        
        # A. Historical Factor
        hist_score = 0.0
        if total_commitments < 5:
            data_quality_issues.append("INSUFFICIENT_HISTORY")
        else:
            if compliance_rate < 80.0:
                hist_score = 80.0
            elif compliance_rate < 95.0:
                hist_score = 40.0
            else:
                hist_score = 10.0
            
            factors.append(SLARiskFactor(
                factor_name="historical_performance",
                score=hist_score,
                weight=0.25,
                contribution=hist_score * 0.25,
                explanation=f"Based on {compliance_rate:.1f}% historical compliance"
            ))
            base_score += hist_score * 0.25

        # B. Temporal Projection Factor
        proj_score = 0.0
        if commitment_due_at and expected_completion_at:
            if expected_completion_at > commitment_due_at:
                proj_score = 100.0
                factors.append(SLARiskFactor(
                    factor_name="projected_breach",
                    score=proj_score,
                    weight=0.40,
                    contribution=proj_score * 0.40,
                    explanation="Expected completion is past commitment due date"
                ))
            else:
                # Calculate margin
                # Since we can't use datetime parsing nondeterministically safely, we assume string comparison 
                # or just use evidence. We'll do a simple string comparison since ISO 8601 is lexicographically sortable.
                proj_score = 10.0
                factors.append(SLARiskFactor(
                    factor_name="projected_on_track",
                    score=proj_score,
                    weight=0.40,
                    contribution=proj_score * 0.40,
                    explanation="Expected completion is before commitment due date"
                ))
            base_score += proj_score * 0.40

        # C. Evidence factors (Incidents, Anomalies, Supplier, Maintenance)
        evd_score = 0.0
        active_incidents = len([e for e in processed_evidence if e.source_domain == "INCIDENT"])
        supplier_risks = len([e for e in processed_evidence if e.source_domain == "SUPPLIER_RISK"])
        maintenance_risks = len([e for e in processed_evidence if e.source_domain == "PREDICTIVE_MAINTENANCE"])
        
        if active_incidents > 0:
            evd_score += 30.0
        if supplier_risks > 0:
            evd_score += 30.0
        if maintenance_risks > 0:
            evd_score += 20.0
            
        evd_score = min(evd_score, 100.0)
        
        if evd_score > 0:
            factors.append(SLARiskFactor(
                factor_name="operational_evidence",
                score=evd_score,
                weight=0.35,
                contribution=evd_score * 0.35,
                explanation="Operational exposures detected on dependency path"
            ))
            base_score += evd_score * 0.35
            
        # Normalize score
        risk_score = min(base_score, 100.0)

        # 5. Risk Level & Status
        if len(factors) == 0 and not (commitment_due_at and expected_completion_at):
            risk_level = SLARiskLevel.INSUFFICIENT_DATA
            sla_status = SLARiskStatus.INSUFFICIENT_DATA
            confidence = SLARiskConfidence.INSUFFICIENT_DATA
        else:
            if risk_score >= 80.0:
                risk_level = SLARiskLevel.CRITICAL
                sla_status = SLARiskStatus.LIKELY_BREACH
            elif risk_score >= 50.0:
                risk_level = SLARiskLevel.HIGH
                sla_status = SLARiskStatus.AT_RISK
            elif risk_score >= 25.0:
                risk_level = SLARiskLevel.MEDIUM
                sla_status = SLARiskStatus.AT_RISK
            else:
                risk_level = SLARiskLevel.LOW
                sla_status = SLARiskStatus.ON_TRACK
                
            # Check for actual temporal breach if due_at is before assessment
            if commitment_due_at and commitment_due_at < assessment_timestamp:
                # If we don't have completion, or completion is after due_at
                if not expected_completion_at or expected_completion_at > commitment_due_at:
                    sla_status = SLARiskStatus.BREACHED
                    risk_level = SLARiskLevel.CRITICAL
                    risk_score = 100.0
                    
            if total_commitments > 20 and len(processed_evidence) >= 2:
                confidence = SLARiskConfidence.HIGH
            elif len(processed_evidence) > 0 or total_commitments > 5:
                confidence = SLARiskConfidence.MEDIUM
            else:
                confidence = SLARiskConfidence.LOW

        # 6. Assembly
        assessment = SLACustomerRiskAssessment(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            customer_id=customer_id,
            service_id=service_id,
            assessment_timestamp=assessment_timestamp,
            observation_start=observation_start,
            observation_end=observation_end,
            commitment_due_at=commitment_due_at,
            expected_completion_at=expected_completion_at,
            risk_level=risk_level,
            sla_status=sla_status,
            risk_score=risk_score,
            confidence=confidence,
            factors=factors,
            evidence=processed_evidence,
            historical_performance=history,
            capacity_exposure=cap_exposure,
            demand_exposure=dem_exposure,
            data_quality_issues=data_quality_issues
        )
        
        assessment.generate_fingerprint()
        
        # 7. Persist
        saved = sla_customer_risk_repository.save_assessment(assessment)
        return saved

sla_customer_risk_service = SLACustomerRiskService()
