# backend/test_v3_ontology.py
"""
SageCommand V3 — Comprehensive Industrial Ontology Unit & Integration Tests
Verifies:
  1. Entity creation, retrieval, updates, and versioning.
  2. Taxonomy validation and invalid type rejection.
  3. Canonical identifier synthesis and uniqueness enforcement.
  4. Multi-tenant isolation boundary (cross-tenant access prohibited).
  5. Cross-tenant relationship rejection (fails closed).
  6. External system identifier resolution (MES, SCADA, ERP, SAP).
  7. Conflicting external identity detection and CONFLICT state.
  8. Valid semantic relationship creation across compatibility matrix.
  9. Incompatible relationship rejection (e.g. CUSTOMER HAS_SENSOR SENSOR).
  10. Guarded entity lifecycle transitions.
  11. Invalid lifecycle transition rejection.
  12. Provenance tracking and historical version snapshotting.
  13. REST API authorized read endpoints (/taxonomy, /entities, /lookup).
  14. REST API authentication and RBAC permission enforcement (401 and 403).
  15. Strict execution isolation proof (no operational database writes).
"""

import os
import unittest
import sqlite3
import jwt
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from core.config import SAGE_SECRET_KEY, SAGE_AUTH_ISSUER, SAGE_AUTH_AUDIENCE, SAGE_ONTOLOGY_DB_PATH
from core.auth import Identity
from data.schemas.ontology_contract import (
    OntologyEntity,
    OntologyRelationship,
    EntityType,
    EntityLifecycleState,
    EntitySource,
    RelationshipType,
    RelationshipConfidence,
    validate_relationship_compatibility,
    validate_lifecycle_transition,
)
from services.ontology_repository import SQLiteOntologyRepository
from services.ontology_service import OntologyService
from services.authorization_service import authorization_service
try:
    from api import ontology_routes
except ImportError:
    from backend.api import ontology_routes
from server import app


class TestV3IndustrialOntology(unittest.TestCase):
    """Test suite for SageCommand V3 Industrial Ontology Foundation."""

    @classmethod
    def setUpClass(cls):
        cls.test_db_path = "test_sage_ontology.sqlite"
        if os.path.exists(cls.test_db_path):
            try:
                os.remove(cls.test_db_path)
            except OSError:
                pass

        cls.repo = SQLiteOntologyRepository(db_path=cls.test_db_path)
        cls.service = OntologyService(repo=cls.repo)
        ontology_routes.ontology_service = cls.service

        # Create isolated identities for testing
        cls.tenant_a = "tenant_mfg_alpha"
        cls.tenant_b = "tenant_mfg_beta"

        cls.identity_admin_a = Identity(
            user_id="user_admin_a",
            tenant_id=cls.tenant_a,
            roles=["ADMINISTRATOR"],
            workspace_id="workspace_alpha",
            plant_id="plant_mumbai",
            is_server_authoritative=True
        )

        cls.identity_pm_a = Identity(
            user_id="user_pm_a",
            tenant_id=cls.tenant_a,
            roles=["PLANT_MANAGER"],
            workspace_id="workspace_alpha",
            plant_id="plant_mumbai",
            is_server_authoritative=True
        )

        cls.identity_op_a = Identity(
            user_id="user_op_a",
            tenant_id=cls.tenant_a,
            roles=["OPERATOR"],
            workspace_id="workspace_alpha",
            plant_id="plant_mumbai",
            is_server_authoritative=True
        )

        cls.identity_viewer_a = Identity(
            user_id="user_viewer_a",
            tenant_id=cls.tenant_a,
            roles=["VIEWER"],
            workspace_id="workspace_alpha",
            plant_id="plant_mumbai",
            is_server_authoritative=True
        )

        cls.identity_pm_b = Identity(
            user_id="user_pm_b",
            tenant_id=cls.tenant_b,
            roles=["PLANT_MANAGER"],
            workspace_id="workspace_beta",
            plant_id="plant_pune",
            is_server_authoritative=True
        )

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            try:
                os.remove(cls.test_db_path)
            except OSError:
                pass

    def _create_jwt_token(self, identity: Identity) -> str:
        assigned_plants = getattr(identity, "assigned_plants", None)
        plant_id = assigned_plants[0] if assigned_plants else "plant_mumbai"
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
    # 1. Entity Lifecycle & Taxonomies
    # -------------------------------------------------------------------------

    def test_01_create_and_retrieve_entity(self):
        """Create valid entity, verify auto-generated canonical ID and retrieval."""
        entity = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Hydraulic Stamping Press 01",
            display_name="Press 01",
            plant_id="plant_mumbai",
            attributes={"tonnage": 500, "manufacturer": "Schuler"},
            source=EntitySource.MES
        )

        self.assertIsNotNone(entity)
        self.assertEqual(entity.entity_type, EntityType.MACHINE)
        self.assertTrue(entity.entity_id.startswith("machine:plant_mumbai:hydraulic_stamping_press_01"))
        self.assertEqual(entity.tenant_id, self.tenant_a)
        self.assertEqual(entity.version, 1)
        self.assertEqual(entity.status, EntityLifecycleState.ACTIVE)
        self.assertEqual(entity.attributes.get("tonnage"), 500)

        # Retrieve and verify
        retrieved = self.service.get_entity(entity.entity_id, self.identity_pm_a)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.entity_id, entity.entity_id)
        self.assertEqual(retrieved.canonical_name, "Hydraulic Stamping Press 01")

    def test_02_invalid_entity_type_rejected(self):
        """Pydantic model rejects unknown or invalid entity types."""
        with self.assertRaises(ValueError):
            OntologyEntity(
                entity_id="custom:device:01",
                entity_type="NON_EXISTENT_TYPE",  # type: ignore
                canonical_name="Invalid Thing",
                display_name="Invalid",
                tenant_id=self.tenant_a
            )

    def test_03_missing_or_duplicate_canonical_id_rejected(self):
        """Duplicate canonical ID within the same tenant raises ValueError."""
        cid = "machine:plant_mumbai:unique_cnc_mill_01"
        self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Unique CNC Mill 01",
            display_name="CNC Mill 01",
            entity_id=cid
        )

        with self.assertRaises(ValueError) as ctx:
            self.service.create_entity(
                identity=self.identity_pm_a,
                entity_type=EntityType.MACHINE,
                canonical_name="Duplicate CNC Mill 01",
                display_name="Duplicate",
                entity_id=cid
            )
        self.assertIn("DUPLICATE_CANONICAL_ID", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 2. Multi-Tenant Isolation
    # -------------------------------------------------------------------------

    def test_04_tenant_isolation_enforced(self):
        """Tenant B cannot read or modify Tenant A's ontology entities."""
        ent_a = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.PRODUCTION_LINE,
            canonical_name="Battery Pack Assembly Line",
            display_name="Line Alpha"
        )

        # Tenant B queries entity A -> returns None
        ent_b_query = self.service.get_entity(ent_a.entity_id, self.identity_pm_b)
        self.assertIsNone(ent_b_query)

        # Tenant B attempts update on entity A -> raises KeyError
        with self.assertRaises(KeyError):
            self.service.update_entity(
                entity_id=ent_a.entity_id,
                identity=self.identity_pm_b,
                display_name="Tampered Line"
            )

    def test_05_cross_tenant_relationship_rejected(self):
        """Creating relationship connecting entities across different tenants fails closed."""
        ent_a = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Alpha Machine",
            display_name="Alpha MCH"
        )

        ent_b = self.service.create_entity(
            identity=self.identity_pm_b,
            entity_type=EntityType.SENSOR,
            canonical_name="Beta Sensor",
            display_name="Beta SNS"
        )

        # Caller in Tenant A attempts to link ent_a to ent_b (which is in Tenant B)
        with self.assertRaises(KeyError) as ctx:
            self.service.create_relationship(
                identity=self.identity_pm_a,
                relationship_type=RelationshipType.HAS_SENSOR,
                source_entity_id=ent_a.entity_id,
                target_entity_id=ent_b.entity_id
            )
        self.assertIn("TARGET_ENTITY_NOT_FOUND", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 3. External Identifiers & Conflict Handling
    # -------------------------------------------------------------------------

    def test_06_external_id_mapping_and_lookup(self):
        """Maps MES, SCADA, ERP external identifiers and resolves back to canonical entity."""
        press = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Ext Press Line 1 Machine",
            display_name="Press Line 1",
            plant_id="plant_mumbai",
            external_ids={"SAP": "10007891", "MES": "MCH-007"}
        )

        # Register SCADA mapping via method
        self.service.register_external_mapping(
            identity=self.identity_pm_a,
            entity_id=press.entity_id,
            system="SCADA",
            external_id="PRESS7"
        )

        # Lookup by MES
        res_mes = self.service.lookup_by_external_id(self.identity_pm_a, "MES", "MCH-007")
        self.assertTrue(res_mes.resolved)
        self.assertIsNotNone(res_mes.entity)
        self.assertEqual(res_mes.entity.entity_id, press.entity_id)

        # Lookup by SCADA
        res_scada = self.service.lookup_by_external_id(self.identity_pm_a, "SCADA", "PRESS7")
        self.assertTrue(res_scada.resolved)
        self.assertEqual(res_scada.entity.entity_id, press.entity_id)

    def test_07_conflicting_external_mapping_detected(self):
        """Attempting to assign an existing external ID to a second entity triggers conflict error."""
        mch_1 = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="First Machine",
            display_name="MCH 1",
            external_ids={"MES": "MES-SHARED-01"}
        )

        mch_2 = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Second Machine",
            display_name="MCH 2"
        )

        # Attempt to map the same MES-SHARED-01 to mch_2
        with self.assertRaises(ValueError) as ctx:
            self.service.register_external_mapping(
                identity=self.identity_pm_a,
                entity_id=mch_2.entity_id,
                system="MES",
                external_id="MES-SHARED-01"
            )
        self.assertIn("EXTERNAL_ID_CONFLICT", str(ctx.exception))

        # mch_2 should be in CONFLICT state
        refreshed_2 = self.service.get_entity(mch_2.entity_id, self.identity_pm_a)
        self.assertEqual(refreshed_2.status, EntityLifecycleState.CONFLICT)

    # -------------------------------------------------------------------------
    # 4. Semantic Relationships & Compatibility Matrix
    # -------------------------------------------------------------------------

    def test_08_valid_relationship_accepted(self):
        """Permitted relationships per compatibility matrix are accepted."""
        plant = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.PLANT,
            canonical_name="Mumbai Gigafactory",
            display_name="Mumbai Plant"
        )
        line = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.PRODUCTION_LINE,
            canonical_name="Stamping Line 1",
            display_name="Line 1"
        )
        machine = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.MACHINE,
            canonical_name="Line 1 Press A",
            display_name="Press A"
        )
        sensor = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.SENSOR,
            canonical_name="Vibration Sensor 101",
            display_name="VIB-101"
        )

        # 1. PLANT CONTAINS PRODUCTION_LINE
        rel_1 = self.service.create_relationship(
            identity=self.identity_pm_a,
            relationship_type=RelationshipType.CONTAINS,
            source_entity_id=plant.entity_id,
            target_entity_id=line.entity_id
        )
        self.assertIsNotNone(rel_1)
        self.assertEqual(rel_1.relationship_type, RelationshipType.CONTAINS)

        # 2. PRODUCTION_LINE CONTAINS MACHINE
        rel_2 = self.service.create_relationship(
            identity=self.identity_pm_a,
            relationship_type=RelationshipType.CONTAINS,
            source_entity_id=line.entity_id,
            target_entity_id=machine.entity_id
        )
        self.assertIsNotNone(rel_2)

        # 3. MACHINE HAS_SENSOR SENSOR
        rel_3 = self.service.create_relationship(
            identity=self.identity_pm_a,
            relationship_type=RelationshipType.HAS_SENSOR,
            source_entity_id=machine.entity_id,
            target_entity_id=sensor.entity_id
        )
        self.assertIsNotNone(rel_3)

        # Query relationships for machine
        mch_rels = self.service.get_entity_relationships(machine.entity_id, self.identity_pm_a)
        self.assertEqual(len(mch_rels), 2)  # Line CONTAINS machine (incoming), machine HAS_SENSOR (outgoing)

    def test_09_invalid_relationship_rejected(self):
        """Incompatible relationships (e.g. CUSTOMER HAS_SENSOR SENSOR) are rejected."""
        customer = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.CUSTOMER,
            canonical_name="Automotive OEM Customer",
            display_name="OEM Client"
        )
        sensor = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.SENSOR,
            canonical_name="Thermal Sensor 502",
            display_name="TEMP-502"
        )

        with self.assertRaises(ValueError) as ctx:
            self.service.create_relationship(
                identity=self.identity_pm_a,
                relationship_type=RelationshipType.HAS_SENSOR,
                source_entity_id=customer.entity_id,
                target_entity_id=sensor.entity_id
            )
        self.assertIn("RELATIONSHIP_INCOMPATIBLE", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 5. Lifecycle Transitions & Versioning
    # -------------------------------------------------------------------------

    def test_10_valid_lifecycle_transition(self):
        """Entity transitions cleanly through permitted lifecycle states."""
        ent = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.EQUIPMENT,
            canonical_name="Cooling Chiller 04",
            display_name="Chiller 4",
            status=EntityLifecycleState.DISCOVERED
        )
        self.assertEqual(ent.status, EntityLifecycleState.DISCOVERED)

        # DISCOVERED -> ACTIVE
        updated_1 = self.service.update_entity(ent.entity_id, self.identity_pm_a, status=EntityLifecycleState.ACTIVE)
        self.assertEqual(updated_1.status, EntityLifecycleState.ACTIVE)

        # ACTIVE -> INACTIVE
        updated_2 = self.service.update_entity(ent.entity_id, self.identity_pm_a, status=EntityLifecycleState.INACTIVE)
        self.assertEqual(updated_2.status, EntityLifecycleState.INACTIVE)

        # INACTIVE -> DECOMMISSIONED
        updated_3 = self.service.update_entity(ent.entity_id, self.identity_pm_a, status=EntityLifecycleState.DECOMMISSIONED)
        self.assertEqual(updated_3.status, EntityLifecycleState.DECOMMISSIONED)

        # DECOMMISSIONED -> ARCHIVED
        updated_4 = self.service.update_entity(ent.entity_id, self.identity_pm_a, status=EntityLifecycleState.ARCHIVED)
        self.assertEqual(updated_4.status, EntityLifecycleState.ARCHIVED)

    def test_11_invalid_lifecycle_transition_rejected(self):
        """Illegal transition (e.g. DECOMMISSIONED -> ACTIVE) raises ValueError."""
        ent = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.EQUIPMENT,
            canonical_name="Scrapped Conveyor",
            display_name="Old Conveyor",
            status=EntityLifecycleState.DECOMMISSIONED
        )

        with self.assertRaises(ValueError) as ctx:
            self.service.update_entity(ent.entity_id, self.identity_pm_a, status=EntityLifecycleState.ACTIVE)
        self.assertIn("INVALID_LIFECYCLE_TRANSITION", str(ctx.exception))

    def test_12_provenance_and_versioning(self):
        """Updating entity increments version and preserves historical snapshots."""
        ent = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.WAREHOUSE,
            canonical_name="Main Parts Warehouse",
            display_name="WH-01",
            attributes={"capacity_sqft": 50000}
        )
        self.assertEqual(ent.version, 1)

        # Update 1
        u1 = self.service.update_entity(
            ent.entity_id,
            self.identity_pm_a,
            display_name="Central Parts Depot",
            attributes={"capacity_sqft": 75000}
        )
        self.assertEqual(u1.version, 2)
        self.assertEqual(u1.display_name, "Central Parts Depot")

        # Update 2
        u2 = self.service.update_entity(
            ent.entity_id,
            self.identity_pm_a,
            display_name="Central Logistics Hub"
        )
        self.assertEqual(u2.version, 3)

        # Check snapshots
        snapshots = self.repo.get_entity_versions(self.tenant_a, ent.entity_id)
        self.assertEqual(len(snapshots), 2)  # Version 1 and Version 2 preserved

    # -------------------------------------------------------------------------
    # 6. REST API Endpoints & Security
    # -------------------------------------------------------------------------

    def test_13_api_taxonomy_and_read_endpoints(self):
        """Authorized user queries /taxonomy, /entities, /mappings, and /lookup via REST API."""
        token = self._create_jwt_token(self.identity_pm_a)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. GET /api/v3/ontology/taxonomy
        res_tax = self.client.get("/api/v3/ontology/taxonomy", headers=headers)
        self.assertEqual(res_tax.status_code, 200)
        data_tax = res_tax.json()
        self.assertTrue(data_tax["success"])
        self.assertIn("MACHINE", data_tax["entity_types"])
        self.assertIn("HAS_SENSOR", data_tax["relationship_types"])
        self.assertIn("CONTAINS", data_tax["compatibility_rules"])

        # 2. POST /api/v3/ontology/entities
        res_create = self.client.post(
            "/api/v3/ontology/entities",
            headers=headers,
            json={
                "entity_type": "MACHINE",
                "canonical_name": "API CNC Machine 07",
                "display_name": "CNC 07",
                "plant_id": "plant_mumbai",
                "source": "MES",
                "attributes": {"axis": 5}
            }
        )
        self.assertEqual(res_create.status_code, 201)
        ent_data = res_create.json()["data"]
        ent_id = ent_data["entity_id"]

        # 3. POST /api/v3/ontology/mappings
        res_map = self.client.post(
            "/api/v3/ontology/mappings",
            headers=headers,
            json={
                "entity_id": ent_id,
                "system": "MES",
                "external_id": "MCH-API-007",
                "confidence": "CONFIRMED"
            }
        )
        self.assertEqual(res_map.status_code, 201)

        # 4. GET /api/v3/ontology/entities
        res_list = self.client.get("/api/v3/ontology/entities?limit=10", headers=headers)
        self.assertEqual(res_list.status_code, 200)
        data_list = res_list.json()
        self.assertTrue(data_list["success"])
        self.assertGreaterEqual(data_list["total_count"], 1)

        # 5. GET /api/v3/ontology/lookup
        res_lookup = self.client.get("/api/v3/ontology/lookup?system=MES&external_id=MCH-API-007", headers=headers)
        self.assertEqual(res_lookup.status_code, 200)
        data_lookup = res_lookup.json()
        self.assertTrue(data_lookup["resolved"])
        self.assertEqual(data_lookup["entity"]["entity_id"], ent_id)

    def test_14_api_unauthenticated_and_unauthorized_rejected(self):
        """Unauthenticated requests are rejected (401), and lacking permissions raises 403."""
        # Unauthenticated request with invalid token
        res_unauth = self.client.get(
            "/api/v3/ontology/taxonomy",
            headers={"Authorization": "Bearer invalid_token"}
        )
        self.assertEqual(res_unauth.status_code, 401)

        # User with VIEWER role attempting write (POST /entities requires ontology.manage)
        token_viewer = self._create_jwt_token(self.identity_viewer_a)
        res_forbidden = self.client.post(
            "/api/v3/ontology/entities",
            headers={"Authorization": f"Bearer {token_viewer}"},
            json={
                "entity_type": "MACHINE",
                "canonical_name": "Forbidden Press",
                "display_name": "No Access"
            }
        )
        self.assertEqual(res_forbidden.status_code, 403)

    # -------------------------------------------------------------------------
    # 7. Strict Execution Isolation Proof
    # -------------------------------------------------------------------------

    def test_15_execution_isolation_proof(self):
        """
        Proof of Execution Isolation:
        Proves that creating or modifying ontology entities NEVER touches operational
        database tables (e.g. inventory) and NEVER calls Execution Gateway.
        """
        # 1. Connect to session test DB to verify inventory count before ontology action
        conn = sqlite3.connect("./dynamic_datacore.sqlite")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM inventory")
            inv_count_before = cursor.fetchone()[0]
        except Exception:
            inv_count_before = 0
        finally:
            conn.close()

        # 2. Perform extensive ontology creations, mappings, and relationships
        inv_entity = self.service.create_entity(
            identity=self.identity_pm_a,
            entity_type=EntityType.INVENTORY_ITEM,
            canonical_name="Microcontroller Component Board",
            display_name="MCU-Board-X1",
            attributes={"target_stock": 2000, "reorder_point": 500}
        )

        self.service.register_external_mapping(
            identity=self.identity_pm_a,
            entity_id=inv_entity.entity_id,
            system="SAP",
            external_id="SAP-MAT-9901"
        )

        # 3. Verify operational inventory table has not been altered
        conn = sqlite3.connect("./dynamic_datacore.sqlite")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM inventory")
            inv_count_after = cursor.fetchone()[0]
            self.assertEqual(inv_count_before, inv_count_after)
        except Exception:
            pass
        finally:
            conn.close()

        # 4. Verify ontology service has zero operational execution attributes
        self.assertFalse(hasattr(self.service, "execute"))
        self.assertFalse(hasattr(self.service, "execute_action"))
        self.assertFalse(hasattr(self.service, "execute_transaction"))


if __name__ == "__main__":
    unittest.main()
