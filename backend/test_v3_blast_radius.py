import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from backend.services.blast_radius_service import BlastRadiusService
from backend.services.blast_radius_repository import BlastRadiusRepository
from backend.data.schemas.blast_radius_contract import (
    BlastRadiusAnalysis,
    ImpactClassification,
    ImpactPath,
    ImpactScope
)
from backend.services.knowledge_graph_service import KnowledgeGraphService
from backend.core.config import SAGE_BLAST_RADIUS_MAX_DEPTH, SAGE_BLAST_RADIUS_MAX_NODES

@pytest.fixture
def mock_repo():
    return MagicMock(spec=BlastRadiusRepository)

@pytest.fixture
def mock_kg_service():
    kg = MagicMock(spec=KnowledgeGraphService)
    # Mock get_entity_node
    def mock_get_entity_node(entity_id, identity, at_time=None):
        if entity_id == "pump_01":
            return MagicMock(entity_id="pump_01", entity_type="ASSET", plant_id="plant_01")
        if entity_id == "valve_02":
            return MagicMock(entity_id="valve_02", entity_type="ASSET", plant_id="plant_01")
        if entity_id == "tank_03":
            return MagicMock(entity_id="tank_03", entity_type="ASSET", plant_id="plant_01")
        return None
    kg.get_entity_node.side_effect = mock_get_entity_node
    
    # Mock get_neighbors
    def mock_get_neighbors(entity_id, identity, direction="BOTH", at_time=None):
        if entity_id == "pump_01":
            return [
                MagicMock(entity_id="valve_02", relationship_type="FEEDS_INTO", direction="OUTGOING")
            ]
        if entity_id == "valve_02":
            return [
                MagicMock(entity_id="pump_01", relationship_type="FEEDS_INTO", direction="INCOMING"),
                MagicMock(entity_id="tank_03", relationship_type="CONTROLS", direction="OUTGOING")
            ]
        return []
    kg.get_neighbors.side_effect = mock_get_neighbors
    return kg

@pytest.fixture
def blast_radius_service(mock_repo, mock_kg_service):
    return BlastRadiusService(mock_repo, mock_kg_service)

def test_blast_radius_bfs_traversal(blast_radius_service, mock_repo):
    """Verify standard BFS propagation downstream and upstream."""
    mock_repo.get_analysis_by_fingerprint.return_value = None

    identity = MagicMock(tenant_id="tenant_1", workspace_id="default", user_id="operator_01")
    result = blast_radius_service.analyze_impact(
        identity=identity,
        source_entity_id="pump_01"
    )

    assert result is not None
    assert result.source_entity_id == "pump_01"
    mock_repo.save_analysis.assert_called_once()
    saved = mock_repo.save_analysis.call_args[0][0]
    
    # Check bounded traversal hit pump_01, valve_02, and tank_03
    assert len(saved.nodes) == 3
    node_ids = {n.entity_id for n in saved.nodes}
    assert "pump_01" in node_ids
    assert "valve_02" in node_ids
    assert "tank_03" in node_ids
    
    # Check distances
    valve_node = next(n for n in saved.nodes if n.entity_id == "valve_02")
    assert valve_node.distance == 1
    assert valve_node.impact_classification == ImpactClassification.DOWNSTREAM
    
    tank_node = next(n for n in saved.nodes if n.entity_id == "tank_03")
    assert tank_node.distance == 2
    
    # Check paths
    assert len(saved.paths) == 3
    path_to_tank = next(p for p in saved.paths if p.target_node_id == "tank_03")
    assert path_to_tank.ordered_path == ["pump_01", "valve_02", "tank_03"]

def test_blast_radius_max_depth_limit(blast_radius_service, mock_repo, mock_kg_service):
    """Verify the analysis respects SAGE_BLAST_RADIUS_MAX_DEPTH."""
    with patch("backend.services.blast_radius_service.SAGE_BLAST_RADIUS_MAX_DEPTH", 1):
        mock_repo.get_analysis_by_fingerprint.return_value = None
        
        identity = MagicMock(tenant_id="tenant_1", workspace_id="default", user_id="operator_01")
        blast_radius_service.analyze_impact(
            identity=identity,
            source_entity_id="pump_01"
        )
        
        saved = mock_repo.save_analysis.call_args[0][0]
        # Max depth is 1, so tank_03 (depth 2) should not be reached
        assert len(saved.nodes) == 2
        node_ids = {n.entity_id for n in saved.nodes}
        assert "tank_03" not in node_ids

def test_deterministic_fingerprint_caching(blast_radius_service, mock_repo):
    """Verify that identical inputs use fingerprinting to return cached analysis."""
    cached_analysis = BlastRadiusAnalysis(
        tenant_id="tenant_1",
        snapshot_timestamp="2026-09-17T00:00:00Z",
        analysis_id="bra_cached",
        source_entity_id="pump_01",
        input_fingerprint="abc",
        analysis_status="COMPLETED",
        nodes=[],
        paths=[],
        scope=ImpactScope(
            total_assets=0,
            total_processes=0,
            total_upstream_dependencies=0,
            total_downstream_dependencies=0
        )
    )
    mock_repo.get_analysis_by_fingerprint.return_value = cached_analysis
    
    identity = MagicMock(tenant_id="tenant_1", workspace_id="default", user_id="operator_01")
    result = blast_radius_service.analyze_impact(
        identity=identity,
        source_entity_id="pump_01"
    )
    
    # Should not traverse, should return cached
    assert result.analysis_id == "bra_cached"
    mock_repo.save_analysis.assert_not_called()

def test_isolation_no_mutations_allowed():
    """Verify Blast Radius does not contain execute/mutate capabilities."""
    methods = dir(BlastRadiusService)
    disallowed_terms = ["execute", "remediate", "revert", "action", "write_to_device"]
    for term in disallowed_terms:
        for method in methods:
            assert term not in method.lower(), f"Blast Radius MUST NOT possess execution capability: {method}"
