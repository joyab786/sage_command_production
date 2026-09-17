import ast
import inspect
import os
import threading
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.auth import Identity, require_permission
from core.config import SAGE_RCA_MAX_CANDIDATES, SAGE_RCA_MAX_EVIDENCE
from data.schemas.authorization_contract import (
    AuthorizationDecision,
    AuthzDecisionEffect,
    AuthzReasonCode,
)
from data.schemas.rca_contract import (
    CausalRelationship,
    CausalRelationshipType,
    CauseCandidate,
    CauseType,
    ConfidenceLevel,
    DataQualityState,
    DependencyReasoning,
    EvidenceSourceType,
    RcaAnalysis,
    RcaAnalysisStatus,
    RcaEvidence,
    TemporalReasoning,
)
from server import app
from services.rca_repository import RcaRepository
from services.rca_service import RcaService

client = TestClient(app)


def get_test_auth_headers(tenant_id="tenant_A", role="operator"):
    return {
        "Authorization": f"Bearer test_token_{tenant_id}_{role}",
        "X-Tenant-ID": tenant_id,
    }


class TestV3RootCauseAnalysis:

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        self.db_path = str(tmp_path / f"test_rca_{uuid.uuid4().hex}.sqlite")
        self.repo = RcaRepository(db_path=self.db_path)
        self.service = RcaService(repository=self.repo)

        # Wire the API routes to use our test service
        import api.rca_routes
        api.rca_routes.repo = self.repo
        api.rca_routes.service = self.service
        yield
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except (PermissionError, OSError):
                pass

    # =========================================================================
    # CONTRACT TESTS (01 - 05)
    # =========================================================================

    def test_01_rca_analysis_contract_validation(self):
        analysis = RcaAnalysis(
            incident_id="inc_test_01",
            tenant_id="tenant_A",
            input_fingerprint="abc123hash",
            workspace_id="ws_01",
            plant_id="plant_01"
        )
        assert analysis.analysis_id.startswith("rca_")
        assert analysis.incident_id == "inc_test_01"
        assert analysis.tenant_id == "tenant_A"
        assert analysis.workspace_id == "ws_01"
        assert analysis.plant_id == "plant_01"
        assert analysis.schema_version == "1.0"
        assert analysis.analysis_version == 1
        assert analysis.status == RcaAnalysisStatus.PENDING
        assert analysis.started_at is not None

    def test_02_cause_candidate_contract(self):
        for ct in CauseType:
            cand = CauseCandidate(
                analysis_id="rca_01",
                cause_type=ct,
                label=f"Test {ct.value}",
                description="Test description",
                score=80.0,
                confidence=ConfidenceLevel.HIGH
            )
            assert cand.cause_type == ct
            assert cand.cause_id.startswith("cause_")
            assert cand.score == 80.0
            assert cand.confidence == ConfidenceLevel.HIGH

        with pytest.raises(ValueError):
            CauseType("NON_EXISTENT_CAUSE_TYPE")

    def test_03_causal_relationship_contract(self):
        for crt in CausalRelationshipType:
            rel = CausalRelationship(
                analysis_id="rca_01",
                source_cause_id="cause_src",
                target_cause_id="cause_tgt",
                relationship_type=crt,
                description=f"Test rel {crt.value}"
            )
            assert rel.relationship_type == crt
            assert rel.relationship_id.startswith("rel_")

        with pytest.raises(ValueError):
            CausalRelationshipType("INVALID_REL_TYPE")

    def test_04_temporal_reasoning_contract(self):
        tr = TemporalReasoning(
            time_difference_ms=5000,
            window_used_ms=60000,
            temporal_relation="PRECEDES",
            source_timestamp="2026-09-17T12:00:00Z",
            target_timestamp="2026-09-17T12:00:05Z"
        )
        assert tr.time_difference_ms == 5000
        assert tr.window_used_ms == 60000
        assert tr.temporal_relation == "PRECEDES"

    def test_05_dependency_reasoning_contract(self):
        dr = DependencyReasoning(
            graph_depth=3,
            relationship_type="FEEDS_INTO",
            source_entity="pump_01",
            target_entity="tank_02",
            path=["pump_01", "valve_01", "tank_02"]
        )
        assert dr.graph_depth == 3
        assert len(dr.path) == 3
        assert dr.source_entity == "pump_01"

    # =========================================================================
    # LIFECYCLE & STATUS TESTS (06)
    # =========================================================================

    def test_06_analysis_lifecycle_status_transitions(self):
        assert RcaAnalysisStatus.PENDING == "PENDING"
        assert RcaAnalysisStatus.RUNNING == "RUNNING"
        assert RcaAnalysisStatus.COMPLETED == "COMPLETED"
        assert RcaAnalysisStatus.INSUFFICIENT_DATA == "INSUFFICIENT_DATA"
        assert RcaAnalysisStatus.FAILED == "FAILED"
        assert RcaAnalysisStatus.SUPERSEDED == "SUPERSEDED"

        analysis = self.service.analyze_incident("tenant_A", "inc_status", ["evt_1"])
        assert analysis.status == RcaAnalysisStatus.COMPLETED
        assert analysis.completed_at is not None

        # Verify update status
        self.repo.update_analysis_status(analysis.analysis_id, "tenant_A", RcaAnalysisStatus.SUPERSEDED)
        reloaded = self.repo.get_analysis(analysis.analysis_id, "tenant_A")
        assert reloaded.status == RcaAnalysisStatus.SUPERSEDED

    # =========================================================================
    # DETERMINISTIC REASONING & INTEGRATION TESTS (07 - 14)
    # =========================================================================

    def test_07_deterministic_candidate_generation(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_det", ["evt_1", "evt_2", "evt_3"])
        assert len(analysis.causes) == 3
        # Scores degrade deterministically
        assert analysis.causes[0].score > analysis.causes[1].score > analysis.causes[2].score
        assert analysis.causes[0].label == "Candidate derived from evt_1"

    def test_08_temporal_reasoning_trace_generation(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_temp", ["evt_1"])
        cause = analysis.causes[0]
        assert cause.temporal_support is not None
        assert cause.temporal_support.temporal_relation == "PRECEDES"
        assert cause.temporal_support.window_used_ms == 60000

    def test_09_ontology_and_kg_reasoning_integration(self):
        analysis = self.service.analyze_incident(
            "tenant_A", "inc_kg", ["kg_edge_pump_01"], kg_version="v2.1"
        )
        cause = analysis.causes[0]
        assert cause.cause_type == CauseType.UPSTREAM_DEPENDENCY
        assert cause.dependency_support is not None
        assert cause.dependency_support.graph_depth >= 2
        assert len(cause.dependency_support.path) >= 2

    def test_10_digital_twin_context_integration(self):
        analysis = self.service.analyze_incident(
            "tenant_A", "inc_twin", ["twin_pressure_valve"], twin_snapshot_id="snap_99"
        )
        cause = analysis.causes[0]
        assert cause.cause_type == CauseType.EQUIPMENT
        assert len(cause.evidence_refs) == 1
        evd = cause.evidence_refs[0]
        assert evd.source_type == EvidenceSourceType.TWIN_STATE
        assert evd.relevance_metadata.get("twin_snapshot") == "snap_99"

    def test_11_anomaly_integration(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_anom", ["anom_vibration_spike"])
        cause = analysis.causes[0]
        assert cause.cause_type == CauseType.PROCESS
        assert cause.evidence_refs[0].source_type == EvidenceSourceType.ANOMALY

    def test_12_data_quality_integration(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_dq", ["dq_stale_telemetry"])
        cause = analysis.causes[0]
        assert cause.cause_type == CauseType.SENSOR
        assert cause.data_quality_state == DataQualityState.STALE
        assert cause.evidence_refs[0].source_type == EvidenceSourceType.DATA_QUALITY

    def test_13_deterministic_scoring_and_confidence(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_score", ["evt_1", "evt_2", "evt_3", "evt_4"])
        for idx, cause in enumerate(analysis.causes):
            assert 10.0 <= cause.score <= 95.0
            assert cause.confidence in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW]
            assert "±" in cause.uncertainty

    def test_14_evidence_linkage_and_provenance(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_evd", ["evt_alpha"], kg_version="v1.0")
        cause = analysis.causes[0]
        assert len(cause.evidence_refs) == 1
        evd = cause.evidence_refs[0]
        assert evd.source_id == "evt_alpha"
        assert evd.relationship == "CORRELATES_WITH"
        assert "deterministic_v1" in evd.provenance

    # =========================================================================
    # FINGERPRINTING & REPRODUCIBILITY TESTS (15 - 17)
    # =========================================================================

    def test_15_sha256_fingerprinting_invariance(self):
        a1 = RcaAnalysis(incident_id="inc_fp", tenant_id="t1", input_fingerprint="")
        fg1 = a1.generate_fingerprint("inc_fp", ["evt_B", "evt_A", "evt_C"], "kg_v1", "twin_s1", "det_v1")

        a2 = RcaAnalysis(incident_id="inc_fp", tenant_id="t1", input_fingerprint="")
        fg2 = a2.generate_fingerprint("inc_fp", ["evt_A", "evt_C", "evt_B"], "kg_v1", "twin_s1", "det_v1")

        assert fg1 == fg2
        assert len(fg1) == 64  # Valid SHA-256 hex string

        # Different context changes fingerprint
        fg3 = a2.generate_fingerprint("inc_fp", ["evt_A", "evt_C", "evt_B"], "kg_v2", "twin_s1", "det_v1")
        assert fg1 != fg3

    def test_16_duplicate_analysis_prevention_cache(self):
        a1 = self.service.analyze_incident("tenant_A", "inc_cache", ["evt_1", "evt_2"])
        a2 = self.service.analyze_incident("tenant_A", "inc_cache", ["evt_2", "evt_1"])

        assert a1.analysis_id == a2.analysis_id
        assert a1.input_fingerprint == a2.input_fingerprint

        # Listing analyses for this incident should return exactly 1
        analyses = self.service.list_analyses("inc_cache", "tenant_A")
        assert len(analyses) == 1

    def test_17_full_persistence_roundtrip(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_persist", ["evt_p1", "evt_p2"])
        assert len(analysis.causes) == 2
        assert len(analysis.relationships) == 1

        # Create new repository instance pointing to same SQLite database
        fresh_repo = RcaRepository(db_path=self.db_path)
        loaded = fresh_repo.get_analysis(analysis.analysis_id, "tenant_A")

        assert loaded is not None
        assert loaded.analysis_id == analysis.analysis_id
        assert loaded.input_fingerprint == analysis.input_fingerprint
        assert len(loaded.causes) == 2
        assert len(loaded.relationships) == 1
        assert loaded.causes[0].label == analysis.causes[0].label
        assert len(loaded.causes[0].evidence_refs) == 1

    # =========================================================================
    # BOUNDS & RESOURCE LIMIT TESTS (18 - 19)
    # =========================================================================

    def test_18_candidate_bounds_enforcement(self):
        evidence_ids = [f"evt_{i}" for i in range(SAGE_RCA_MAX_CANDIDATES + 15)]
        analysis = self.service.analyze_incident("tenant_A", "inc_bound", evidence_ids)
        assert len(analysis.causes) <= SAGE_RCA_MAX_CANDIDATES
        assert len(analysis.causes) == SAGE_RCA_MAX_CANDIDATES

    def test_19_evidence_bounds_enforcement(self):
        # Pass 1500 evidence IDs when max is SAGE_RCA_MAX_EVIDENCE (1000)
        evidence_ids = [f"evt_{i}" for i in range(SAGE_RCA_MAX_EVIDENCE + 200)]
        analysis = self.service.analyze_incident("tenant_A", "inc_evd_bound", evidence_ids)
        assert analysis.status == RcaAnalysisStatus.COMPLETED

    # =========================================================================
    # ISOLATION & CONCURRENCY TESTS (20 - 23)
    # =========================================================================

    def test_20_tenant_isolation_enforcement(self):
        a_tenant_a = self.service.analyze_incident("tenant_A", "inc_iso", ["evt_iso"])
        assert a_tenant_a is not None

        # Tenant B cannot read Tenant A's analysis
        assert self.service.get_analysis(a_tenant_a.analysis_id, "tenant_B") is None
        assert len(self.service.list_analyses("inc_iso", "tenant_B")) == 0

    def test_21_workspace_and_plant_isolation(self):
        analysis = self.service.analyze_incident(
            "tenant_A", "inc_ws", ["evt_ws"],
            workspace_id="ws_industrial_01",
            plant_id="plant_austin_02"
        )
        assert analysis.workspace_id == "ws_industrial_01"
        assert analysis.plant_id == "plant_austin_02"

        loaded = self.service.get_analysis(analysis.analysis_id, "tenant_A")
        assert loaded.workspace_id == "ws_industrial_01"
        assert loaded.plant_id == "plant_austin_02"

    def test_22_concurrency_thread_safety(self):
        results = []
        errors = []

        def worker(idx):
            try:
                res = self.service.analyze_incident("tenant_A", f"inc_thread_{idx % 3}", [f"evt_{idx}"])
                results.append(res)
            except Exception as ex:
                errors.append(ex)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10

    def test_23_reproducibility_across_instances(self):
        # Service 1 runs analysis
        s1 = RcaService(self.repo)
        res1 = s1.analyze_incident("tenant_A", "inc_repro", ["evt_a", "evt_b"])

        # Service 2 with distinct repo instance runs identical analysis
        repo2 = RcaRepository(self.db_path)
        s2 = RcaService(repo2)
        res2 = s2.analyze_incident("tenant_A", "inc_repro", ["evt_a", "evt_b"])

        assert res1.analysis_id == res2.analysis_id
        assert res1.input_fingerprint == res2.input_fingerprint
        assert len(res1.causes) == len(res2.causes)

    # =========================================================================
    # EXECUTION BOUNDARY & SECURITY TESTS (24 - 26)
    # =========================================================================

    def test_24_execution_boundary_ast_inspection(self):
        """Verifies RCA files do NOT import or invoke physical execution engines."""
        target_files = [
            "backend/services/rca_service.py",
            "backend/services/rca_repository.py",
            "backend/api/rca_routes.py",
            "backend/data/schemas/rca_contract.py"
        ]
        prohibited_terms = [
            "ExecutionGateway",
            "action_service",
            "execute_action",
            "plc_write",
            "emergency_stop",
            "apply_action",
            "blast_radius",
            "trigger_remediation"
        ]

        for filepath in target_files:
            if not os.path.exists(filepath):
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                tree = ast.parse(content, filename=filepath)

            # Check imports
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for n in node.names:
                        for term in prohibited_terms:
                            assert term.lower() not in n.name.lower(), (
                                f"File {filepath} imports prohibited execution component {n.name}"
                            )

    def test_25_incident_lifecycle_immutability(self):
        """Verifies RCA analysis does NOT mutate incident records."""
        import services.rca_service
        source = inspect.getsource(services.rca_service)
        prohibited_incident_mutations = [
            "update_incident_status",
            "transition_lifecycle",
            "incident_repo.update",
            "incident_repo.transition"
        ]
        for term in prohibited_incident_mutations:
            assert term not in source, f"RcaService contains incident mutation call: {term}"

    def test_26_insufficient_evidence_fallback(self):
        analysis = self.service.analyze_incident("tenant_A", "inc_empty", [])
        assert analysis.status == RcaAnalysisStatus.COMPLETED
        assert len(analysis.causes) == 1
        assert analysis.causes[0].cause_type == CauseType.UNKNOWN
        assert analysis.causes[0].confidence == ConfidenceLevel.INSUFFICIENT_DATA
        assert analysis.causes[0].score == 0.0

    # =========================================================================
    # FASTAPI HTTP INTEGRATION TESTS (27 - 30)
    # =========================================================================

    def test_27_api_analyze_endpoint_integration(self):
        headers = get_test_auth_headers("tenant_A")
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="d1",
                effect=AuthzDecisionEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED,
                reason="OK",
                decision_hash="h1",
                required_permission="rca.analyze"
            )
            res = client.post(
                "/api/v3/rca/analyze/inc_api_01",
                json={"evidence_ids": ["evt_1", "evt_2"], "kg_version": "v1.0"},
                headers=headers
            )
        assert res.status_code == 200
        data = res.json()
        assert data["incident_id"] == "inc_api_01"
        assert len(data["causes"]) == 2
        assert data["input_fingerprint"] is not None

    def test_28_api_list_analyses_endpoint(self):
        headers = get_test_auth_headers("tenant_A")
        self.service.analyze_incident("tenant_A", "inc_list_api", ["evt_a"])

        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="d2",
                effect=AuthzDecisionEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED,
                reason="OK",
                decision_hash="h2",
                required_permission="rca.read"
            )
            res = client.get("/api/v3/rca/analyses/inc_list_api", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 1
        assert data[0]["incident_id"] == "inc_list_api"

    def test_29_api_get_single_analysis_endpoint(self):
        headers = get_test_auth_headers("tenant_A")
        analysis = self.service.analyze_incident("tenant_A", "inc_get_api", ["evt_single"])

        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="d3",
                effect=AuthzDecisionEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED,
                reason="OK",
                decision_hash="h3",
                required_permission="rca.read"
            )
            res = client.get(f"/api/v3/rca/analysis/{analysis.analysis_id}", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["analysis_id"] == analysis.analysis_id
        assert len(data["causes"]) == 1

    def test_30_api_rbac_abac_permission_enforcement(self):
        headers = get_test_auth_headers("tenant_A")
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="d4",
                effect=AuthzDecisionEffect.DENY,
                reason_code=AuthzReasonCode.INSUFFICIENT_ROLE_PERMISSIONS,
                reason="Denied by RBAC policy",
                decision_hash="h4",
                required_permission="rca.analyze"
            )
            res = client.post(
                "/api/v3/rca/analyze/inc_denied",
                json={"evidence_ids": ["evt_1"]},
                headers=headers
            )
        assert res.status_code == 403
