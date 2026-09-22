import pytest
import concurrent.futures
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.server import app
from backend.services.blast_radius_service import BlastRadiusService
from backend.services.blast_radius_repository import BlastRadiusRepository
from backend.data.schemas.blast_radius_contract import (
    BlastRadiusAnalysis,
    BlastRadiusAnalysisStatus,
    ImpactClassification,
    ImpactPath,
    ImpactScope,
    ImpactNode,
    ConfidenceLevel
)
from backend.services.knowledge_graph_service import KnowledgeGraphService
from backend.core.auth import Identity, get_current_identity
from backend.data.schemas.authorization_contract import AuthorizationDecision

@pytest.fixture
def mock_repo():
    return MagicMock(spec=BlastRadiusRepository)

@pytest.fixture
def mock_kg_service():
    kg = MagicMock(spec=KnowledgeGraphService)
    def mock_get_entity_node(entity_id, identity, at_time=None):
        nodes = {
            "pump_01": MagicMock(entity_id="pump_01", entity_type="ASSET", plant_id="plant_01"),
            "valve_02": MagicMock(entity_id="valve_02", entity_type="ASSET", plant_id="plant_01"),
            "tank_03": MagicMock(entity_id="tank_03", entity_type="ASSET", plant_id="plant_01"),
            "pipe_04": MagicMock(entity_id="pipe_04", entity_type="ASSET", plant_id="plant_01"),
            "process_05": MagicMock(entity_id="process_05", entity_type="PROCESS", plant_id="plant_01"),
            "controller_06": MagicMock(entity_id="controller_06", entity_type="ASSET", plant_id="plant_01"),
            "unsupported_07": MagicMock(entity_id="unsupported_07", entity_type="ASSET", plant_id="plant_01")
        }
        return nodes.get(entity_id)

    kg.get_entity_node.side_effect = mock_get_entity_node
    
    def mock_get_neighbors(entity_id, identity, direction="BOTH", at_time=None):
        edges = {
            "pump_01": [
                MagicMock(entity_id="valve_02", relationship_type="FEEDS_INTO", direction="OUTGOING", edge_source="kg"),
                MagicMock(entity_id="controller_06", relationship_type="CONTROLS", direction="INCOMING", edge_source="kg")
            ],
            "valve_02": [
                MagicMock(entity_id="pump_01", relationship_type="FEEDS_INTO", direction="INCOMING", edge_source="kg"),
                MagicMock(entity_id="tank_03", relationship_type="FEEDS_INTO", direction="OUTGOING", edge_source="kg"),
                MagicMock(entity_id="unsupported_07", relationship_type="UNKNOWN_REL", direction="BOTH", edge_source="kg")
            ],
            "tank_03": [
                MagicMock(entity_id="valve_02", relationship_type="FEEDS_INTO", direction="INCOMING", edge_source="kg"),
                MagicMock(entity_id="pipe_04", relationship_type="FEEDS_INTO", direction="OUTGOING", edge_source="kg"),
                MagicMock(entity_id="process_05", relationship_type="MONITORS", direction="INCOMING", edge_source="kg")
            ],
            "pipe_04": [
                MagicMock(entity_id="tank_03", relationship_type="FEEDS_INTO", direction="INCOMING", edge_source="kg")
            ],
            "process_05": [
                MagicMock(entity_id="tank_03", relationship_type="MONITORS", direction="OUTGOING", edge_source="kg")
            ],
            "controller_06": [
                MagicMock(entity_id="pump_01", relationship_type="CONTROLS", direction="OUTGOING", edge_source="kg")
            ],
            "unsupported_07": [
                MagicMock(entity_id="valve_02", relationship_type="UNKNOWN_REL", direction="BOTH", edge_source="kg")
            ]
        }
        
        if direction == "OUTGOING":
            return [e for e in edges.get(entity_id, []) if e.direction == "OUTGOING"]
        elif direction == "INCOMING":
            return [e for e in edges.get(entity_id, []) if e.direction == "INCOMING"]
        return edges.get(entity_id, [])

    kg.get_neighbors.side_effect = mock_get_neighbors
    return kg

@pytest.fixture
def blast_radius_service(mock_repo, mock_kg_service):
    return BlastRadiusService(mock_repo, mock_kg_service)

@pytest.fixture
def test_client():
    return TestClient(app)

class TestBlastRadiusContract:
    def test_analysis_schema_validation(self):
        analysis = BlastRadiusAnalysis(
            tenant_id="tenant_1",
            source_entity_id="pump_01",
            snapshot_timestamp=datetime.now(UTC).isoformat()
        )
        assert analysis.confidence == ConfidenceLevel.INSUFFICIENT_DATA
        
        fingerprint = analysis.generate_fingerprint()
        assert analysis.input_fingerprint == fingerprint
        assert fingerprint is not None

class TestBlastRadiusPropagation:
    def test_blast_radius_bfs_traversal(self, blast_radius_service, mock_repo):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        result = blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="valve_02"
        )
        assert result is not None
        assert result.source_entity_id == "valve_02"
        mock_repo.save_analysis.assert_called_once()
        saved = mock_repo.save_analysis.call_args[0][0]
        
        assert len(saved.nodes) == 7
        node_ids = {n.entity_id for n in saved.nodes}
        for expected in ["valve_02", "pump_01", "tank_03", "pipe_04", "process_05", "controller_06", "unsupported_07"]:
            assert expected in node_ids
        
        pump = next(n for n in saved.nodes if n.entity_id == "pump_01")
        assert pump.impact_classification == ImpactClassification.UPSTREAM
        
        tank = next(n for n in saved.nodes if n.entity_id == "tank_03")
        assert tank.impact_classification == ImpactClassification.DOWNSTREAM
        
        assert tank.distance == 1
        assert tank.impact_score == 80.0
        
        pipe = next(n for n in saved.nodes if n.entity_id == "pipe_04")
        assert pipe.distance == 2
        assert pipe.impact_score == 64.0
        
        unsup = next(n for n in saved.nodes if n.entity_id == "unsupported_07")
        assert unsup.impact_classification == ImpactClassification.UNKNOWN
        
        assert len(saved.paths) > 0

    def test_blast_radius_max_depth_limit(self, blast_radius_service, mock_repo, mock_kg_service):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        
        result = blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="valve_02",
            max_depth=1
        )
        saved = mock_repo.save_analysis.call_args[0][0]
        assert len(saved.nodes) == 4
        node_ids = {n.entity_id for n in saved.nodes}
        assert "pipe_04" not in node_ids
        
    def test_blast_radius_max_nodes_limit(self, blast_radius_service, mock_repo, mock_kg_service):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        
        result = blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="valve_02",
            max_nodes=2
        )
        saved = mock_repo.save_analysis.call_args[0][0]
        assert len(saved.nodes) == 2

    def test_duplicate_path_handling(self, blast_radius_service, mock_repo, mock_kg_service):
        orig_get_neighbors = mock_kg_service.get_neighbors.side_effect
        def mock_get_neighbors_dup(entity_id, identity, direction="BOTH", at_time=None):
            res = orig_get_neighbors(entity_id, identity, direction, at_time)
            if entity_id == "controller_06":
                res.append(MagicMock(entity_id="valve_02", relationship_type="FEEDS_INTO", direction="OUTGOING", edge_source="kg"))
            return res
        mock_kg_service.get_neighbors.side_effect = mock_get_neighbors_dup
        
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="controller_06"
        )
        saved = mock_repo.save_analysis.call_args[0][0]
        valve = next(n for n in saved.nodes if n.entity_id == "valve_02")
        assert valve.impact_score == 80.0
        
    def test_temporal_validity(self, blast_radius_service, mock_repo, mock_kg_service):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        result = blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="pump_01"
        )
        saved = mock_repo.save_analysis.call_args[0][0]
        mock_kg_service.get_neighbors.assert_called()
        call_args = mock_kg_service.get_neighbors.call_args
        assert call_args[1].get('at_time') == saved.snapshot_timestamp

    def test_digital_twin_integration(self, blast_radius_service, mock_repo):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="valve_02"
        )
        saved = mock_repo.save_analysis.call_args[0][0]
        assert saved.scope.total_assets == 6
        assert saved.scope.total_processes == 1
        
    def test_incident_anomaly_integration(self, blast_radius_service, mock_repo):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="pump_01",
            source_incident_id="inc_001",
            source_anomaly_id="anom_002"
        )
        saved = mock_repo.save_analysis.call_args[0][0]
        assert saved.source_incident_id == "inc_001"
        assert saved.source_anomaly_id == "anom_002"
        assert saved.analysis_status == BlastRadiusAnalysisStatus.COMPLETED

    def test_deterministic_fingerprint_caching(self, blast_radius_service, mock_repo):
        cached_analysis = BlastRadiusAnalysis(
            tenant_id="tenant_1",
            snapshot_timestamp="2026-09-17T00:00:00Z",
            analysis_id="bra_cached",
            source_entity_id="pump_01",
            input_fingerprint="abc",
            analysis_status="COMPLETED",
        )
        mock_repo.get_analysis_by_fingerprint.return_value = cached_analysis
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        result = blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="pump_01"
        )
        assert result.analysis_id == "bra_cached"
        mock_repo.save_analysis.assert_not_called()

    def test_isolation_no_mutations_allowed(self):
        methods = dir(BlastRadiusService)
        disallowed_terms = ["execute", "remediate", "revert", "action", "write_to_device"]
        for term in disallowed_terms:
            for method in methods:
                assert term not in method.lower()

class TestBlastRadiusPersistence:
    def test_sqlite_persistence_mock(self):
        import tempfile
        import os
        fd, db_path = tempfile.mkstemp()
        os.close(fd)
        try:
            repo = BlastRadiusRepository(db_path=db_path)
            analysis = BlastRadiusAnalysis(
                tenant_id="tenant_1",
                snapshot_timestamp="2026-09-17T00:00:00Z",
                analysis_id="bra_01",
                source_entity_id="pump_01",
                analysis_status=BlastRadiusAnalysisStatus.COMPLETED,
                scope=ImpactScope(total_assets=1, total_processes=0, total_production_areas=0, total_workspaces=0, total_plants=0, total_upstream_dependencies=0, total_downstream_dependencies=0, related_incidents=0, related_anomalies=0)
            )
            analysis.generate_fingerprint()
            repo.save_analysis(analysis)
            
            retrieved = repo.get_analysis("bra_01", "tenant_1")
            assert retrieved is not None
            assert retrieved.analysis_id == "bra_01"
            assert retrieved.scope.total_assets == 1
            
            retrieved_fp = repo.get_analysis_by_fingerprint(analysis.input_fingerprint)
            assert retrieved_fp is not None
            assert retrieved_fp.analysis_id == "bra_01"
            
            assert repo.get_analysis("bra_01", "tenant_2") is None
        finally:
            os.unlink(db_path)

    def test_concurrency(self, blast_radius_service, mock_repo):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        identity = Identity(tenant_id="tenant_1", workspace_id="default", user_id="operator_01", roles=[], permissions=[])
        
        def run_analysis():
            return blast_radius_service.analyze_impact(identity, "valve_02")
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run_analysis) for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
        assert len(results) == 5
        for res in results:
            assert res.source_entity_id == "valve_02"
            
class TestBlastRadiusAPI:
    def test_api_analyze(self, test_client):
        import sys
        module_name = 'api.blast_radius_routes' if 'api.blast_radius_routes' in sys.modules else 'backend.api.blast_radius_routes'
        
        with patch(f"{module_name}.AuthorizationContext") as mock_ctx, \
             patch(f"{module_name}.authorization_service") as mock_auth, \
             patch(f"{module_name}.blast_radius_service") as mock_service:
             
            decision_mock = MagicMock()
            decision_mock.is_allowed.return_value = True
            mock_auth.evaluate.return_value = decision_mock
            
            mock_service.analyze_impact.return_value = BlastRadiusAnalysis(
                tenant_id="tenant_1",
                snapshot_timestamp="2026-09-17T00:00:00Z",
                analysis_status=BlastRadiusAnalysisStatus.COMPLETED,
                analysis_id="bra_123",
                source_entity_id="pump_01"
            )
            
            app.dependency_overrides[get_current_identity] = lambda: Identity(tenant_id="t1", workspace_id="w1", user_id="u1", roles=[])
            
            response = test_client.post(
                "/v3/blast-radius/analyze",
                json={"source_entity_id": "pump_01"}
            )
            assert response.status_code == 200
            assert response.json()["analysis_id"] == "bra_123"
            app.dependency_overrides = {}

    def test_api_rbac_enforcement(self, test_client):
        import sys
        module_name = 'api.blast_radius_routes' if 'api.blast_radius_routes' in sys.modules else 'backend.api.blast_radius_routes'
        
        with patch(f"{module_name}.AuthorizationContext") as mock_ctx, \
             patch(f"{module_name}.authorization_service") as mock_auth:
             
            decision_mock = MagicMock()
            decision_mock.is_allowed.return_value = False
            decision_mock.reason = "Denied"
            mock_auth.evaluate.return_value = decision_mock
            
            app.dependency_overrides[get_current_identity] = lambda: Identity(tenant_id="t1", workspace_id="w1", user_id="u1", roles=[])
            
            response = test_client.post(
                "/v3/blast-radius/analyze",
                json={"source_entity_id": "pump_01"}
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "Denied"
        
        app.dependency_overrides = {}
