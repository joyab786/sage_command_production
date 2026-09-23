import sys
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, UTC

# Strict Execution Boundary Enforcement: We do not import ExecutionGateway.

try:
    from data.schemas.supplier_risk_contract import (
        SupplierRiskAssessment, 
        SupplierRiskStatus, 
        SupplierRiskConfidence,
        RiskFactor,
        SupplierRiskEvidence,
        SupplierExposure,
        AnalyticalObservation,
        ContextBounds
    )
    from services.supplier_risk_repository import supplier_risk_repository
except ImportError as e:
    raise ImportError(f"Missing internal dependencies for Supplier Risk Intelligence: {e}")


class SupplierRiskService:
    """
    Deterministic analytical subsystem for calculating Supplier Risk.
    This service is side-effect-free and strictly read-only regarding operational systems.
    It does NOT connect to the ExecutionGateway.
    """
    
    def analyze_supplier_risk(self, tenant_id: str, supplier_id: str, as_of_timestamp: str, raw_observations: List[Dict[str, Any]]) -> SupplierRiskAssessment:
        """
        Deterministically analyze a supplier's risk using raw operational observations.
        """
        # Filter observations temporally (strict as_of_timestamp boundary)
        valid_observations = []
        data_quality_issues = []
        
        ts = as_of_timestamp.replace("Z", "+00:00")
        if ts.count("+00:00") > 1:
            ts = ts.replace("+00:00+00:00", "+00:00")
        try:
            as_of_dt = datetime.fromisoformat(ts)
        except ValueError:
            raise ValueError(f"Invalid as_of_timestamp format: {as_of_timestamp}")
        
        for obs in raw_observations:
            ts_str = obs.get("timestamp")
            if not ts_str:
                data_quality_issues.append("Missing timestamp on observation.")
                continue
                
            try:
                obs_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                data_quality_issues.append(f"Invalid timestamp format: {ts_str}")
                continue
                
            if obs_dt > as_of_dt:
                # Exclude future observations deterministically to prevent temporal leakage
                continue
            
            valid_observations.append(obs)
            
        observation_count = len(valid_observations)
        
        if observation_count == 0:
            # Insufficient data
            assessment = SupplierRiskAssessment(
                tenant_id=tenant_id,
                supplier_id=supplier_id,
                as_of_timestamp=as_of_timestamp,
                risk_status=SupplierRiskStatus.UNKNOWN,
                risk_score=0.0,
                confidence=SupplierRiskConfidence.INSUFFICIENT_DATA,
                uncertainty="No valid observations found prior to as_of_timestamp.",
                factors=[],
                evidence=[],
                exposure_summary=SupplierExposure(),
                data_quality_issues=data_quality_issues + ["No valid observations found prior to as_of_timestamp."]
            )
            assessment.generate_fingerprint()
            return supplier_risk_repository.save_assessment(assessment)

        factors = []
        evidence = []
        observations = []
        
        # Calculate Delivery Reliability
        late_count = sum(1 for obs in valid_observations if obs.get("type") == "delivery" and obs.get("status") == "late")
        delivery_total = sum(1 for obs in valid_observations if obs.get("type") == "delivery")
        
        if delivery_total > 0:
            late_rate = late_count / delivery_total
            delivery_score = min(100.0, late_rate * 200.0)  # e.g., 50% late = 100.0 risk score
            weight = 0.3
            factors.append(RiskFactor(
                factor_name="delivery_reliability", 
                score=delivery_score, 
                weight=weight, 
                contribution=delivery_score * weight,
                explanation=f"Calculated from {late_count} late out of {delivery_total} deliveries"
            ))
            evidence.append(SupplierRiskEvidence(
                factor_type="delivery_reliability",
                source="ERP",
                source_id="erp-1",
                supplier_id=supplier_id,
                timestamp=as_of_timestamp,
                observed_value=late_rate,
                expected_value=0.0,
                contribution=delivery_score * weight,
                confidence=min(1.0, delivery_total / 10.0),
                explanation="Late delivery rate"
            ))
            if late_rate > 0.2:
                observations.append(AnalyticalObservation(
                    observation_type="DELIVERY_WARNING",
                    description=f"Monitor supplier delivery reliability. Late rate is {(late_rate*100):.1f}%."
                ))
        
        # Calculate Quality 
        defect_count = sum(1 for obs in valid_observations if obs.get("type") == "quality" and obs.get("status") == "defective")
        quality_total = sum(1 for obs in valid_observations if obs.get("type") == "quality")
        
        if quality_total > 0:
            defect_rate = defect_count / quality_total
            quality_score = min(100.0, defect_rate * 500.0) # e.g., 20% defect = 100.0 risk score
            weight = 0.3
            factors.append(RiskFactor(
                factor_name="quality", 
                score=quality_score, 
                weight=weight, 
                contribution=quality_score * weight,
                explanation=f"Calculated from {defect_count} defective out of {quality_total} quality inspections"
            ))
            evidence.append(SupplierRiskEvidence(
                factor_type="quality",
                source="QMS",
                source_id="qms-1",
                supplier_id=supplier_id,
                timestamp=as_of_timestamp,
                observed_value=defect_rate,
                expected_value=0.0,
                contribution=quality_score * weight,
                confidence=min(1.0, quality_total / 10.0),
                explanation="Defect rate"
            ))
            if defect_rate > 0.1:
                observations.append(AnalyticalObservation(
                    observation_type="QUALITY_WARNING",
                    description=f"Investigate quality trend. Defect rate is {(defect_rate*100):.1f}%."
                ))
        
        # Calculate Capacity / Disruptions
        disruption_count = sum(1 for obs in valid_observations if obs.get("type") in ("disruption", "shortfall"))
        if disruption_count > 0:
            disruption_score = min(100.0, disruption_count * 25.0)
            weight = 0.2
            factors.append(RiskFactor(
                factor_name="capacity_disruption", 
                score=disruption_score, 
                weight=weight, 
                contribution=disruption_score * weight,
                explanation=f"Calculated from {disruption_count} disruptions/shortfalls"
            ))
            evidence.append(SupplierRiskEvidence(
                factor_type="capacity_disruption",
                source="INCIDENT_MGT",
                source_id="inc-1",
                supplier_id=supplier_id,
                timestamp=as_of_timestamp,
                observed_value=disruption_count,
                expected_value=0,
                contribution=disruption_score * weight,
                confidence=1.0,
                explanation="Count of supply disruptions"
            ))
            observations.append(AnalyticalObservation(
                observation_type="CAPACITY_WARNING",
                description=f"Review capacity evidence due to {disruption_count} recent shortfalls."
            ))

        # Concentration / Dependency Risk
        # We derive this from specific concentration observations if provided.
        single_source = any(obs.get("single_source", False) for obs in valid_observations)
        affected_plants = max([obs.get("affected_plant_count", 0) for obs in valid_observations] + [0])
        
        if single_source or affected_plants > 1:
            concentration_score = 100.0 if single_source else min(100.0, affected_plants * 20.0)
            weight = 0.2
            factors.append(RiskFactor(
                factor_name="concentration", 
                score=concentration_score, 
                weight=weight, 
                contribution=concentration_score * weight,
                explanation="Single source exposure or high plant concentration"
            ))
            evidence.append(SupplierRiskEvidence(
                factor_type="concentration",
                source="KNOWLEDGE_GRAPH",
                source_id="kg-1",
                supplier_id=supplier_id,
                timestamp=as_of_timestamp,
                observed_value={"single_source": single_source, "plants": affected_plants},
                contribution=concentration_score * weight,
                confidence=1.0,
                explanation="Dependency concentration"
            ))
            if single_source:
                observations.append(AnalyticalObservation(
                    observation_type="CONCENTRATION_WARNING",
                    description="Review single-source exposure for critical dependency."
                ))

        # Aggregate weighted score deterministically
        total_weight = sum(f.weight for f in factors)
        if total_weight > 0:
            aggregated_score = sum(f.contribution for f in factors) / total_weight
        else:
            aggregated_score = 0.0

        # Determine Risk Status deterministically
        if aggregated_score > 75.0:
            status = SupplierRiskStatus.CRITICAL
        elif aggregated_score > 50.0:
            status = SupplierRiskStatus.HIGH
        elif aggregated_score > 25.0:
            status = SupplierRiskStatus.MEDIUM
        else:
            status = SupplierRiskStatus.LOW
            
        # Determine Confidence
        if observation_count > 50:
            confidence = SupplierRiskConfidence.HIGH
            uncertainty = "Low uncertainty."
        elif observation_count > 10:
            confidence = SupplierRiskConfidence.MEDIUM
            uncertainty = "Moderate uncertainty due to medium observation count."
        else:
            confidence = SupplierRiskConfidence.LOW
            uncertainty = "High uncertainty due to sparse data."
            
        # Mocking Exposure - deterministic extraction from observations 
        comp_count = max([obs.get("affected_component_count", 0) for obs in valid_observations] + [0])
        sku_count = max([obs.get("affected_sku_count", 0) for obs in valid_observations] + [0])
        ord_count = max([obs.get("affected_order_count", 0) for obs in valid_observations] + [0])
        forecast_exposure = max([obs.get("forecast_exposure_units", 0) for obs in valid_observations] + [0])
        
        exposure = SupplierExposure(
            affected_component_count=comp_count,
            affected_sku_count=sku_count,
            affected_order_count=ord_count,
            affected_plant_count=affected_plants,
            forecast_exposure_units=forecast_exposure if forecast_exposure > 0 else None,
            single_source_exposure=single_source
        )
        
        assessment = SupplierRiskAssessment(
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            as_of_timestamp=as_of_timestamp,
            risk_status=status if len(factors) > 0 else SupplierRiskStatus.UNKNOWN,
            risk_score=aggregated_score if len(factors) > 0 else 0.0,
            confidence=confidence if len(factors) > 0 else SupplierRiskConfidence.INSUFFICIENT_DATA,
            uncertainty=uncertainty if len(factors) > 0 else "Insufficient evidence to assess risk.",
            factors=factors,
            evidence=evidence,
            observations=observations,
            exposure_summary=exposure,
            data_quality_issues=data_quality_issues
        )
        
        assessment.generate_fingerprint()
        return supplier_risk_repository.save_assessment(assessment)
        
    def get_history(self, tenant_id: str, supplier_id: str, limit: int = 100) -> List[SupplierRiskAssessment]:
        """
        Fetch historical assessments for a supplier, bounded and isolated to the tenant.
        """
        bounded_limit = min(limit, 100)
        return supplier_risk_repository.get_history(supplier_id, tenant_id, bounded_limit)
        
    def get_assessment(self, tenant_id: str, assessment_id: str) -> Optional[SupplierRiskAssessment]:
        """
        Retrieve a specific assessment by ID, strictly bounded by tenant.
        """
        return supplier_risk_repository.get_assessment(assessment_id, tenant_id)

    def get_summary(self, tenant_id: str, supplier_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a high-level summary of the latest supplier risk assessment.
        """
        latest = supplier_risk_repository.get_latest_assessment(supplier_id, tenant_id)
        if not latest:
            return None
            
        return {
            "supplier_id": latest.supplier_id,
            "risk_status": latest.risk_status.value,
            "risk_score": latest.risk_score,
            "confidence": latest.confidence.value,
            "assessment_timestamp": latest.assessment_timestamp,
            "fingerprint": latest.input_fingerprint
        }


supplier_risk_service = SupplierRiskService()
