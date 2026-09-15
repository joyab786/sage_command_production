import sys
import os
import unittest

# Ensure sys.path includes both backend directory and parent directory for root/module imports
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from data.schemas.provenance import DataProvenance, DataSourceType
    from data.schemas.event import IndustrialEvent
    from data.schemas.action import StructuredAction, ActionTarget
    from data.schemas.incident import IncidentObject, IncidentState, ActionState
    from data.schemas.mission import MissionObject
    from data.schemas.decision import DecisionObject
    from data.schemas.domain import (
        Plant, ProductionLine, Machine, Sensor, SKU, InventoryItem, Supplier, Customer, Anomaly, Risk
    )
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.provenance import DataProvenance, DataSourceType
    from backend.data.schemas.event import IndustrialEvent
    from backend.data.schemas.action import StructuredAction, ActionTarget
    from backend.data.schemas.incident import IncidentObject, IncidentState, ActionState
    from backend.data.schemas.mission import MissionObject
    from backend.data.schemas.decision import DecisionObject
    from backend.data.schemas.domain import (
        Plant, ProductionLine, Machine, Sensor, SKU, InventoryItem, Supplier, Customer, Anomaly, Risk
    )


class TestV3DomainSchemas(unittest.TestCase):

    def test_provenance_schema(self):
        """Verify DataProvenance initialization and default values."""
        prov = DataProvenance(source="PLC-LINE-4", source_type=DataSourceType.REAL_DATA)
        self.assertEqual(prov.source, "PLC-LINE-4")
        self.assertEqual(prov.source_type, DataSourceType.REAL_DATA)
        self.assertEqual(prov.confidence, 1.0)
        self.assertFalse(prov.is_simulated)

    def test_industrial_event_schema(self):
        """Verify IndustrialEvent contract formatting and UUID generation."""
        event = IndustrialEvent(
            event_type="inventory.low_stock",
            source="discovery_agent",
            severity="HIGH",
            entity_type="inventory",
            entity_id="SKU-882",
            payload={"current_quantity": 4}
        )
        self.assertTrue(len(event.event_id) > 10)
        self.assertEqual(event.event_type, "inventory.low_stock")
        self.assertEqual(event.payload["current_quantity"], 4)

    def test_structured_action_schema(self):
        """Verify StructuredAction contract parameters and target definition."""
        action = StructuredAction(
            action_type="REORDER_INVENTORY",
            target=ActionTarget(entity_type="SKU", entity_id="SKU-882"),
            parameters={"quantity": 500, "supplier_id": "SUP-APEX-01"},
            reason="Projected stockout within 4 days",
            risk_level="MEDIUM",
            estimated_cost=1200.0,
            requires_approval=True
        )
        self.assertEqual(action.action_type, "REORDER_INVENTORY")
        self.assertEqual(action.target.entity_id, "SKU-882")
        self.assertTrue(action.requires_approval)

    def test_incident_state_enum(self):
        """Verify IncidentState enum contains required operational lifecycle states."""
        required_states = [
            "DETECTED", "TRIAGED", "ANALYZING", "RECOMMENDATION_READY",
            "AWAITING_APPROVAL", "APPROVED", "REJECTED", "EXECUTING",
            "VERIFYING", "RESOLVED", "FAILED", "ROLLED_BACK"
        ]
        for st in required_states:
            self.assertTrue(hasattr(IncidentState, st), f"Missing incident state: {st}")

    def test_action_state_enum(self):
        """Verify ActionState enum contains required action lifecycle states."""
        required_states = [
            "PROPOSED", "POLICY_REVIEW", "AWAITING_APPROVAL", "APPROVED",
            "EXECUTING", "SUCCEEDED", "FAILED", "ROLLED_BACK"
        ]
        for st in required_states:
            self.assertTrue(hasattr(ActionState, st), f"Missing action state: {st}")

    def test_mission_object(self):
        """Verify MissionObject structure and default values."""
        mission = MissionObject(
            title="Prevent Line 4 Shutdown",
            objective="Maintain Line 4 operation for 24 hours.",
            constraints=["Budget <= $10,000"],
            allowed_actions=["Maintenance", "Inventory reallocation"],
            risk_tolerance="LOW",
            success_criteria=["No unplanned shutdown."]
        )
        self.assertEqual(mission.title, "Prevent Line 4 Shutdown")
        self.assertEqual(mission.risk_tolerance, "LOW")

    def test_decision_object(self):
        """Verify DecisionObject schema fields and contract validation."""
        decision = DecisionObject(
            problem="Thermal sensor pack stock depleted to 4 units",
            objective="Expedite priority restock to prevent line halt",
            strategies=[{"id": "S1", "action": "Expedite restock", "cost": 3500}],
            confidence=0.95,
            risk="HIGH",
            cost=3500.0,
            financial_impact="$3,500 USD"
        )
        self.assertEqual(decision.risk, "HIGH")
        self.assertEqual(decision.confidence, 0.95)
        self.assertEqual(decision.approval_status, "PENDING")

    def test_physical_domain_entities(self):
        """Verify Plant, ProductionLine, Machine, and Sensor domain models."""
        sensor = Sensor(sensor_id="TEMP-01", sensor_type="Temperature", unit="Celsius", current_value=45.2)
        machine = Machine(machine_id="MCH-01", name="Line 1 Motor", category="Actuator", line_id="LINE-01", sensors=[sensor])
        line = ProductionLine(line_id="LINE-01", name="Assembly Alpha", plant_id="PLANT-01", machines=[machine])
        plant = Plant(plant_id="PLANT-01", name="Detroit Gigafactory", location="Detroit, MI", lines=[line])

        self.assertEqual(plant.lines[0].machines[0].sensors[0].sensor_id, "TEMP-01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
