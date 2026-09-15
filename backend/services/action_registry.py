# backend/services/action_registry.py
"""
SageCommand V3 — Action Registry Service
Maintains the centralized, extensible registry of officially supported industrial action types,
versioned parameter schemas, resource compatibility, deterministic risk classification,
and human preview builders.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel

try:
    from data.schemas.action_contract import (
        ActionType,
        ResourceType,
        RiskLevel,
        RollbackCapability,
        BaseActionParameters,
        AdjustReorderPointParameters,
        ReorderInventoryParameters,
        MoveInventoryParameters,
        ScheduleMaintenanceParameters,
        CreateMaintenanceWorkOrderParameters,
        RescheduleProductionParameters,
        ChangeProductionPlanParameters,
        UpdateSupplierOrderParameters,
        EscalateIncidentParameters,
        NotifyStakeholderParameters,
        UpdateSLAPriorityParameters,
        ACTION_PARAMETER_SCHEMAS,
    )
except ModuleNotFoundError:
    from backend.data.schemas.action_contract import (
        ActionType,
        ResourceType,
        RiskLevel,
        RollbackCapability,
        BaseActionParameters,
        AdjustReorderPointParameters,
        ReorderInventoryParameters,
        MoveInventoryParameters,
        ScheduleMaintenanceParameters,
        CreateMaintenanceWorkOrderParameters,
        RescheduleProductionParameters,
        ChangeProductionPlanParameters,
        UpdateSupplierOrderParameters,
        EscalateIncidentParameters,
        NotifyStakeholderParameters,
        UpdateSLAPriorityParameters,
        ACTION_PARAMETER_SCHEMAS,
    )


@dataclass
class ActionDefinition:
    """Specification metadata for a registered action type."""
    action_type: ActionType
    version: str
    parameter_schema: type[BaseActionParameters]
    allowed_resource_types: Set[ResourceType]
    default_risk: RiskLevel
    rollback_capability: RollbackCapability
    description: str


class ActionRegistry:
    """
    Centralized Action Registry.
    Determines action schema binding, target compatibility, and risk classification.
    """
    def __init__(self):
        self._registry: Dict[str, ActionDefinition] = {}
        self._bootstrap_defaults()

    def _make_key(self, action_type: ActionType, version: str) -> str:
        return f"{action_type.value}:{version}"

    def register(
        self,
        action_type: ActionType,
        version: str,
        parameter_schema: type[BaseActionParameters],
        allowed_resource_types: Set[ResourceType],
        default_risk: RiskLevel,
        rollback_capability: RollbackCapability,
        description: str
    ) -> None:
        """Registers a new or versioned action definition."""
        key = self._make_key(action_type, version)
        self._registry[key] = ActionDefinition(
            action_type=action_type,
            version=version,
            parameter_schema=parameter_schema,
            allowed_resource_types=allowed_resource_types,
            default_risk=default_risk,
            rollback_capability=rollback_capability,
            description=description
        )

    def get_definition(self, action_type: ActionType, version: str = "1.0") -> Optional[ActionDefinition]:
        """Retrieves definition for given action type and version."""
        key = self._make_key(action_type, version)
        return self._registry.get(key)

    def list_supported_actions(self) -> List[Dict[str, Any]]:
        """Returns catalog metadata for all registered actions."""
        catalog = []
        for defn in self._registry.values():
            catalog.append({
                "action_type": defn.action_type.value,
                "version": defn.version,
                "allowed_resource_types": [r.value for r in defn.allowed_resource_types],
                "default_risk": defn.default_risk.value,
                "rollback_capability": defn.rollback_capability.value,
                "description": defn.description
            })
        return catalog

    def list_definitions(self) -> List[ActionDefinition]:
        """Returns all registered ActionDefinition objects."""
        return list(self._registry.values())

    def classify_risk(
        self,
        action_type: ActionType,
        target: Optional[Any] = None,
        parameters: Optional[Dict[str, Any]] = None,
        cost_estimate: Optional[Any] = None,
        estimated_cost: Optional[float] = None,
        data_mode: str = "REAL"
    ) -> RiskLevel:
        """
        Calculates authoritative deterministic risk level.
        Does NOT rely solely on LLM self-reporting.
        """
        # Simulation actions are bounded strictly to LOW
        if str(data_mode).upper() == "SIMULATION":
            return RiskLevel.LOW

        defn = self.get_definition(action_type)
        base_risk = defn.default_risk if defn else RiskLevel.MEDIUM
        params = parameters or {}

        # Resolve cost
        cost_val = None
        if cost_estimate is not None:
            if hasattr(cost_estimate, "value"):
                cost_val = cost_estimate.value
            elif isinstance(cost_estimate, dict):
                cost_val = cost_estimate.get("value")
            elif isinstance(cost_estimate, (int, float)):
                cost_val = float(cost_estimate)
        elif estimated_cost is not None:
            cost_val = float(estimated_cost)

        # High financial threshold escalation
        if cost_val is not None:
            if cost_val >= 50000:
                return RiskLevel.CRITICAL
            elif cost_val >= 10000:
                if base_risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
                    base_risk = RiskLevel.HIGH

        # Critical machine / severity / priority escalation
        sev = str(params.get("severity", "")).upper()
        prio = str(params.get("priority", "")).upper()
        if sev == "CRITICAL" or prio == "CRITICAL":
            if base_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                return RiskLevel.CRITICAL
            else:
                base_risk = RiskLevel.HIGH

        # High parameter quantity thresholds
        qty = params.get("quantity") or params.get("target_units")
        if qty and isinstance(qty, (int, float)) and qty > 10000:
            if base_risk == RiskLevel.LOW:
                base_risk = RiskLevel.MEDIUM

        # Schedule maintenance duration escalation (> 8 hours)
        duration = params.get("estimated_duration_minutes")
        if duration and isinstance(duration, (int, float)) and duration > 480:
            base_risk = RiskLevel.HIGH

        return base_risk

    def _bootstrap_defaults(self):
        """Pre-populates registry with all 11 core industrial action types."""
        self.register(
            action_type=ActionType.ADJUST_REORDER_POINT,
            version="1.0",
            parameter_schema=AdjustReorderPointParameters,
            allowed_resource_types={ResourceType.SKU, ResourceType.INVENTORY_ITEM, ResourceType.PRODUCT},
            default_risk=RiskLevel.LOW,
            rollback_capability=RollbackCapability.REVERSIBLE,
            description="Adjusts target safety stock reorder threshold for a warehouse SKU."
        )

        self.register(
            action_type=ActionType.REORDER_INVENTORY,
            version="1.0",
            parameter_schema=ReorderInventoryParameters,
            allowed_resource_types={ResourceType.SKU, ResourceType.INVENTORY_ITEM, ResourceType.SUPPLIER},
            default_risk=RiskLevel.MEDIUM,
            rollback_capability=RollbackCapability.PARTIALLY_REVERSIBLE,
            description="Generates an automated inventory replenishment order to an approved supplier."
        )

        self.register(
            action_type=ActionType.MOVE_INVENTORY,
            version="1.0",
            parameter_schema=MoveInventoryParameters,
            allowed_resource_types={ResourceType.SKU, ResourceType.INVENTORY_ITEM, ResourceType.WAREHOUSE},
            default_risk=RiskLevel.LOW,
            rollback_capability=RollbackCapability.REVERSIBLE,
            description="Transfers inventory units between operational warehouse facilities."
        )

        self.register(
            action_type=ActionType.SCHEDULE_MAINTENANCE,
            version="1.0",
            parameter_schema=ScheduleMaintenanceParameters,
            allowed_resource_types={ResourceType.MACHINE, ResourceType.PRODUCTION_LINE, ResourceType.SENSOR},
            default_risk=RiskLevel.MEDIUM,
            rollback_capability=RollbackCapability.REVERSIBLE,
            description="Schedules planned maintenance downtime for factory industrial machinery."
        )

        self.register(
            action_type=ActionType.CREATE_MAINTENANCE_WORK_ORDER,
            version="1.0",
            parameter_schema=CreateMaintenanceWorkOrderParameters,
            allowed_resource_types={ResourceType.MACHINE, ResourceType.PRODUCTION_LINE, ResourceType.MAINTENANCE_RECORD},
            default_risk=RiskLevel.LOW,
            rollback_capability=RollbackCapability.REVERSIBLE,
            description="Dispatches a prioritized maintenance work order ticket to plant engineering."
        )

        self.register(
            action_type=ActionType.RESCHEDULE_PRODUCTION,
            version="1.0",
            parameter_schema=RescheduleProductionParameters,
            allowed_resource_types={ResourceType.PRODUCTION_LINE, ResourceType.PLANT, ResourceType.PRODUCTION_PLAN},
            default_risk=RiskLevel.HIGH,
            rollback_capability=RollbackCapability.PARTIALLY_REVERSIBLE,
            description="Modifies factory shift allocations and operational line throughput."
        )

        self.register(
            action_type=ActionType.CHANGE_PRODUCTION_PLAN,
            version="1.0",
            parameter_schema=ChangeProductionPlanParameters,
            allowed_resource_types={ResourceType.PRODUCTION_PLAN, ResourceType.PRODUCT, ResourceType.PRODUCTION_LINE},
            default_risk=RiskLevel.CRITICAL,
            rollback_capability=RollbackCapability.PARTIALLY_REVERSIBLE,
            description="Revises master production schedule target output quantities."
        )

        self.register(
            action_type=ActionType.UPDATE_SUPPLIER_ORDER,
            version="1.0",
            parameter_schema=UpdateSupplierOrderParameters,
            allowed_resource_types={ResourceType.ORDER, ResourceType.SUPPLIER},
            default_risk=RiskLevel.MEDIUM,
            rollback_capability=RollbackCapability.PARTIALLY_REVERSIBLE,
            description="Requests delivery window adjustment for an active vendor purchase order."
        )

        self.register(
            action_type=ActionType.ESCALATE_INCIDENT,
            version="1.0",
            parameter_schema=EscalateIncidentParameters,
            allowed_resource_types={ResourceType.INCIDENT, ResourceType.PLANT},
            default_risk=RiskLevel.LOW,
            rollback_capability=RollbackCapability.IRREVERSIBLE,
            description="Elevates industrial plant anomaly severity to executive incident response."
        )

        self.register(
            action_type=ActionType.NOTIFY_STAKEHOLDER,
            version="1.0",
            parameter_schema=NotifyStakeholderParameters,
            allowed_resource_types={ResourceType.CUSTOMER, ResourceType.PLANT, ResourceType.INCIDENT},
            default_risk=RiskLevel.LOW,
            rollback_capability=RollbackCapability.IRREVERSIBLE,
            description="Dispatches operational bulletin alert to designated personnel."
        )

        self.register(
            action_type=ActionType.UPDATE_SLA_PRIORITY,
            version="1.0",
            parameter_schema=UpdateSLAPriorityParameters,
            allowed_resource_types={ResourceType.SLA, ResourceType.CUSTOMER, ResourceType.ORDER},
            default_risk=RiskLevel.MEDIUM,
            rollback_capability=RollbackCapability.REVERSIBLE,
            description="Adjusts contractual service delivery response urgency."
        )


# Global singleton instance
action_registry = ActionRegistry()
