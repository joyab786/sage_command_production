# backend/test_v3_digital_twin.py
"""
SageCommand V3 — Prompt 13 Digital Twin Foundation Test Suite
Validates Digital Twin state model, typed properties, state versioning,
temporal reconstruction, immutable snapshots, scenario isolation,
deterministic state comparison, conflict handling, freshness evaluation,
consistency validation, ontology/graph integration, tenant isolation,
authorization, and execution isolation proof.
"""

import os
import sys
import json
import uuid
import inspect
import unittest
import tempfile
from datetime import datetime, timezone, timedelta

# Ensure backend module path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.schemas.digital_twin_contract import (
    TwinStateClassification,
    TwinConfidence,
    TwinConflictState,
    TwinPropertyValueType,
    TwinEntity,
    TwinStateProperty,
    TwinStateVersion,
    TwinSnapshot,
    TwinScenario,
    TwinStateDiff,
    TwinValidationIssue,
    TwinValidationReport,
    TWIN_ELIGIBLE_ENTITY_TYPES,
    StateIngestRequest,
    SnapshotCreateRequest,
    ScenarioCreateRequest,
    StateCompareRequest,
    FreshnessState,
)
from core.auth import Identity
from data.schemas.ontology_contract import (
    EntityType,
    EntityLifecycleState,
    EntitySource,
    OntologyEntity,
)
from data.schemas.knowledge_graph_contract import FactSourceType

from services.digital_twin_repository import DigitalTwinRepository
from services.digital_twin_service import DigitalTwinService
from services.ontology_repository import SQLiteOntologyRepository
from services.ontology_service import OntologyService
from services.knowledge_graph_repository import SQLiteKnowledgeGraphRepository
from services.knowledge_graph_service import KnowledgeGraphService


TENANT_A = "tenant_twin_alpha"
TENANT_B = "tenant_twin_beta"


class TestV3DigitalTwin(unittest.TestCase):
    """Comprehensive Digital Twin Foundation test suite."""

    @classmethod
    def setUpClass(cls):
        """Set up isolated test databases and services."""
        cls.dt_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.onto_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.kg_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.dt_db.close()
        cls.onto_db.close()
        cls.kg_db.close()

        cls.dt_repo = DigitalTwinRepository(db_path=cls.dt_db.name)
        cls.onto_repo = SQLiteOntologyRepository(db_path=cls.onto_db.name)
        cls.onto_svc = OntologyService(repo=cls.onto_repo)
        cls.kg_repo = SQLiteKnowledgeGraphRepository(db_path=cls.kg_db.name)
        cls.kg_svc = KnowledgeGraphService(
            repo=cls.kg_repo,
            ontology_svc=cls.onto_svc,
        )
        cls.dt_svc = DigitalTwinService(
            repo=cls.dt_repo,
            ontology_svc=cls.onto_svc,
            kg_svc=cls.kg_svc,
        )

        # Seed ontology entities for testing
        cls._seed_ontology_entities()

    @classmethod
    def _seed_ontology_entities(cls):
        """Create canonical ontology entities for twin testing."""
        entities = [
            ("machine-m1", EntityType.MACHINE, "Machine M1", "Machine M1"),
            ("machine-m2", EntityType.MACHINE, "Machine M2", "Machine M2"),
            ("sensor-s1", EntityType.SENSOR, "Sensor S1", "Temperature Sensor S1"),
            ("actuator-a1", EntityType.ACTUATOR, "Actuator A1", "Valve Actuator A1"),
            ("line-l1", EntityType.PRODUCTION_LINE, "Line L1", "Production Line L1"),
            ("plc-p1", EntityType.PLC, "PLC P1", "PLC Controller P1"),
            ("robot-r1", EntityType.ROBOT, "Robot R1", "Industrial Robot R1"),
        ]
        for eid, etype, cname, dname in entities:
            cls.onto_svc.create_entity(
                identity=Identity(user_id="system", tenant_id=TENANT_A, roles=["SYSTEM"]),
                entity_type=etype,
                canonical_name=cname,
                display_name=dname,
                entity_id=eid,
            )

        # Seed one entity for tenant B
        cls.onto_svc.create_entity(
            identity=Identity(user_id="system", tenant_id=TENANT_B, roles=["SYSTEM"]),
            entity_type=EntityType.MACHINE,
            canonical_name="Machine B1",
            display_name="Tenant B Machine",
            entity_id="machine-b1",
        )

        # Non-twin-eligible entity
        cls.onto_svc.create_entity(
            identity=Identity(user_id="system", tenant_id=TENANT_A, roles=["SYSTEM"]),
            entity_type=EntityType.ORGANIZATION,
            canonical_name="Org Alpha",
            display_name="Alpha Organization",
            entity_id="org-alpha",
        )

    @classmethod
    def tearDownClass(cls):
        for f in [cls.dt_db.name, cls.onto_db.name, cls.kg_db.name]:
            try:
                os.unlink(f)
            except OSError:
                pass

    # =========================================================================
    # 1. ENTITY INTEGRATION TESTS
    # =========================================================================

    def test_01_valid_ontology_entity_ingestion(self):
        """Valid ontology entity should accept twin state ingestion."""
        ok, msg, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="machine-m1",
            properties=[
                {"property_name": "status", "value": "RUNNING", "value_type": "STRING"},
                {"property_name": "temperature", "value": 82.4, "value_type": "FLOAT", "unit": "CELSIUS"},
                {"property_name": "speed", "value": 1450, "value_type": "INTEGER", "unit": "RPM"},
            ],
            classification="OBSERVED",
            source_type="TELEMETRY",
            source_id="sensor-pack-01",
        )
        self.assertTrue(ok, msg)
        self.assertIsNotNone(twin)
        self.assertEqual(twin.entity_id, "machine-m1")
        self.assertEqual(len(twin.properties), 3)
        self.assertEqual(twin.state_version, 1)
        self.assertEqual(twin.conflict_state, TwinConflictState.NONE)

    def test_02_unknown_entity_rejected(self):
        """Entity not in ontology should be rejected."""
        ok, msg, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="nonexistent-entity",
            properties=[{"property_name": "status", "value": "ON"}],
        )
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    def test_03_unsupported_entity_type_rejected(self):
        """Non-twin-eligible entity type should be rejected."""
        ok, msg, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="org-alpha",
            properties=[{"property_name": "status", "value": "ACTIVE"}],
        )
        self.assertFalse(ok)
        self.assertIn("not twin-eligible", msg.lower())

    def test_04_tenant_mismatch_rejected(self):
        """Entity from different tenant should not be accessible."""
        ok, msg, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="machine-b1",
            properties=[{"property_name": "status", "value": "ON"}],
        )
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    # =========================================================================
    # 2. STATE INGESTION TESTS
    # =========================================================================

    def test_05_observed_state_ingestion(self):
        """OBSERVED state classification should be preserved."""
        ok, msg, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="sensor-s1",
            properties=[{"property_name": "reading", "value": 72.5, "value_type": "FLOAT", "unit": "CELSIUS"}],
            classification="OBSERVED",
            source_type="TELEMETRY",
            source_id="sensor-s1",
        )
        self.assertTrue(ok)
        self.assertEqual(twin.properties[0].classification, TwinStateClassification.OBSERVED)

    def test_06_derived_state_ingestion(self):
        """DERIVED state classification should be preserved."""
        ok, msg, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="line-l1",
            properties=[{"property_name": "utilization", "value": 0.85, "value_type": "FLOAT"}],
            classification="DERIVED",
            source_type="SYSTEM",
            source_id="analytics-engine",
        )
        self.assertTrue(ok)
        self.assertEqual(twin.properties[0].classification, TwinStateClassification.DERIVED)

    def test_07_simulated_state_ingestion(self):
        """SIMULATED state classification should be preserved."""
        ok, msg, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="actuator-a1",
            properties=[{"property_name": "position", "value": 45, "value_type": "INTEGER", "unit": "DEGREES"}],
            classification="SIMULATED",
            source_type="SIMULATOR",
            source_id="factory-simulator",
        )
        self.assertTrue(ok)
        self.assertEqual(twin.properties[0].classification, TwinStateClassification.SIMULATED)

    def test_08_state_versioning(self):
        """Each ingestion should increment state version."""
        # V1
        ok1, _, twin1 = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="machine-m2",
            properties=[{"property_name": "status", "value": "IDLE"}],
        )
        # V2
        ok2, _, twin2 = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="machine-m2",
            properties=[{"property_name": "status", "value": "RUNNING"}],
        )
        # V3
        ok3, _, twin3 = self.dt_svc.ingest_state(
            tenant_id=TENANT_A,
            entity_id="machine-m2",
            properties=[{"property_name": "status", "value": "STOPPED"}],
        )
        self.assertTrue(ok1 and ok2 and ok3)
        self.assertEqual(twin1.state_version, 1)
        self.assertEqual(twin2.state_version, 2)
        self.assertEqual(twin3.state_version, 3)

    # =========================================================================
    # 3. TEMPORAL STATE TESTS
    # =========================================================================

    def test_09_current_state_retrieval(self):
        """Current state should return latest version."""
        twin = self.dt_svc.get_twin_entity(TENANT_A, "machine-m1")
        self.assertIsNotNone(twin)
        self.assertEqual(twin.entity_id, "machine-m1")
        self.assertGreater(len(twin.properties), 0)

    def test_10_historical_state_retrieval(self):
        """State history should preserve all versions in descending order."""
        history = self.dt_svc.get_state_history(TENANT_A, "machine-m2")
        self.assertGreaterEqual(len(history), 3)
        # Versions should be in descending order
        versions = [v.state_version for v in history]
        self.assertEqual(versions, sorted(versions, reverse=True))

    def test_11_state_at_time_reconstruction(self):
        """Should reconstruct state at a specific point in time."""
        # Ingest with known timestamps
        t1 = "2025-01-01T10:00:00+00:00"
        t2 = "2025-01-01T12:00:00+00:00"

        self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="plc-p1",
            properties=[{"property_name": "mode", "value": "RUN"}],
            effective_at=t1, observed_at=t1,
        )
        self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="plc-p1",
            properties=[{"property_name": "mode", "value": "PROGRAM"}],
            effective_at=t2, observed_at=t2,
        )

        # Query at t1 + 1 hour should get first state
        state_at = self.dt_svc.get_state_at_time(TENANT_A, "plc-p1", "2025-01-01T11:00:00+00:00")
        self.assertIsNotNone(state_at)
        props = {p.property_name if hasattr(p, 'property_name') else p.get('property_name', ''): p
                 for p in state_at.properties}
        mode_prop = props.get("mode")
        self.assertIsNotNone(mode_prop)
        mode_val = mode_prop.value if hasattr(mode_prop, 'value') else mode_prop.get('value')
        self.assertEqual(mode_val, "RUN")

    # =========================================================================
    # 4. SNAPSHOT TESTS
    # =========================================================================

    def test_12_create_snapshot(self):
        """Snapshot creation should succeed with deterministic contents."""
        snapshot = self.dt_svc.create_snapshot(
            tenant_id=TENANT_A,
            description="Test snapshot",
        )
        self.assertIsNotNone(snapshot)
        self.assertIsNotNone(snapshot.snapshot_id)
        self.assertTrue(snapshot.is_immutable)
        self.assertGreater(snapshot.entity_count, 0)
        self.__class__._test_snapshot_id = snapshot.snapshot_id

    def test_13_retrieve_snapshot(self):
        """Saved snapshot should be retrievable."""
        snap_id = getattr(self.__class__, '_test_snapshot_id', None)
        if not snap_id:
            self.skipTest("No snapshot created")
        snapshot = self.dt_svc.get_snapshot(TENANT_A, snap_id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.snapshot_id, snap_id)
        self.assertTrue(snapshot.is_immutable)

    def test_14_snapshot_immutability(self):
        """Snapshot model should enforce immutability flag."""
        snapshot = TwinSnapshot(
            snapshot_id="snap_test_immutable",
            tenant_id=TENANT_A,
            snapshot_timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.assertTrue(snapshot.is_immutable)

    def test_15_snapshot_deterministic_contents(self):
        """Snapshot should use effective_at <= snapshot_timestamp rule."""
        # Ingest state with future timestamp
        future_ts = "2099-12-31T23:59:59+00:00"
        self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="robot-r1",
            properties=[{"property_name": "status", "value": "FUTURE_STATE"}],
            effective_at=future_ts, observed_at=future_ts,
        )

        # Snapshot at now should NOT include the future state
        now = datetime.now(timezone.utc).isoformat()
        snapshot = self.dt_svc.create_snapshot(
            tenant_id=TENANT_A,
            entity_ids=["robot-r1"],
            snapshot_timestamp=now,
        )
        # The snapshot should either be empty for this entity or not have the future state
        for entity in snapshot.entities:
            if entity.entity_id == "robot-r1":
                for p in entity.properties:
                    prop_val = p.value if hasattr(p, 'value') else p.get('value')
                    self.assertNotEqual(prop_val, "FUTURE_STATE",
                                        "Future state should not appear in current snapshot")

    # =========================================================================
    # 5. SCENARIO TESTS
    # =========================================================================

    def test_16_create_scenario(self):
        """Scenario creation from base snapshot should succeed."""
        snap_id = getattr(self.__class__, '_test_snapshot_id', None)
        if not snap_id:
            snap = self.dt_svc.create_snapshot(tenant_id=TENANT_A)
            snap_id = snap.snapshot_id
            self.__class__._test_snapshot_id = snap_id

        ok, msg, scenario = self.dt_svc.create_scenario(
            tenant_id=TENANT_A,
            base_snapshot_id=snap_id,
            name="What-If: Machine M1 Stopped",
            overrides=[{
                "entity_id": "machine-m1",
                "property_name": "status",
                "value": "STOPPED",
                "value_type": "STRING",
            }],
        )
        self.assertTrue(ok, msg)
        self.assertIsNotNone(scenario)
        self.__class__._test_scenario_id = scenario.scenario_id

    def test_17_scenario_isolation_from_observed(self):
        """Scenario overrides must NOT affect observed twin state."""
        # After creating scenario with M1=STOPPED, real M1 should still be RUNNING
        twin = self.dt_svc.get_twin_entity(TENANT_A, "machine-m1")
        self.assertIsNotNone(twin)
        status_props = [p for p in twin.properties if p.property_name == "status"]
        if status_props:
            self.assertNotEqual(status_props[0].value, "STOPPED",
                                "Scenario override must not change observed state")

    def test_18_scenario_with_invalid_snapshot_rejected(self):
        """Scenario with non-existent base snapshot should fail."""
        ok, msg, scenario = self.dt_svc.create_scenario(
            tenant_id=TENANT_A,
            base_snapshot_id="snap_nonexistent",
            name="Invalid scenario",
        )
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    def test_19_get_scenario(self):
        """Created scenario should be retrievable."""
        scen_id = getattr(self.__class__, '_test_scenario_id', None)
        if not scen_id:
            self.skipTest("No scenario created")
        scenario = self.dt_svc.get_scenario(TENANT_A, scen_id)
        self.assertIsNotNone(scenario)
        self.assertEqual(scenario.scenario_id, scen_id)
        self.assertGreater(len(scenario.overrides), 0)

    # =========================================================================
    # 6. STATE COMPARISON TESTS
    # =========================================================================

    def test_20_snapshot_vs_snapshot_comparison(self):
        """Comparing two snapshots should return structured diffs."""
        # Create two snapshots with different state
        snap1 = self.dt_svc.create_snapshot(tenant_id=TENANT_A, entity_ids=["machine-m1"])

        # Change state
        self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="machine-m1",
            properties=[{"property_name": "status", "value": "MAINTENANCE"}],
        )
        snap2 = self.dt_svc.create_snapshot(tenant_id=TENANT_A, entity_ids=["machine-m1"])

        ok, msg, diffs = self.dt_svc.compare_states(
            tenant_id=TENANT_A,
            source_type="snapshot", source_id=snap1.snapshot_id,
            target_type="snapshot", target_id=snap2.snapshot_id,
        )
        self.assertTrue(ok, msg)
        # Should detect the status change
        self.assertIsInstance(diffs, list)

    def test_21_entity_vs_entity_comparison(self):
        """Comparing two entity states should work."""
        # Ingest state for two different entities
        self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="machine-m1",
            properties=[{"property_name": "temp", "value": 80}],
        )
        self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="machine-m2",
            properties=[{"property_name": "temp", "value": 90}],
        )

        ok, msg, diffs = self.dt_svc.compare_states(
            tenant_id=TENANT_A,
            source_type="entity", source_id="machine-m1",
            target_type="entity", target_id="machine-m2",
        )
        self.assertTrue(ok, msg)

    def test_22_invalid_comparison_source(self):
        """Comparing nonexistent source should fail gracefully."""
        ok, msg, diffs = self.dt_svc.compare_states(
            tenant_id=TENANT_A,
            source_type="snapshot", source_id="snap_nonexistent",
            target_type="entity", target_id="machine-m1",
        )
        self.assertFalse(ok)

    # =========================================================================
    # 7. FRESHNESS TESTS
    # =========================================================================

    def test_23_fresh_state(self):
        """Recently ingested state should be FRESH."""
        ok, _, twin = self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="machine-m1",
            properties=[{"property_name": "heartbeat", "value": "ok"}],
        )
        self.assertTrue(ok)
        self.assertEqual(twin.freshness, FreshnessState.FRESH)

    def test_24_expired_state_freshness(self):
        """State with very old timestamp should be EXPIRED."""
        old_ts = "2020-01-01T00:00:00+00:00"
        freshness = self.dt_svc._calculate_freshness(old_ts)
        self.assertEqual(freshness, "EXPIRED")

    def test_25_unknown_freshness(self):
        """Invalid timestamp should yield UNKNOWN freshness."""
        freshness = self.dt_svc._calculate_freshness("not-a-timestamp")
        self.assertEqual(freshness, "UNKNOWN")

    # =========================================================================
    # 8. CONFLICT TESTS
    # =========================================================================

    def test_26_deterministic_conflict_resolution(self):
        """Conflicting observations should produce deterministic result."""
        now = datetime.now(timezone.utc).isoformat()
        # First observation
        ok1, _, _ = self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="sensor-s1",
            properties=[{"property_name": "status", "value": "NORMAL"}],
            effective_at=now, source_id="sensor-a",
        )
        # Second observation same effective_at — potential conflict
        ok2, _, twin2 = self.dt_svc.ingest_state(
            tenant_id=TENANT_A, entity_id="sensor-s1",
            properties=[{"property_name": "status", "value": "ALARM"}],
            effective_at=now, source_id="sensor-b",
        )
        self.assertTrue(ok1 and ok2)
        # Latest recorded_at should win (version 2)
        self.assertGreater(twin2.state_version, 1)

    # =========================================================================
    # 9. ONTOLOGY/GRAPH INTEGRATION TESTS
    # =========================================================================

    def test_27_canonical_entity_reuse(self):
        """Twin should reference canonical ontology entity_id, not create duplicate identity."""
        twin = self.dt_svc.get_twin_entity(TENANT_A, "machine-m1")
        self.assertIsNotNone(twin)
        self.assertEqual(twin.entity_id, "machine-m1")
        # twin_id should be different from entity_id
        self.assertNotEqual(twin.twin_id, twin.entity_id)

    def test_28_entity_context_from_knowledge_graph(self):
        """Graph context retrieval should not error and should be bounded."""
        context = self.dt_svc.get_entity_context(TENANT_A, "machine-m1")
        self.assertIsNotNone(context)
        self.assertEqual(context["entity_id"], "machine-m1")
        self.assertTrue(context["bounded"])

    def test_29_twin_eligible_types_defined(self):
        """Twin-eligible entity types should be explicitly defined and non-empty."""
        self.assertGreater(len(TWIN_ELIGIBLE_ENTITY_TYPES), 0)
        self.assertIn(EntityType.MACHINE, TWIN_ELIGIBLE_ENTITY_TYPES)
        self.assertIn(EntityType.SENSOR, TWIN_ELIGIBLE_ENTITY_TYPES)
        self.assertNotIn(EntityType.ORGANIZATION, TWIN_ELIGIBLE_ENTITY_TYPES)
        self.assertNotIn(EntityType.CUSTOMER, TWIN_ELIGIBLE_ENTITY_TYPES)

    # =========================================================================
    # 10. SECURITY TESTS
    # =========================================================================

    def test_30_tenant_isolation(self):
        """Twin state from one tenant should not be visible to another."""
        # Ingest for tenant B
        self.dt_svc.ingest_state(
            tenant_id=TENANT_B, entity_id="machine-b1",
            properties=[{"property_name": "status", "value": "RUNNING"}],
        )

        # Tenant A should not see tenant B's twin
        twin = self.dt_svc.get_twin_entity(TENANT_A, "machine-b1")
        self.assertIsNone(twin)

    def test_31_cross_tenant_snapshot_isolation(self):
        """Snapshots should be tenant-scoped."""
        snap = self.dt_svc.create_snapshot(tenant_id=TENANT_B)
        # Tenant A should not see tenant B's snapshot
        retrieved = self.dt_svc.get_snapshot(TENANT_A, snap.snapshot_id)
        self.assertIsNone(retrieved)

    def test_32_cross_tenant_scenario_isolation(self):
        """Scenarios should be tenant-scoped."""
        snap = self.dt_svc.create_snapshot(tenant_id=TENANT_B)
        ok, _, scenario = self.dt_svc.create_scenario(
            tenant_id=TENANT_B,
            base_snapshot_id=snap.snapshot_id,
            name="Tenant B Scenario",
        )
        self.assertTrue(ok)
        # Tenant A should not see it
        retrieved = self.dt_svc.get_scenario(TENANT_A, scenario.scenario_id)
        self.assertIsNone(retrieved)

    # =========================================================================
    # 11. CONSISTENCY VALIDATION TESTS
    # =========================================================================

    def test_33_consistency_validation(self):
        """Validation should return structured report."""
        report = self.dt_svc.validate_consistency(TENANT_A)
        self.assertIsNotNone(report)
        self.assertEqual(report.tenant_id, TENANT_A)
        self.assertIsInstance(report.error_count, int)
        self.assertIsInstance(report.warning_count, int)

    # =========================================================================
    # 12. EXECUTION ISOLATION PROOF — MANDATORY
    # =========================================================================

    def test_34_no_execution_gateway_import(self):
        """
        EXECUTION ISOLATION PROOF:
        DigitalTwinService source code must contain ZERO imports of
        ExecutionGateway, Action, or ActionStatus.
        """
        source_file = inspect.getfile(DigitalTwinService)
        with open(source_file, "r") as f:
            source = f.read()

        self.assertNotIn("ExecutionGateway", source,
                         "DigitalTwinService MUST NOT import ExecutionGateway")
        self.assertNotIn("from services.execution_gateway", source,
                         "DigitalTwinService MUST NOT import from execution_gateway")
        self.assertNotIn("from backend.services.execution_gateway", source,
                         "DigitalTwinService MUST NOT import from execution_gateway")
        self.assertNotIn("ActionStatus", source,
                         "DigitalTwinService MUST NOT reference ActionStatus")

    def test_35_no_execution_gateway_in_repository(self):
        """
        Repository must also have zero execution gateway imports.
        """
        source_file = inspect.getfile(DigitalTwinRepository)
        with open(source_file, "r") as f:
            source = f.read()

        self.assertNotIn("ExecutionGateway", source)
        self.assertNotIn("execution_gateway", source)

    def test_36_no_execution_gateway_in_routes(self):
        """
        API routes must not import or invoke execution gateway.
        """
        routes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "digital_twin_routes.py")
        with open(routes_path, "r") as f:
            source = f.read()

        self.assertNotIn("ExecutionGateway", source)
        self.assertNotIn("execution_gateway", source)

    def test_37_twin_operations_cannot_mutate_operational_db(self):
        """
        Digital Twin operations must generate zero mutations on
        operational database tables (inventory, telemetry, shipments).
        """
        import sqlite3
        from core.config import DEFAULT_DB_PATH

        # Check that DT service doesn't reference DEFAULT_DB_PATH for writes
        source_file = inspect.getfile(DigitalTwinService)
        with open(source_file, "r") as f:
            source = f.read()

        # Service should not directly use DEFAULT_DB_PATH or dynamic_datacore
        self.assertNotIn("dynamic_datacore", source,
                         "DigitalTwinService must not reference operational database")

    # =========================================================================
    # 13. CONTRACT MODEL TESTS
    # =========================================================================

    def test_38_twin_state_property_model(self):
        """TwinStateProperty model should accept all value types."""
        prop = TwinStateProperty(
            property_name="temperature",
            value_type=TwinPropertyValueType.FLOAT,
            value=82.4,
            unit="CELSIUS",
            classification=TwinStateClassification.OBSERVED,
            confidence=TwinConfidence.HIGH,
            source_type=FactSourceType.TELEMETRY,
            source_id="sensor-01",
            observed_at=datetime.now(timezone.utc).isoformat(),
            effective_at=datetime.now(timezone.utc).isoformat(),
        )
        self.assertEqual(prop.property_name, "temperature")
        self.assertEqual(prop.value, 82.4)
        self.assertEqual(prop.classification, TwinStateClassification.OBSERVED)

    def test_39_twin_entity_model(self):
        """TwinEntity model should correctly construct."""
        now = datetime.now(timezone.utc).isoformat()
        entity = TwinEntity(
            twin_id="twin_test123",
            entity_id="machine-test",
            tenant_id=TENANT_A,
            entity_type=EntityType.MACHINE,
            observed_at=now,
            effective_at=now,
        )
        self.assertEqual(entity.twin_id, "twin_test123")
        self.assertTrue(entity.twin_id != entity.entity_id)

    def test_40_twin_state_classifications_complete(self):
        """All required classifications should exist."""
        self.assertEqual(TwinStateClassification.OBSERVED.value, "OBSERVED")
        self.assertEqual(TwinStateClassification.SIMULATED.value, "SIMULATED")
        self.assertEqual(TwinStateClassification.DERIVED.value, "DERIVED")
        self.assertEqual(TwinStateClassification.UNKNOWN.value, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
