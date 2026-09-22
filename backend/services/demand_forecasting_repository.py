import json
import sqlite3
import threading
from typing import List, Optional, Dict, Any

try:
    from core.config import SAGE_DEMAND_FORECASTING_DB_PATH
    from data.schemas.demand_forecasting_contract import (
        DemandForecast,
        ForecastEvaluation,
        Granularity,
        ForecastHorizon,
        TrendDirection,
        ForecastMethod,
        ConfidenceLevel,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_DEMAND_FORECASTING_DB_PATH
    from backend.data.schemas.demand_forecasting_contract import (
        DemandForecast,
        ForecastEvaluation,
        Granularity,
        ForecastHorizon,
        TrendDirection,
        ForecastMethod,
        ConfidenceLevel,
    )

import os

class DemandForecastingRepository:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or SAGE_DEMAND_FORECASTING_DB_PATH
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Forecasts table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS demand_forecasts_v3 (
                            forecast_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            workspace_id TEXT,
                            plant_id TEXT,
                            demand_entity_id TEXT NOT NULL,
                            forecast_timestamp TEXT NOT NULL,
                            forecast_horizon TEXT NOT NULL,
                            forecast_granularity TEXT NOT NULL,
                            confidence TEXT NOT NULL,
                            trend_context TEXT NOT NULL,
                            method_selected TEXT NOT NULL,
                            input_fingerprint TEXT NOT NULL,
                            payload_json TEXT NOT NULL
                        )
                    """)
                    
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_demand_forecasts_tenant_entity 
                        ON demand_forecasts_v3(tenant_id, demand_entity_id)
                    """)
                    
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_demand_forecasts_fingerprint 
                        ON demand_forecasts_v3(input_fingerprint)
                    """)
                    
                    # Evaluations table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS demand_forecast_evaluations_v3 (
                            evaluation_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            forecast_id TEXT NOT NULL,
                            evaluation_timestamp TEXT NOT NULL,
                            payload_json TEXT NOT NULL
                        )
                    """)
                    
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_demand_evaluations_tenant_forecast 
                        ON demand_forecast_evaluations_v3(tenant_id, forecast_id)
                    """)
            finally:
                conn.close()

    def save_forecast(self, forecast: DemandForecast) -> DemandForecast:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Check for deduplication by fingerprint
                    row = conn.execute(
                        "SELECT forecast_id FROM demand_forecasts_v3 WHERE input_fingerprint = ?", 
                        (forecast.input_fingerprint,)
                    ).fetchone()
                    
                    if row:
                        forecast.forecast_id = row["forecast_id"]
                        return forecast
                        
                    conn.execute("""
                        INSERT INTO demand_forecasts_v3 (
                            forecast_id, tenant_id, workspace_id, plant_id,
                            demand_entity_id, forecast_timestamp, forecast_horizon,
                            forecast_granularity, confidence, trend_context,
                            method_selected, input_fingerprint, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        forecast.forecast_id,
                        forecast.tenant_id,
                        forecast.workspace_id,
                        forecast.plant_id,
                        forecast.demand_entity_id,
                        forecast.forecast_timestamp,
                        forecast.forecast_horizon.value,
                        forecast.forecast_granularity.value,
                        forecast.confidence.value,
                        forecast.trend_context.value,
                        forecast.method_selected.value,
                        forecast.input_fingerprint,
                        forecast.model_dump_json()
                    ))
                return forecast
            finally:
                conn.close()

    def get_forecast(self, forecast_id: str, tenant_id: str) -> Optional[DemandForecast]:
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT payload_json FROM demand_forecasts_v3 WHERE forecast_id = ? AND tenant_id = ?",
                    (forecast_id, tenant_id)
                ).fetchone()
                
                if row:
                    return DemandForecast.model_validate_json(row["payload_json"])
                return None
            finally:
                conn.close()

    def query_forecasts(self, tenant_id: str, entity_id: Optional[str] = None, limit: int = 50) -> List[DemandForecast]:
        with self._lock:
            conn = self._get_connection()
            try:
                query = "SELECT payload_json FROM demand_forecasts_v3 WHERE tenant_id = ?"
                params = [tenant_id]
                
                if entity_id:
                    query += " AND demand_entity_id = ?"
                    params.append(entity_id)
                    
                query += " ORDER BY forecast_timestamp DESC LIMIT ?"
                params.append(limit)
                
                rows = conn.execute(query, params).fetchall()
                return [DemandForecast.model_validate_json(row["payload_json"]) for row in rows]
            finally:
                conn.close()

    def save_evaluation(self, evaluation: ForecastEvaluation) -> ForecastEvaluation:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO demand_forecast_evaluations_v3 (
                            evaluation_id, tenant_id, forecast_id,
                            evaluation_timestamp, payload_json
                        ) VALUES (?, ?, ?, ?, ?)
                    """, (
                        evaluation.evaluation_id,
                        evaluation.tenant_id,
                        evaluation.forecast_id,
                        evaluation.evaluation_timestamp,
                        evaluation.model_dump_json()
                    ))
                return evaluation
            finally:
                conn.close()

    def get_evaluations(self, forecast_id: str, tenant_id: str) -> List[ForecastEvaluation]:
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT payload_json FROM demand_forecast_evaluations_v3 WHERE forecast_id = ? AND tenant_id = ? ORDER BY evaluation_timestamp DESC",
                    (forecast_id, tenant_id)
                ).fetchall()
                return [ForecastEvaluation.model_validate_json(row["payload_json"]) for row in rows]
            finally:
                conn.close()

demand_forecasting_repository = DemandForecastingRepository()
