# backend/data/schemas/provenance.py
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


class DataSourceType(str, Enum):
    REAL_DATA = "REAL_DATA"
    SIMULATED_DATA = "SIMULATED_DATA"
    STALE_DATA = "STALE_DATA"
    INFERRED_DATA = "INFERRED_DATA"
    AI_GENERATED_DATA = "AI_GENERATED_DATA"


class DataProvenance(BaseModel):
    """
    Establishes origin, freshness, and confidence tracking for all telemetry
    and inferred operational data in SageCommand V3.
    """
    source: str = Field(description="System or sensor identifier, e.g. PLC-LINE-4, ERP-SAP, SIMULATOR")
    source_type: DataSourceType = Field(default=DataSourceType.REAL_DATA, description="Classification of data origin")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="ISO-8601 creation timestamp")
    freshness_seconds: float = Field(default=0.0, description="Age of data in seconds since measurement")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    data_version: str = Field(default="1.0", description="Schema version identifier")
    is_simulated: bool = Field(default=False, description="Flag indicating synthetic or simulation origin")
    is_inferred: bool = Field(default=False, description="Flag indicating AI inference derivation")
