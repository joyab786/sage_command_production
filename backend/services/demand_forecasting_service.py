import sys
from typing import List, Optional, Dict, Any
from datetime import datetime, UTC, timedelta

# Strict Execution Boundary Enforcement: We do not import ExecutionGateway.

try:
    from data.schemas.demand_forecasting_contract import (
        DemandForecast, ForecastEvaluation, Granularity, ForecastHorizon,
        TrendDirection, ForecastMethod, ConfidenceLevel, DemandObservation,
        ForecastEvidence, ForecastRecommendation, ForecastContext, ForecastPoint,
        ValueProvenance, ForecastEvaluationMetric
    )
    from services.demand_forecasting_repository import demand_forecasting_repository
    # We can import analytical services for context gathering, but NO execution
except ModuleNotFoundError:
    from backend.data.schemas.demand_forecasting_contract import (
        DemandForecast, ForecastEvaluation, Granularity, ForecastHorizon,
        TrendDirection, ForecastMethod, ConfidenceLevel, DemandObservation,
        ForecastEvidence, ForecastRecommendation, ForecastContext, ForecastPoint,
        ValueProvenance, ForecastEvaluationMetric
    )
    from backend.services.demand_forecasting_repository import demand_forecasting_repository

class DemandForecastingService:
    def __init__(self, repository=demand_forecasting_repository):
        self.repository = repository
        
        # Explicit bounds checking
        self.MAX_OBSERVATIONS = 1000
        self.MAX_FORECAST_POINTS = 365

    def generate_forecast(
        self,
        tenant_id: str,
        workspace_id: Optional[str],
        plant_id: Optional[str],
        demand_entity_id: str,
        horizon: ForecastHorizon,
        granularity: Granularity,
        observations: List[DemandObservation],
        evaluation_timestamp: Optional[str] = None
    ) -> DemandForecast:
        """
        Generates a deterministic demand forecast based on historical observations.
        No LLMs or nondeterministic logic are used for numerical generation.
        """
        # Truncate to max observations for resource bounds
        if len(observations) > self.MAX_OBSERVATIONS:
            observations = observations[-self.MAX_OBSERVATIONS:]
            
        now = evaluation_timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        
        # 1. Deterministically sort observations by timestamp
        sorted_obs = sorted(observations, key=lambda x: x.timestamp)
        
        # 2. Gather Context
        context = ForecastContext(
            anomalies_considered=0,
            data_quality_score=100.0,
            related_events=0,
            digital_twin_state_available=False,
            maintenance_context_available=False
        )
        
        evidence: List[ForecastEvidence] = []
        recommendations: List[ForecastRecommendation] = []
        
        # In a real impl, we'd query DQ and anomalies. Here we mock deterministic logic based on input length.
        if len(sorted_obs) < 5:
            context.data_quality_score = 50.0
            evidence.append(ForecastEvidence(
                factor_type="QUALITY",
                source="DATA_QUALITY_ENGINE",
                source_id="dq_rule_01",
                timestamp=now,
                contribution=-0.5,
                confidence=1.0,
                explanation="Insufficient historical data points."
            ))
            
        # 3. Method Selection
        method = ForecastMethod.INSUFFICIENT_DATA
        confidence = ConfidenceLevel.INSUFFICIENT_DATA
        trend = TrendDirection.INSUFFICIENT_DATA
        
        if len(sorted_obs) == 0:
            method = ForecastMethod.INSUFFICIENT_DATA
            baseline = 0.0
        elif len(sorted_obs) < 3:
            method = ForecastMethod.NAIVE
            baseline = sorted_obs[-1].value
            confidence = ConfidenceLevel.LOW
        else:
            # Deterministic Moving Average
            method = ForecastMethod.MOVING_AVERAGE
            recent = sorted_obs[-3:]
            baseline = sum(o.value for o in recent) / len(recent)
            confidence = ConfidenceLevel.MEDIUM
            
            # Trend Detection
            if sorted_obs[-1].value > sorted_obs[0].value * 1.05:
                trend = TrendDirection.INCREASING
                method = ForecastMethod.TREND_ADJUSTED
            elif sorted_obs[-1].value < sorted_obs[0].value * 0.95:
                trend = TrendDirection.DECREASING
                method = ForecastMethod.TREND_ADJUSTED
            else:
                trend = TrendDirection.STABLE

        # 4. Generate points
        points_to_generate = 7 if horizon == ForecastHorizon.SHORT_TERM else (30 if horizon == ForecastHorizon.MEDIUM_TERM else 90)
        
        # Prevent oversized horizon
        points_to_generate = min(points_to_generate, self.MAX_FORECAST_POINTS)
        
        forecast_points = []
        current_time = datetime.fromisoformat(now.replace("Z", "+00:00"))
        
        for i in range(1, points_to_generate + 1):
            if granularity == Granularity.HOURLY:
                dt = current_time + timedelta(hours=i)
            elif granularity == Granularity.DAILY:
                dt = current_time + timedelta(days=i)
            else:
                dt = current_time + timedelta(weeks=i)
                
            val = baseline
            if method == ForecastMethod.TREND_ADJUSTED:
                if trend == TrendDirection.INCREASING:
                    val = baseline + (baseline * 0.01 * i)
                elif trend == TrendDirection.DECREASING:
                    val = max(0.0, baseline - (baseline * 0.01 * i))
                    
            # Bounds
            uncertainty_factor = 0.1 * i  # uncertainty grows over time
            if confidence == ConfidenceLevel.LOW:
                uncertainty_factor *= 2
                
            forecast_points.append(ForecastPoint(
                timestamp=dt.isoformat().replace("+00:00", "Z"),
                value=round(val, 2),
                lower_bound=round(val * (1 - uncertainty_factor), 2),
                upper_bound=round(val * (1 + uncertainty_factor), 2)
            ))
            
        start_dt = forecast_points[0].timestamp if forecast_points else now
        end_dt = forecast_points[-1].timestamp if forecast_points else now
        
        if trend == TrendDirection.INCREASING:
            recommendations.append(ForecastRecommendation(
                observation_type="EXPECTED_INCREASE",
                description="Demand is trending upwards. Review capacity planning."
            ))
            
        forecast = DemandForecast(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            demand_entity_id=demand_entity_id,
            forecast_timestamp=now,
            forecast_horizon=horizon,
            forecast_granularity=granularity,
            forecast_start=start_dt,
            forecast_end=end_dt,
            baseline_value=round(baseline, 2) if baseline is not None else None,
            forecast_values=forecast_points,
            confidence=confidence,
            trend_context=trend,
            method_selected=method,
            historical_observations=sorted_obs,
            evidence=evidence,
            recommendations=recommendations,
            context=context,
            uncertainty="Uncertainty increases linearly with horizon length." if method != ForecastMethod.INSUFFICIENT_DATA else "No data."
        )
        
        forecast.generate_fingerprint()
        
        # 5. Persist
        return self.repository.save_forecast(forecast)
        
    def evaluate_forecast(self, forecast_id: str, tenant_id: str, actual_observations: List[DemandObservation]) -> ForecastEvaluation:
        """
        Backtesting evaluation of a previously generated forecast against new observations.
        """
        forecast = self.repository.get_forecast(forecast_id, tenant_id)
        if not forecast:
            raise ValueError(f"Forecast {forecast_id} not found.")
            
        if not actual_observations:
            raise ValueError("Evaluation requires actual observations.")
            
        # Deterministic MAE and RMSE calculation
        errors = []
        for point in forecast.forecast_values:
            # Find matching actual observation within a 1-hour window
            for actual in actual_observations:
                if actual.timestamp[:13] == point.timestamp[:13]: # matching up to hour
                    errors.append(actual.value - point.value)
                    break
                    
        if not errors:
            raise ValueError("No temporal intersection between forecast points and actual observations.")
            
        mae = sum(abs(e) for e in errors) / len(errors)
        rmse = (sum(e**2 for e in errors) / len(errors)) ** 0.5
        bias = sum(errors) / len(errors)
        
        metrics = [
            ForecastEvaluationMetric(metric="MAE", value=round(mae, 4), description="Mean Absolute Error"),
            ForecastEvaluationMetric(metric="RMSE", value=round(rmse, 4), description="Root Mean Square Error"),
            ForecastEvaluationMetric(metric="BIAS", value=round(bias, 4), description="Forecast Bias (Actual - Forecast)")
        ]
        
        evaluation = ForecastEvaluation(
            tenant_id=tenant_id,
            forecast_id=forecast_id,
            metrics=metrics,
            evaluation_observations=len(actual_observations)
        )
        
        return self.repository.save_evaluation(evaluation)
        
    def get_forecast(self, forecast_id: str, tenant_id: str) -> Optional[DemandForecast]:
        return self.repository.get_forecast(forecast_id, tenant_id)
        
    def query_forecasts(self, tenant_id: str, entity_id: Optional[str] = None) -> List[DemandForecast]:
        return self.repository.query_forecasts(tenant_id, entity_id)

demand_forecasting_service = DemandForecastingService()
