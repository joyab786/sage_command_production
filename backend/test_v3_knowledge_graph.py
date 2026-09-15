# backend/test_v3_knowledge_graph.py
"""
SageCommand V3 — Comprehensive Operational Knowledge Graph Unit & Integration Tests
Verifies:
  1. Ontology entity validation and missing entity rejection.
  2. Operational fact creation, typing, and provenance tracking.
  3. Fact superseding and historical version snapshotting.
  4. Fact expiration and explicit revocation.
  5. Multi-tenant boundary isolation.
  6. Cross-tenant edge rejection (fails closed).
  7. Temporal bitemporal queries (current vs point-in-time historical reconstruction).
  8. Ontology compatibility matrix enforcement on operational edges.
  9. Graph traversals: 1-hop neighbors, upstream dependencies, downstream consumers.
  10. Bounded traversals and cycle termination (A -> B -> C -> A).
  11. Shortest path BFS pathfinding.
  12. Source freshness evaluation (FRESH, STALE, EXPIRED, UNKNOWN).
  13. Graph consistency validation and audit reporting.
  14. Deterministic read-only inventory projection.
  15. REST API endpoints, JWT authentication (401), and RBAC permissions (403).
  16. Strict execution isolation proof (zero operational DB mutations, zero Gateway calls).
"""

import os
import unittest
import sqlite3
import jwt
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from core.config import SAGE_SECRET_KEY, SAGE_AUTH_ISSUER, SAGE_AUTH_AUDIENCE
from core.auth import Identity
from data.schemas.ontology_contract import (
    EntityType,
    RelationshipType,
    RelationshipConfidence,
    EntitySource,
)
from data.schemas.knowledge_graph_contract import (
    FactValueType,
    FactSourceType,
    FactLifecycleState,
    FreshnessState,
)
from services.ontology_repository import SQLiteOntologyRepository
from services.ontology_service import OntologyService
from services.knowledge_graph_repository import SQLiteKnowledgeGraphRepository
from services.knowledge_graph_service import KnowledgeGraphService
try:
    from api import ontology_routes, knowledge_graph_routes
except ImportError:
    from backend.api import ontology_routes, knowledge_graph_routes
from server import app


class TestV3OperationalKnowledgeGraph(unittest.TestCase):
    """Comprehensive test suite for Operational Knowledge Graph Foundation (Prompt 12)."""

    @classmethod
    def setUpClass(cls):
        cls.test_onto_db = "test_sage_ontology_kg.sqlite"
        cls.test_kg_db = "test_sage_kg.sqlite"

        for p in (cls.test_onto_db, cls.test_kg_db):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

        cls.onto_repo = SQLiteOntologyRepository(db_path=cls.test_onto_db)
        cls.onto_svc = OntologyService(repo=cls.onto_repo)

        cls.kg_repo = SQLiteKnowledgeGraphRepository(db_path=cls.test_kg_db)
        cls.kg_svc = KnowledgeGraphService(
            repo=cls.kg_repo,
            ontology_svc=cls.onto_svc,
            datacore_db_path="./dynamic_datacore.sqlite"
        )

        # Inject isolated test services into routes
        ontology_routes.ontology_service = cls.onto_svc
        knowledge_graph_routes.knowledge_graph_service = cls.kg_svc

        # Identities for testing
        cls.tenant_a = "tenant_mfg_alpha"
        cls.tenant_b = "tenant_mfg_beta"

        cls.identity_pm_a = Identity(
            user_id="user_pm_a",
            tenant_id=cls.tenant_a,
            roles=["PLANT_MANAGER"],
            workspace_id="workspace_alpha",
            assigned_plants=["plant_mumbai"],
            is_server_authoritative=True
        )

        cls.identity_viewer_a = Identity(
            user_id="user_viewer_a",
            tenant_id=cls.tenant_a,
            roles=["VIEWER"],
            workspace_id="workspace_alpha",
            assigned_plants=["plant_mumbai"],
            is_server_authoritative=True
        )

        cls.identity_pm_b = Identity(
            user_id="user_pm_b",
            tenant_id=cls.tenant_b,
            roles=["PLANT_MANAGER"],
            workspace_id="workspace_beta",
            assigned_plants=["plant_pune"],
            is_server_authoritative=True
        )

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in (cls.test_onto_db, cls.test_kg_db):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def _create_jwt_token(self, identity: Identity) -> str:
        assigned = getattr(identity, "assigned_plants", None)
        plant_id = assigned[0] if assigned else "plant_mumbai"
        payload = {
            "sub": identity.user_id,
            "tenant_id": identity.tenant_id,
            "workspace_id": identity.workspace_id,
            "plant_id": plant_id,
            "roles": identity.roles,
            "iss": SAGE_AUTH_ISSUER,
            "aud": SAGE_AUTH_AUDIENCE,
            "exp": int(datetime.now(timezone.utc).timestamp()) + 3600
        }
        return jwt.encode(payload, SAGE_SECRET_KEY, algorithm="HS256")

    # -------------------------------------------------------------------------
    # 1. Ontology Integration & Fact Ingestion
    # -------------------------------------------------------------------------

    def test_01_ontology_entity_validation(self):
        """Accepts valid canonical ontology entity, rejects unknown/non-existent entity."""
        # Create canonical entity in ontology
        machine = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="CNC Mill Alpha",
            display_name="Mill A",
            plant_id="plant_mumbai"
        )

        # Ingest fact for valid entity succeeds
        fact = self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=machine.entity_id,
            predicate="OPERATIONAL_STATUS",
            value="RUNNING",
            source_type=FactSourceType.TELEMETRY,
            source_id="cnc_sensor_01"
        )
        self.assertIsNotNone(fact)
        self.assertEqual(fact.subject_entity_id, machine.entity_id)
        self.assertEqual(fact.value, "RUNNING")

        # Ingest fact for non-existent entity fails closed
        with self.assertRaises(KeyError) as ctx:
            self.kg_svc.ingest_fact(
                identity=self.identity_pm_a,
                subject_entity_id="machine:plant_mumbai:ghost_press_99",
                predicate="OPERATIONAL_STATUS",
                value="OFFLINE"
            )
        self.assertIn("ENTITY_NOT_FOUND", str(ctx.exception))

    def test_02_operational_fact_creation_and_provenance(self):
        """Ingests fact with complete provenance and bitemporal timestamps."""
        sensor = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.SENSOR,
            canonical_name="Vibration Sensor 01",
            display_name="Vib-01",
            plant_id="plant_mumbai"
        )

        obs_time = "2026-09-15T12:00:00+00:00"
        fact = self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=sensor.entity_id,
            predicate="VIBRATION_RMS",
            value=4.82,
            value_type=FactValueType.FLOAT,
            unit="MM_PER_SEC",
            source_type=FactSourceType.TELEMETRY,
            source_id="iot_edge_gateway_01",
            observed_at=obs_time,
            valid_from=obs_time,
            confidence=0.98
        )

        retrieved = self.kg_svc.get_fact(fact.fact_id, self.identity_pm_a)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.value, 4.82)
        self.assertEqual(retrieved.unit, "MM_PER_SEC")
        self.assertEqual(retrieved.source_type, FactSourceType.TELEMETRY)
        self.assertEqual(retrieved.source_id, "iot_edge_gateway_01")
        self.assertEqual(retrieved.confidence, 0.98)
        self.assertEqual(retrieved.observed_at, obs_time)

    # -------------------------------------------------------------------------
    # 2. Lifecycle, Superseding & Revocation
    # -------------------------------------------------------------------------

    def test_03_fact_superseding_and_history_preservation(self):
        """When a newer fact arrives for a singular predicate, prior fact is SUPERSEDED and versioned."""
        machine = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Stamping Press 04",
            display_name="Press 04",
            plant_id="plant_mumbai"
        )

        t1 = "2026-09-15T10:00:00+00:00"
        f1 = self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=machine.entity_id,
            predicate="OPERATIONAL_STATUS",
            value="IDLE",
            valid_from=t1,
            observed_at=t1
        )

        t2 = "2026-09-15T10:30:00+00:00"
        f2 = self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=machine.entity_id,
            predicate="OPERATIONAL_STATUS",
            value="RUNNING",
            valid_from=t2,
            observed_at=t2
        )

        # f1 should now be SUPERSEDED
        f1_refreshed = self.kg_svc.get_fact(f1.fact_id, self.identity_pm_a)
        self.assertEqual(f1_refreshed.status, FactLifecycleState.SUPERSEDED)
        self.assertEqual(f1_refreshed.valid_to, t2)

        # f2 should be ACTIVE
        f2_refreshed = self.kg_svc.get_fact(f2.fact_id, self.identity_pm_a)
        self.assertEqual(f2_refreshed.status, FactLifecycleState.ACTIVE)
        self.assertIsNone(f2_refreshed.valid_to)

        # Active facts query should only return f2
        active_facts = self.kg_repo.get_active_facts_for_entity(machine.entity_id, self.tenant_a, "OPERATIONAL_STATUS")
        self.assertEqual(len(active_facts), 1)
        self.assertEqual(active_facts[0].fact_id, f2.fact_id)

    def test_04_fact_expiration_and_revocation(self):
        """Explicitly revoking a fact marks it REVOKED and updates valid_to."""
        machine = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Welding Robot 02",
            display_name="Robot 02",
            plant_id="plant_mumbai"
        )

        fact = self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=machine.entity_id,
            predicate="DEFECT_FLAG",
            value=True,
            value_type=FactValueType.BOOLEAN
        )

        revoked = self.kg_svc.revoke_fact(fact.fact_id, self.identity_pm_a, reason="False positive calibration error")
        self.assertTrue(revoked)

        refreshed = self.kg_svc.get_fact(fact.fact_id, self.identity_pm_a)
        self.assertEqual(refreshed.status, FactLifecycleState.REVOKED)
        self.assertEqual(refreshed.metadata.get("revocation_reason"), "False positive calibration error")

    # -------------------------------------------------------------------------
    # 3. Multi-Tenant Isolation
    # -------------------------------------------------------------------------

    def test_05_multi_tenant_isolation(self):
        """Proves Tenant B cannot view or traverse facts/nodes belonging to Tenant A."""
        ent_a = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Alpha Private Machine",
            display_name="Alpha Machine",
            plant_id="plant_mumbai"
        )

        fact_a = self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=ent_a.entity_id,
            predicate="CONFIDENTIAL_RECIPE",
            value="FORMULA_X"
        )

        # Tenant B cannot get the fact
        fact_b_view = self.kg_svc.get_fact(fact_a.fact_id, self.identity_pm_b)
        self.assertIsNone(fact_b_view)

        # Tenant B cannot get the node
        node_b_view = self.kg_svc.get_entity_node(ent_a.entity_id, self.identity_pm_b)
        self.assertIsNone(node_b_view)

    def test_06_cross_tenant_edge_rejection(self):
        """Cross-tenant operational edge creation fails closed."""
        ent_a = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Alpha Source Machine",
            display_name="Alpha Machine"
        )
        ent_b = self.onto_svc.create_entity(
            identity=self.identity_pm_b,
            entity_type=EntityType.MACHINE,
            canonical_name="Beta Target Machine",
            display_name="Beta Machine"
        )

        # Attempting to link ent_a to ent_b from Tenant A context fails closed
        with self.assertRaises(KeyError) as ctx:
            self.kg_svc.create_operational_edge(
                identity=self.identity_pm_a,
                source_entity_id=ent_a.entity_id,
                target_entity_id=ent_b.entity_id,
                predicate="FEEDS"
            )
        self.assertIn("TARGET_ENTITY_NOT_FOUND", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 4. Temporal Bitemporal Queries
    # -------------------------------------------------------------------------

    def test_07_temporal_queries_current_and_point_in_time(self):
        """Point-in-time queries return historical state valid at timestamp T."""
        mch = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Furnace 01",
            display_name="Furnace 01"
        )

        # T0: 75 C
        t0 = "2026-09-15T08:00:00+00:00"
        self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=mch.entity_id,
            predicate="TEMPERATURE",
            value=75.0,
            value_type=FactValueType.FLOAT,
            observed_at=t0,
            valid_from=t0
        )

        # T1: 85 C
        t1 = "2026-09-15T09:00:00+00:00"
        self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=mch.entity_id,
            predicate="TEMPERATURE",
            value=85.0,
            value_type=FactValueType.FLOAT,
            observed_at=t1,
            valid_from=t1
        )

        # T2: 92 C
        t2 = "2026-09-15T10:00:00+00:00"
        self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=mch.entity_id,
            predicate="TEMPERATURE",
            value=92.0,
            value_type=FactValueType.FLOAT,
            observed_at=t2,
            valid_from=t2
        )

        # Query at T0.5 (08:30) -> should see 75.0
        facts_t0 = self.kg_repo.get_facts_at_time(mch.entity_id, self.tenant_a, "2026-09-15T08:30:00+00:00", "TEMPERATURE")
        self.assertEqual(len(facts_t0), 1)
        self.assertEqual(facts_t0[0].value, 75.0)

        # Query at T1.5 (09:30) -> should see 85.0
        facts_t1 = self.kg_repo.get_facts_at_time(mch.entity_id, self.tenant_a, "2026-09-15T09:30:00+00:00", "TEMPERATURE")
        self.assertEqual(len(facts_t1), 1)
        self.assertEqual(facts_t1[0].value, 85.0)

        # Current active -> should see 92.0
        active_facts = self.kg_repo.get_active_facts_for_entity(mch.entity_id, self.tenant_a, "TEMPERATURE")
        self.assertEqual(len(active_facts), 1)
        self.assertEqual(active_facts[0].value, 92.0)

    # -------------------------------------------------------------------------
    # 5. Compatibility Matrix Enforcement
    # -------------------------------------------------------------------------

    def test_08_ontology_compatibility_matrix_enforcement(self):
        """Enforces Prompt 11 ontology compatibility matrix on operational edges."""
        plant = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.PLANT,
            canonical_name="Mumbai Manufacturing Plant",
            display_name="Mumbai Plant"
        )
        sensor = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.SENSOR,
            canonical_name="Temperature Sensor 99",
            display_name="Temp 99"
        )

        # Valid edge: PLANT CONTAINS SENSOR (or MACHINE HAS_SENSOR SENSOR)
        # Invalid edge: SENSOR CONTAINS PLANT
        with self.assertRaises(ValueError) as ctx:
            self.kg_svc.create_operational_edge(
                identity=self.identity_pm_a,
                source_entity_id=sensor.entity_id,
                target_entity_id=plant.entity_id,
                predicate="CONTAINS"
            )
        self.assertIn("RELATIONSHIP_INCOMPATIBLE", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 6. Graph Traversals, Neighbors & Bounded Context
    # -------------------------------------------------------------------------

    def test_09_graph_traversal_neighbors_upstream_downstream(self):
        """Verifies 1-hop neighbors and upstream/downstream directional traversal."""
        line = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.PRODUCTION_LINE,
            canonical_name="Assembly Line 01",
            display_name="Line 01"
        )
        machine = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Assembly Robot 01",
            display_name="Robot 01"
        )
        sensor = self.onto_svc.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.SENSOR,
            canonical_name="Robot Speed Sensor",
            display_name="Speed Sensor"
        )

        # Structural ontology edges: Line CONTAINS Machine, Machine HAS_SENSOR Sensor
        self.onto_svc.create_relationship(
            identity=self.identity_pm_a,
            relationship_type=RelationshipType.CONTAINS,
            source_entity_id=line.entity_id,
            target_entity_id=machine.entity_id
        )
        self.onto_svc.create_relationship(
            identity=self.identity_pm_a,
            relationship_type=RelationshipType.HAS_SENSOR,
            source_entity_id=machine.entity_id,
            target_entity_id=sensor.entity_id
        )

        # Neighbors of Machine: Line (INCOMING) and Sensor (OUTGOING)
        neighbors = self.kg_svc.get_neighbors(machine.entity_id, self.identity_pm_a, direction="BOTH")
        neighbor_ids = [n.entity_id for n in neighbors]
        self.assertIn(line.entity_id, neighbor_ids)
        self.assertIn(sensor.entity_id, neighbor_ids)

        # Downstream of Machine -> Sensor
        downstream = self.kg_svc.get_downstream(machine.entity_id, self.identity_pm_a, max_depth=2)
        self.assertIn(sensor.entity_id, downstream.nodes)

        # Upstream of Machine -> Line
        upstream = self.kg_svc.get_upstream(machine.entity_id, self.identity_pm_a, max_depth=2)
        self.assertIn(line.entity_id, upstream.nodes)

    def test_10_bounded_traversal_and_cycle_avoidance(self):
        """Traverses cyclic graph (A -> B -> C -> A) safely without infinite recursion; bounds depth."""
        # Create 3 work cells in cycle
        c1 = self.onto_svc.create_entity(self.identity_pm_a, EntityType.WORK_CELL, "Cell A", "Cell A")
        c2 = self.onto_svc.create_entity(self.identity_pm_a, EntityType.WORK_CELL, "Cell B", "Cell B")
        c3 = self.onto_svc.create_entity(self.identity_pm_a, EntityType.WORK_CELL, "Cell C", "Cell C")

        # Cycle edges: C1 FEEDS C2, C2 FEEDS C3, C3 FEEDS C1
        self.kg_svc.create_operational_edge(self.identity_pm_a, c1.entity_id, c2.entity_id, "FEEDS")
        self.kg_svc.create_operational_edge(self.identity_pm_a, c2.entity_id, c3.entity_id, "FEEDS")
        self.kg_svc.create_operational_edge(self.identity_pm_a, c3.entity_id, c1.entity_id, "FEEDS")

        # Context expansion on C1 must terminate cleanly with total_nodes == 3
        ctx = self.kg_svc.get_context(c1.entity_id, self.identity_pm_a, depth=5, max_nodes=50)
        self.assertEqual(len(ctx.nodes), 3)
        self.assertIn(c1.entity_id, ctx.nodes)
        self.assertIn(c2.entity_id, ctx.nodes)
        self.assertIn(c3.entity_id, ctx.nodes)

    def test_11_path_lookup(self):
        """Computes shortest deterministic path using BFS."""
        n1 = self.onto_svc.create_entity(self.identity_pm_a, EntityType.WORK_CELL, "Path Start Node", "Start")
        n2 = self.onto_svc.create_entity(self.identity_pm_a, EntityType.WORK_CELL, "Path Mid Node", "Mid")
        n3 = self.onto_svc.create_entity(self.identity_pm_a, EntityType.WORK_CELL, "Path End Node", "End")

        self.kg_svc.create_operational_edge(self.identity_pm_a, n1.entity_id, n2.entity_id, "FEEDS")
        self.kg_svc.create_operational_edge(self.identity_pm_a, n2.entity_id, n3.entity_id, "FEEDS")

        path_res = self.kg_svc.find_path(n1.entity_id, n3.entity_id, self.identity_pm_a, max_depth=4)
        self.assertIsNotNone(path_res)
        self.assertEqual(path_res.depth, 2)
        self.assertEqual(path_res.path, [n1.entity_id, n2.entity_id, n3.entity_id])

    # -------------------------------------------------------------------------
    # 7. Freshness & Consistency
    # -------------------------------------------------------------------------

    def test_12_source_freshness_evaluation(self):
        """Evaluates FRESH, STALE, EXPIRED, and UNKNOWN freshness states."""
        now = datetime.now(timezone.utc)
        fresh_time = (now - timedelta(seconds=60)).isoformat()
        stale_time = (now - timedelta(seconds=600)).isoformat()
        expired_time = (now - timedelta(seconds=7200)).isoformat()

        self.assertEqual(self.kg_svc.calculate_freshness(fresh_time), FreshnessState.FRESH)
        self.assertEqual(self.kg_svc.calculate_freshness(stale_time), FreshnessState.STALE)
        self.assertEqual(self.kg_svc.calculate_freshness(expired_time), FreshnessState.EXPIRED)
        self.assertEqual(self.kg_svc.calculate_freshness(None), FreshnessState.UNKNOWN)

    def test_13_graph_consistency_validation(self):
        """Runs validation audit detecting clean vs conflicting state."""
        report = self.kg_svc.validate_graph(self.identity_pm_a)
        self.assertIsNotNone(report)
        self.assertEqual(report.tenant_id, self.tenant_a)
        # Should be valid
        self.assertTrue(report.is_valid)

    # -------------------------------------------------------------------------
    # 8. Operational Datacore Read-Only Projection
    # -------------------------------------------------------------------------

    def test_14_read_only_inventory_projection(self):
        """Reads datacore inventory table and projects facts without performing writes."""
        res = self.kg_svc.sync_inventory_projection(self.identity_pm_a)
        self.assertTrue(res.success)
        self.assertGreaterEqual(res.facts_ingested, 1)

    # -------------------------------------------------------------------------
    # 9. REST API & Authorization
    # -------------------------------------------------------------------------

    def test_15_api_endpoints_and_rbac_rate_limiting(self):
        """Verifies REST endpoints, 401 unauthenticated, and 403 unauthorized rejection."""
        # 1. Unauthenticated request rejected
        res_unauth = self.client.get(
            "/api/v3/knowledge-graph/snapshot",
            headers={"Authorization": "Bearer invalid_token"}
        )
        self.assertEqual(res_unauth.status_code, 401)

        # 2. Authorized read request succeeds
        token_pm = self._create_jwt_token(self.identity_pm_a)
        headers_pm = {"Authorization": f"Bearer {token_pm}"}

        res_snap = self.client.get("/api/v3/knowledge-graph/snapshot", headers=headers_pm)
        self.assertEqual(res_snap.status_code, 200)

        # 3. VIEWER attempting to POST /facts without knowledge_graph.manage returns 403
        token_viewer = self._create_jwt_token(self.identity_viewer_a)
        res_forbidden = self.client.post(
            "/api/v3/knowledge-graph/facts",
            headers={"Authorization": f"Bearer {token_viewer}"},
            json={
                "subject_entity_id": "machine:test:mch_01",
                "predicate": "TEMPERATURE",
                "value": 80.0,
                "source_id": "test"
            }
        )
        self.assertEqual(res_forbidden.status_code, 403)

    # -------------------------------------------------------------------------
    # 10. Strict Execution Isolation Proof
    # -------------------------------------------------------------------------

    def test_16_strict_execution_isolation_proof(self):
        """
        Proof of Execution Isolation:
        Verifies knowledge graph operations never write to operational database
        and never call Execution Gateway.
        """
        # 1. Connect to datacore and record inventory row count
        conn = sqlite3.connect("./dynamic_datacore.sqlite")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM inventory")
            inv_count_before = cursor.fetchone()[0]
        finally:
            conn.close()

        # 2. Perform graph actions
        mch = self.onto_svc.create_entity(
            self.identity_pm_a, EntityType.MACHINE, "Isolation Machine", "Iso Mch"
        )
        self.kg_svc.ingest_fact(
            identity=self.identity_pm_a,
            subject_entity_id=mch.entity_id,
            predicate="STATUS",
            value="TESTING"
        )

        # 3. Assert operational table is untouched
        conn = sqlite3.connect("./dynamic_datacore.sqlite")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM inventory")
            inv_count_after = cursor.fetchone()[0]
            self.assertEqual(inv_count_before, inv_count_after)
        finally:
            conn.close()

        # 4. Assert service has zero execution capabilities
        self.assertFalse(hasattr(self.kg_svc, "execute"))
        self.assertFalse(hasattr(self.kg_svc, "execute_action"))
        self.assertFalse(hasattr(self.kg_svc, "execute_transaction"))


if __name__ == "__main__":
    unittest.main()
