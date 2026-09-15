# backend/test_v3_data_quality.py
import unittest
import os
import uuid
import time
from datetime import datetime, timezone

from backend.data.schemas.data_quality_contract import (
    QualityDimension, QualityStatus, QualitySeverity, AssessmentScope
)
from backend.services.data_quality_repository import DataQualityRepository
from backend.services.data_quality_service import DataQualityService
from backend.services.ontology_repository import SQLiteOntologyRepository
from backend.services.ontology_service import OntologyService
from backend.services.knowledge_graph_repository import SQLiteKnowledgeGraphRepository
from backend.services.knowledge_graph_service import KnowledgeGraphService
from backend.services.digital_twin_repository import DigitalTwinRepository
from backend.services.digital_twin_service import DigitalTwinService
from backend.data.schemas.ontology_contract import OntologyEntity, EntityType, EntityLifecycleState
from backend.core.auth import Identity

class TestV3DataQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup ephemeral databases
        cls.test_db = "test_data_quality.sqlite"
        cls.test_ont_db = "test_ontology.sqlite"
        cls.test_kg_db = "test_kg.sqlite"
        cls.test_dt_db = "test_dt.sqlite"
        
        for db in [cls.test_db, cls.test_ont_db, cls.test_kg_db, cls.test_dt_db]:
            if os.path.exists(db):
                os.remove(db)
        
        cls.ont_repo = SQLiteOntologyRepository(cls.test_ont_db)
        cls.ont_svc = OntologyService(cls.ont_repo)
        
        cls.kg_repo = SQLiteKnowledgeGraphRepository(cls.test_kg_db)
        cls.kg_svc = KnowledgeGraphService(cls.kg_repo, cls.ont_svc)
        
        cls.dt_repo = DigitalTwinRepository(cls.test_dt_db)
        cls.dt_svc = DigitalTwinService(cls.dt_repo, cls.ont_svc, cls.kg_svc)
        
        cls.dq_repo = DataQualityRepository(cls.test_db)
        cls.dq_svc = DataQualityService(cls.dq_repo, cls.ont_svc, cls.kg_svc, cls.dt_svc)
        
        cls.identity = Identity(user_id="u1", tenant_id="t1", roles=["ANALYST"])
        cls.identity2 = Identity(user_id="u2", tenant_id="t2", roles=["ANALYST"])

        # Seed an entity
        cls.e1 = cls.ont_svc.create_entity(
            identity=cls.identity,
            entity_id="ent_1",
            entity_type=EntityType.MACHINE,
            canonical_name="machine_1",
            display_name="Machine 1",
            status=EntityLifecycleState.ACTIVE,
            attributes={}
        )

    @classmethod
    def tearDownClass(cls):
        for db in [cls.test_db, cls.test_ont_db, cls.test_kg_db, cls.test_dt_db]:
            if os.path.exists(db):
                try:
                    os.remove(db)
                except Exception:
                    pass

    def test_01_completeness_missing_field(self):
        # Create entity without name
        e2 = self.ont_svc.create_entity(
            identity=self.identity,
            entity_id="ent_2",
            entity_type=EntityType.MACHINE,
            canonical_name="machine_2",
            display_name="Machine 2",
            status=EntityLifecycleState.ACTIVE,
            attributes={}
        )
        
        # To test completeness for missing field (since name is removed, let's test missing external_ids or an arbitrary property)
        # Actually our completeness rule checks for `name`, but we have canonical_name and display_name. I will just clear canonical_name manually avoiding validation.
        e2.canonical_name = ""
        res = self.dq_svc._evaluate_completeness(e2)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].status, QualityStatus.FAIL)
        self.assertEqual(res[0].dimension, QualityDimension.COMPLETENESS)

    def test_02_uniqueness_duplicate_urn(self):
        e2 = self.e1.model_copy()
        e2.entity_id = "ent_dup"
        res = self.dq_svc._evaluate_uniqueness(e2, [self.e1, e2])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].status, QualityStatus.FAIL)
        self.assertEqual(res[0].dimension, QualityDimension.UNIQUENESS)

    def test_03_integrity_dangling_relationship(self):
        class MockRel:
            def __init__(self, target_entity_id):
                self.target_entity_id = target_entity_id
                self.relationship_id = "r1"
        rels = [MockRel("missing_entity")]
        res = self.dq_svc._evaluate_integrity(self.e1, rels, self.identity)
        self.assertEqual(res[0].status, QualityStatus.FAIL)
        self.assertEqual(res[0].dimension, QualityDimension.INTEGRITY)

    def test_04_conformity_invalid_state(self):
        e3 = self.ont_svc.create_entity(
            identity=self.identity,
            entity_id="ent_3",
            entity_type=EntityType.MACHINE,
            canonical_name="machine_3",
            display_name="Machine 3",
            status=EntityLifecycleState.CONFLICT,
            attributes={}
        )
        res = self.dq_svc._evaluate_conformity(e3)
        self.assertEqual(res[0].status, QualityStatus.WARN)
        self.assertEqual(res[0].dimension, QualityDimension.CONFORMITY)

    def test_05_accuracy_is_unknown(self):
        res = self.dq_svc._evaluate_accuracy()
        self.assertEqual(res[0].status, QualityStatus.UNKNOWN)
        self.assertEqual(res[0].dimension, QualityDimension.ACCURACY)

    def test_06_coverage_with_entities(self):
        res = self.dq_svc._evaluate_coverage([self.e1])
        self.assertEqual(res[0].status, QualityStatus.PASS)
        self.assertEqual(res[0].dimension, QualityDimension.COVERAGE)

    def test_07_coverage_without_entities(self):
        res = self.dq_svc._evaluate_coverage([])
        self.assertEqual(res[0].status, QualityStatus.UNKNOWN)

    def test_08_assessment_run(self):
        scope = AssessmentScope(tenant_id="t1")
        run = self.dq_svc.run_assessment(self.identity, scope)
        self.assertIsNotNone(run.assessment_id)
        self.assertTrue(run.overall_score >= 0.0)
        
        # Verify persistence
        runs = self.dq_svc.get_assessments(self.identity)
        self.assertEqual(len(runs), 1)

    def test_09_tenant_isolation(self):
        # Identity 2 should see 0 assessments
        runs = self.dq_svc.get_assessments(self.identity2)
        self.assertEqual(len(runs), 0)
        
        # Identity 2 should see 0 issues
        issues = self.dq_svc.list_issues(self.identity2)
        self.assertEqual(len(issues), 0)

    def test_10_no_execution_gateway_import(self):
        # Strict static verification that ExecutionGateway is completely absent
        with open("backend/services/data_quality_service.py", "r") as f:
            content = f.read()
            self.assertNotIn("ExecutionGateway", content)
            self.assertNotIn("ActionStatus", content)
            
        with open("backend/services/data_quality_repository.py", "r") as f:
            content = f.read()
            self.assertNotIn("ExecutionGateway", content)

    def test_11_freshness_digital_twin(self):
        class MockTwinState:
            is_expired = True
            recorded_at = "2026-09-01T00:00:00Z"
        
        dt_state = {"temp": MockTwinState()}
        res = self.dq_svc._evaluate_freshness(self.e1, dt_state)
        self.assertEqual(res[0].status, QualityStatus.FAIL)
        self.assertEqual(res[0].dimension, QualityDimension.FRESHNESS)

    def test_12_validity_digital_twin(self):
        class MockType:
            value = "UNKNOWN"
            
        class MockTwinState:
            property_type = MockType()
            
        dt_state = {"temp": MockTwinState()}
        res = self.dq_svc._evaluate_validity(self.e1, dt_state)
        self.assertEqual(res[0].status, QualityStatus.FAIL)
        self.assertEqual(res[0].dimension, QualityDimension.VALIDITY)

    def test_13_provenance_digital_twin(self):
        class MockTwinState:
            source_id = None
            
        dt_state = {"temp": MockTwinState()}
        res = self.dq_svc._evaluate_provenance(self.e1, dt_state)
        self.assertEqual(res[0].status, QualityStatus.WARN)
        self.assertEqual(res[0].dimension, QualityDimension.PROVENANCE)

    def test_14_consistency_knowledge_graph(self):
        class MockFact:
            relationship_type = "OPERATES_AT"
            
        kg_facts = [MockFact(), MockFact()]
        res = self.dq_svc._evaluate_consistency(self.e1, kg_facts)
        self.assertEqual(res[0].status, QualityStatus.FAIL)
        self.assertEqual(res[0].dimension, QualityDimension.CONSISTENCY)

if __name__ == '__main__':
    unittest.main()
