# backend/data/schemas/action.py
import uuid
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class ActionTarget(BaseModel):
    entity_type: str = Field(description="Type of entity being modified, e.g. SKU, Machine, Shipment")
    entity_id: str = Field(description="Unique ID of target entity")


class StructuredAction(BaseModel):
    """
    SageCommand V3 Structured Action Contract.
    Agents generate structured actions rather than arbitrary unvalidated SQL statements.
    """
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique action UUID")
    action_type: str = Field(description="Action verb/type, e.g. REORDER_INVENTORY, REALLOCATE_STOCK, ADJUST_PRICING")
    target: ActionTarget = Field(description="Target entity specification")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Execution payload parameters")
    reason: str = Field(description="Justification / operational reasoning behind proposed action")
    risk_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(default="MEDIUM", description="Assessed risk level")
    estimated_cost: float = Field(default=0.0, description="Estimated financial cost in USD")
    requires_approval: bool = Field(default=True, description="Human-in-the-loop approval gate requirement")
    rollback_supported: bool = Field(default=True, description="Whether transaction rollback is supported")
