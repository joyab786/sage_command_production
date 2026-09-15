# backend/data/schemas/domain.py
"""
SageCommand V3 Core Domain Model Contracts
Defines Pydantic models for physical assets, operational entities, and systemic contracts.
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

try:
    from data.schemas.provenance import DataProvenance
    from data.schemas.event import IndustrialEvent
    from data.schemas.action import StructuredAction, ActionTarget
    from data.schemas.incident import IncidentObject, IncidentState, ActionState
    from data.schemas.mission import MissionObject
    from data.schemas.decision import DecisionObject
except ModuleNotFoundError:
    from backend.data.schemas.provenance import DataProvenance
    from backend.data.schemas.event import IndustrialEvent
    from backend.data.schemas.action import StructuredAction, ActionTarget
    from backend.data.schemas.incident import IncidentObject, IncidentState, ActionState
    from backend.data.schemas.mission import MissionObject
    from backend.data.schemas.decision import DecisionObject


class Sensor(BaseModel):
    sensor_id: str = Field(description="Unique sensor identifier, e.g., TEMP-402, VIB-101")
    sensor_type: str = Field(description="Sensor classification, e.g. Temperature, Vibration, Pressure")
    unit: str = Field(description="Measurement unit, e.g. Celsius, RPM, PSI")
    current_value: float = Field(description="Latest telemetry reading")
    status: Literal["OK", "WARNING", "CRITICAL", "OFFLINE"] = Field(default="OK")


class Machine(BaseModel):
    machine_id: str = Field(description="Unique machine identifier, e.g. MCH-CONVEYOR-01")
    name: str = Field(description="Human-readable machine name")
    category: str = Field(description="Category e.g. Motor, Hydraulic Valve, Robotic Arm")
    line_id: str = Field(description="Parent production line ID")
    status: Literal["RUNNING", "DEGRADED", "STOPPED", "MAINTENANCE"] = Field(default="RUNNING")
    sensors: List[Sensor] = Field(default_factory=list)


class ProductionLine(BaseModel):
    line_id: str = Field(description="Unique production line identifier, e.g. LINE-ALPHA")
    name: str = Field(description="Line name")
    plant_id: str = Field(description="Parent plant identifier")
    machines: List[Machine] = Field(default_factory=list)
    status: Literal["OPERATIONAL", "DEGRADED", "HALTED"] = Field(default="OPERATIONAL")


class Plant(BaseModel):
    plant_id: str = Field(description="Unique plant identifier, e.g. PLANT-DETROIT-01")
    name: str = Field(description="Plant name")
    location: str = Field(description="Geographic location")
    lines: List[ProductionLine] = Field(default_factory=list)


class SKU(BaseModel):
    sku_id: str = Field(description="Unique Stock Keeping Unit ID, e.g. SKU-THERM-88")
    name: str = Field(description="Item name")
    category: str = Field(description="Item category, e.g. Electronics, Power")
    unit_price: float = Field(description="Price per unit in USD")


class InventoryItem(BaseModel):
    item_id: str = Field(description="Inventory record ID")
    sku_id: str = Field(description="Associated SKU ID")
    item_name: str = Field(description="Item name")
    category: str = Field(description="Category")
    quantity: int = Field(description="Current on-hand stock quantity")
    reorder_threshold: int = Field(description="Reorder threshold quantity")
    unit_price: float = Field(description="Unit price")
    warehouse_id: str = Field(default="WH-MAIN", description="Warehouse ID")


class Warehouse(BaseModel):
    warehouse_id: str = Field(description="Unique warehouse ID")
    name: str = Field(description="Warehouse name")
    location: str = Field(description="Location")
    capacity_used_pct: float = Field(default=0.0)


class Supplier(BaseModel):
    supplier_id: str = Field(description="Supplier ID, e.g. SUP-APEX-01")
    name: str = Field(description="Supplier company name")
    lead_time_days: int = Field(description="Standard order lead time in days")
    reliability_score: float = Field(default=0.95, ge=0.0, le=1.0)


class Customer(BaseModel):
    customer_id: str = Field(description="Customer ID")
    name: str = Field(description="Customer organization name")
    sla_tier: Literal["TIER_1", "TIER_2", "STANDARD"] = Field(default="STANDARD")


class Order(BaseModel):
    order_id: str = Field(description="Order ID")
    customer_id: str = Field(description="Customer ID")
    sku_id: str = Field(description="Ordered SKU ID")
    quantity: int = Field(description="Ordered quantity")
    status: Literal["PENDING", "PROCESSING", "SHIPPED", "DELAYED", "FULFILLED"] = Field(default="PENDING")


class Employee(BaseModel):
    employee_id: str = Field(description="Employee ID")
    name: str = Field(description="Full name")
    role: Literal["OPERATOR", "ENGINEER", "MANAGER", "ADMIN"] = Field(default="OPERATOR")


class MaintenanceRecord(BaseModel):
    record_id: str = Field(description="Maintenance record ID")
    machine_id: str = Field(description="Target machine ID")
    performed_by: str = Field(description="Technician ID or name")
    details: str = Field(description="Maintenance log details")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Anomaly(BaseModel):
    anomaly_id: str = Field(description="Anomaly ID")
    anomaly_type: str = Field(description="Classification e.g. Low Stock, Shipment Delay, Thermal Spike")
    details: str = Field(description="Anomaly summary text")
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(default="MEDIUM")
    provenance: Optional[DataProvenance] = None


class Risk(BaseModel):
    risk_id: str = Field(description="Risk assessment ID")
    urgency_rating: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(default="HIGH")
    financial_exposure: str = Field(description="Formatted financial exposure e.g. $35,000 USD")
    summary: str = Field(description="Executive blast radius summary")


class Strategy(BaseModel):
    strategy_id: str = Field(description="Strategy ID e.g. S1, S2")
    action_text: str = Field(description="Operational resolution action")
    cost: float = Field(description="Estimated cost in USD")


class Simulation(BaseModel):
    simulation_id: str = Field(description="Simulation run ID")
    scenario_name: str = Field(description="Scenario name")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    results: Dict[str, Any] = Field(default_factory=dict)


class Approval(BaseModel):
    approval_id: str = Field(description="Approval record ID")
    decision_id: str = Field(description="Associated decision ID")
    approved_by_role: str = Field(description="Role approving transaction e.g. MANAGER")
    status: Literal["APPROVED", "REJECTED", "PENDING"] = Field(default="PENDING")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Execution(BaseModel):
    execution_id: str = Field(description="Execution run ID")
    decision_id: str = Field(description="Target decision ID")
    executed_query: Optional[str] = None
    status: ActionState = Field(default=ActionState.EXECUTING)


class Verification(BaseModel):
    verification_id: str = Field(description="Verification ID")
    execution_id: str = Field(description="Target execution ID")
    status: Literal["VERIFIED_SUCCESS", "VERIFICATION_FAILED", "UNVERIFIED"] = Field(default="UNVERIFIED")
    details: str = Field(description="Post-execution telemetry audit findings")


class Evidence(BaseModel):
    evidence_id: str = Field(description="Evidence ID")
    source: str = Field(description="Data origin e.g. SQL Query, Tavily Search, Vision Assessment")
    content: str = Field(description="Evidence content summary")
    provenance: Optional[DataProvenance] = None
