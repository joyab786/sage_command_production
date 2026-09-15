# backend/data/schemas/event.py
import uuid
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

try:
    from data.schemas.provenance import DataProvenance
except ModuleNotFoundError:
    from backend.data.schemas.provenance import DataProvenance


class IndustrialEvent(BaseModel):
    """
    Standardized internal event contract for SageCommand V3 event-driven architecture.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique event UUID identifier")
    event_type: str = Field(description="Structured event topic/type, e.g., inventory.low_stock, machine.overheat")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="ISO-8601 timestamp")
    source: str = Field(description="Originating system or component, e.g., erp, plc, discovery_agent")
    tenant_id: str = Field(default="default_tenant", description="Enterprise tenant identifier")
    plant_id: str = Field(default="PLANT-01", description="Industrial plant identifier")
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] = Field(default="MEDIUM", description="Event severity rating")
    entity_type: str = Field(description="Target entity type, e.g., inventory, machine, shipment")
    entity_id: str = Field(description="Target entity identifier, e.g., SKU-123, MCH-404")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event telemetry payload data")
    provenance: Optional[DataProvenance] = Field(default=None, description="Data origin and freshness tracking metadata")
