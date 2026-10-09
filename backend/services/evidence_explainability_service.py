# backend/services/evidence_explainability_service.py
"""
SageCommand V3 — Evidence and Explainability Intelligence Foundation Service (Prompt 31)

ANALYTICAL EXPLAINABILITY AND EVIDENCE TRACING ONLY.
Orchestrates deterministic evidence identification, linkage, validation,
provenance tracking, lineage graph construction, and decision-level explanations.

Cardinal Invariant:
An explanation describes the evidence and reasoning behind an outcome.
It does NOT authorize an action, change a decision policy, or execute a recommendation.
The Evidence and Explainability layer is a READ-ONLY analytical integration layer.
It NEVER mutates underlying operational or source subsystem records.

Boundary:
EVIDENCE EXPLAINABILITY -> READ-ONLY REASONING TRACE -> HUMAN INSPECTION / REVIEW
Never: EVIDENCE EXPLAINABILITY -> OPERATIONAL EXECUTION / ACTUATION.
"""

import math
import hashlib
import json
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime, timezone, timedelta

try:
    from core.config import (
        SAGE_EXPLAINABILITY_MAX_GRAPH_DEPTH,
        SAGE_EXPLAINABILITY_MAX_NODES,
        SAGE_EXPLAINABILITY_MAX_EDGES,
        SAGE_EXPLAINABILITY_MAX_EVIDENCE_ITEMS,
        SAGE_EXPLAINABILITY_DEFAULT_FRESHNESS_SECONDS,
    )
    from data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceReference,
        EvidenceSourceType,
        EvidenceProvenance,
        EvidenceValidationStatus,
        LineageEdgeType,
        ExplanationNodeType,
        ExplanationEdgeRelation,
        SeverityLevel,
        GapType,
        ConflictType,
        EvidenceTransformation,
        EvidenceLineageEdge,
        EvidenceLineageGraph,
        EvidenceFreshnessAssessment,
        EvidenceRejection,
        EvidenceConflict,
        EvidenceGap,
        EvidenceValidationResult,
        EvidenceContribution,
        ExplanationNode,
        ExplanationEdge,
        ExplanationGraph,
        ExplanationLimitation,
        ExplanationRequest,
        EvidenceValidationRequest,
        EvidenceValidationBatchResponse,
        ExplanationResult,
        ExplanationSummary,
        compute_explanation_fingerprint,
        compute_evidence_record_fingerprint,
        MANDATORY_EXPLAINABILITY_NOTICE,
        ALGORITHM_VERSION,
        CONTRACT_VERSION,
    )
    from repositories.evidence_explainability_repository import (
        EvidenceExplainabilityRepository,
        evidence_explainability_repository,
    )
    from repositories.decision_engine_repository import decision_engine_repository
    from repositories.optimization_repository import optimization_repository
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_EXPLAINABILITY_MAX_GRAPH_DEPTH,
        SAGE_EXPLAINABILITY_MAX_NODES,
        SAGE_EXPLAINABILITY_MAX_EDGES,
        SAGE_EXPLAINABILITY_MAX_EVIDENCE_ITEMS,
        SAGE_EXPLAINABILITY_DEFAULT_FRESHNESS_SECONDS,
    )
    from backend.data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceReference,
        EvidenceSourceType,
        EvidenceProvenance,
        EvidenceValidationStatus,
        LineageEdgeType,
        ExplanationNodeType,
        ExplanationEdgeRelation,
        SeverityLevel,
        GapType,
        ConflictType,
        EvidenceTransformation,
        EvidenceLineageEdge,
        EvidenceLineageGraph,
        EvidenceFreshnessAssessment,
        EvidenceRejection,
        EvidenceConflict,
        EvidenceGap,
        EvidenceValidationResult,
        EvidenceContribution,
        ExplanationNode,
        ExplanationEdge,
        ExplanationGraph,
        ExplanationLimitation,
        ExplanationRequest,
        EvidenceValidationRequest,
        EvidenceValidationBatchResponse,
        ExplanationResult,
        ExplanationSummary,
        compute_explanation_fingerprint,
        compute_evidence_record_fingerprint,
        MANDATORY_EXPLAINABILITY_NOTICE,
        ALGORITHM_VERSION,
        CONTRACT_VERSION,
    )
    from backend.repositories.evidence_explainability_repository import (
        EvidenceExplainabilityRepository,
        evidence_explainability_repository,
    )
    from backend.repositories.decision_engine_repository import decision_engine_repository
    from backend.repositories.optimization_repository import optimization_repository


# =============================================================================
# 1. READ-ONLY UPSTREAM SUBSYSTEM ADAPTERS
# =============================================================================

class SubsystemEvidenceAdapterRegistry:
    """
    Registry of small, explicit read-only adapters around upstream contracts and repositories.
    Preserves true provenance and source assessment metadata without inventing values.
    """

    @staticmethod
    def get_source_record(
        source_type: EvidenceSourceType,
        record_id: str,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves source record payload from appropriate repository enforcing tenant isolation.
        Strictly read-only.
        """
        try:
            if source_type == EvidenceSourceType.DECISION_ENGINE:
                res = decision_engine_repository.get_by_id(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.OPTIMIZATION:
                res = optimization_repository.get_result_by_id(record_id, tenant_id)
                if res:
                    return res.model_dump()
                prob = optimization_repository.get_problem_by_id(record_id, tenant_id)
                return prob.model_dump() if prob else None

            elif source_type == EvidenceSourceType.WHAT_IF_SIMULATION:
                try:
                    from services.what_if_simulation_repository import what_if_simulation_repository as w_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.what_if_simulation_repository import what_if_simulation_repository as w_repo
                res = w_repo.get_result_by_id(record_id, tenant_id)
                if res:
                    return res.model_dump()
                scen = w_repo.get_scenario_by_id(record_id, tenant_id)
                return scen.model_dump() if scen else None

            elif source_type == EvidenceSourceType.SENSOR_FUSION:
                try:
                    from services.sensor_fusion_repository import sensor_fusion_repository as sf_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.sensor_fusion_repository import sensor_fusion_repository as sf_repo
                res = sf_repo.get_assessment_by_id(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.PREDICTIVE_MAINTENANCE:
                try:
                    from services.predictive_maintenance_repository import predictive_maintenance_repository as pm_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.predictive_maintenance_repository import predictive_maintenance_repository as pm_repo
                res = pm_repo.get_assessment_by_id(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.DEMAND_FORECASTING:
                try:
                    from services.demand_forecasting_repository import demand_forecasting_repository as df_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.demand_forecasting_repository import demand_forecasting_repository as df_repo
                res = df_repo.get_forecast_by_id(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.ROOT_CAUSE_ANALYSIS:
                try:
                    from services.rca_repository import RcaRepository
                    from core.config import SAGE_RCA_DB_PATH
                    r_repo = RcaRepository(SAGE_RCA_DB_PATH)
                except Exception:
                    try:
                        from backend.services.rca_repository import RcaRepository
                        from backend.core.config import SAGE_RCA_DB_PATH
                        r_repo = RcaRepository(SAGE_RCA_DB_PATH)
                    except Exception:
                        r_repo = None
                if r_repo:
                    res = r_repo.get_analysis(record_id, tenant_id)
                    return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.BLAST_RADIUS:
                try:
                    from services.blast_radius_repository import blast_radius_repository as br_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.blast_radius_repository import blast_radius_repository as br_repo
                res = br_repo.get_analysis(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.INCIDENT_MANAGEMENT:
                try:
                    from services.incident_repository import incident_repository as inc_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.incident_repository import incident_repository as inc_repo
                res = inc_repo.get_incident(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.DATA_QUALITY:
                try:
                    from services.data_quality_repository import data_quality_repository as dq_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.data_quality_repository import data_quality_repository as dq_repo
                res = dq_repo.get_assessment(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.ANOMALY_DETECTION:
                try:
                    from services.anomaly_repository import anomaly_repository as an_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.anomaly_repository import anomaly_repository as an_repo
                res = an_repo.get_anomaly(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.SUPPLIER_RISK:
                try:
                    from services.supplier_risk_repository import supplier_risk_repository as sup_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.supplier_risk_repository import supplier_risk_repository as sup_repo
                res = sup_repo.get_assessment(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.SLA_CUSTOMER_RISK:
                try:
                    from services.sla_customer_risk_repository import sla_customer_risk_repository as sla_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.sla_customer_risk_repository import sla_customer_risk_repository as sla_repo
                res = sla_repo.get_assessment(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.FINANCIAL_IMPACT:
                try:
                    from services.financial_impact_repository import financial_impact_repository as fi_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.financial_impact_repository import financial_impact_repository as fi_repo
                res = fi_repo.get_assessment(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.SUSTAINABILITY:
                try:
                    from services.sustainability_repository import sustainability_repository as sust_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.sustainability_repository import sustainability_repository as sust_repo
                res = sust_repo.get_assessment(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.DIGITAL_TWIN:
                try:
                    from services.digital_twin_repository import digital_twin_repository as dt_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.digital_twin_repository import digital_twin_repository as dt_repo
                res = dt_repo.get_snapshot(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.OPERATIONAL_KNOWLEDGE_GRAPH:
                try:
                    from services.knowledge_graph_repository import knowledge_graph_repository as kg_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.knowledge_graph_repository import knowledge_graph_repository as kg_repo
                res = kg_repo.get_fact(record_id, tenant_id)
                return res.model_dump() if res else None

            elif source_type == EvidenceSourceType.INDUSTRIAL_ONTOLOGY:
                try:
                    from services.ontology_repository import ontology_repository as ont_repo
                except (ImportError, ModuleNotFoundError):
                    from backend.services.ontology_repository import ontology_repository as ont_repo
                res = ont_repo.get_entity(record_id, tenant_id)
                return res.model_dump() if res else None

        except Exception:
            return None

        return None



# =============================================================================
# 2. EVIDENCE VALIDATION & FRESHNESS ENGINE
# =============================================================================

class EvidenceValidationEngine:
    """
    Deterministic validation pipeline for evidence items.
    Checks:
    1. Scope isolation (tenant, workspace, plant).
    2. Temporal validity (no future-dated evidence relative to assessment timestamp).
    3. Freshness against configured threshold.
    4. Provenance consistency (never mislabel simulation/forecast as observed).
    5. Data quality score threshold.
    6. Identification of contradictions or incompatible semantics.
    """

    @staticmethod
    def validate_item(
        ev: EvidenceRecord,
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str],
        assessment_ts: str,
        freshness_threshold_seconds: float,
        verify_source_existence: bool = False,
    ) -> Tuple[EvidenceValidationResult, Optional[EvidenceRejection]]:
        rejections: List[str] = []
        is_valid = True
        status = EvidenceValidationStatus.VALID

        # Scope Check
        if ev.tenant_id != tenant_id:
            return (
                EvidenceValidationResult(
                    evidence_id=ev.evidence_id,
                    status=EvidenceValidationStatus.INACCESSIBLE,
                    is_valid=False,
                    rejection_reasons=["CROSS_TENANT_ISOLATION_VIOLATION"],
                    evaluated_at=assessment_ts,
                    details={"error": "Tenant scope mismatch"},
                ),
                EvidenceRejection(
                    evidence_id=ev.evidence_id,
                    reason_code="CROSS_TENANT_ISOLATION_VIOLATION",
                    explanation="Evidence item belongs to a different tenant partition.",
                    severity=SeverityLevel.BLOCKING,
                ),
            )

        if plant_id and ev.plant_id and ev.plant_id != plant_id:
            rejections.append("PLANT_SCOPE_MISMATCH")
            status = EvidenceValidationStatus.INVALID
            is_valid = False

        # Parse assessment timestamp
        try:
            assess_dt = datetime.fromisoformat(assessment_ts.replace("Z", "+00:00"))
            if assess_dt.tzinfo is None:
                assess_dt = assess_dt.replace(tzinfo=timezone.utc)
        except Exception:
            assess_dt = datetime.now(timezone.utc)

        # Temporal Validity Check (No future leakage)
        ts_to_check = ev.observed_at or ev.assessed_at or ev.received_at
        is_future = False
        age_seconds = 0.0

        if ts_to_check:
            try:
                ev_dt = datetime.fromisoformat(ts_to_check.replace("Z", "+00:00"))
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)

                if ev_dt > assess_dt:
                    is_future = True
                    is_valid = False
                    status = EvidenceValidationStatus.INVALID
                    rejections.append("FUTURE_DATED_EVIDENCE")
                else:
                    age_seconds = max(0.0, (assess_dt - ev_dt).total_seconds())
            except Exception:
                pass

        if ev.freshness_seconds is not None:
            age_seconds = max(age_seconds, ev.freshness_seconds)

        # Freshness Check
        is_fresh = age_seconds <= freshness_threshold_seconds
        if not is_fresh and not is_future:
            status = EvidenceValidationStatus.STALE
            rejections.append("STALE_EVIDENCE")
            # Stale evidence may still be partially included with warning

        # Data Quality Check
        if ev.quality_score < 0.3:
            rejections.append("LOW_DATA_QUALITY")
            status = EvidenceValidationStatus.INVALID
            is_valid = False

        # Verify source existence if enabled
        if verify_source_existence:
            source_rec = SubsystemEvidenceAdapterRegistry.get_source_record(
                ev.source_type, ev.source_record_id, tenant_id
            )
            if not source_rec:
                rejections.append("SOURCE_RECORD_UNVERIFIED")
                if status == EvidenceValidationStatus.VALID:
                    status = EvidenceValidationStatus.MISSING

        freshness_assessment = EvidenceFreshnessAssessment(
            evidence_id=ev.evidence_id,
            observed_at=ev.observed_at,
            assessed_at=assessment_ts,
            age_seconds=round(age_seconds, 2),
            freshness_threshold_seconds=freshness_threshold_seconds,
            is_fresh=is_fresh,
            is_future_dated=is_future,
        )

        rejection_obj: Optional[EvidenceRejection] = None
        if rejections:
            rejection_obj = EvidenceRejection(
                evidence_id=ev.evidence_id,
                reason_code=rejections[0],
                explanation=f"Evidence failed validation criteria: {', '.join(rejections)}.",
                severity=SeverityLevel.BLOCKING if is_future else SeverityLevel.MEDIUM,
            )

        val_result = EvidenceValidationResult(
            evidence_id=ev.evidence_id,
            status=status,
            is_valid=is_valid and status in (EvidenceValidationStatus.VALID, EvidenceValidationStatus.STALE),
            rejection_reasons=rejections,
            freshness_assessment=freshness_assessment,
            evaluated_at=assessment_ts,
            details={
                "age_hours": round(age_seconds / 3600.0, 2),
                "quality_score": ev.quality_score,
                "provenance": ev.provenance.value,
            },
        )
        return val_result, rejection_obj

    @staticmethod
    def detect_conflicts(evidence_items: List[EvidenceRecord]) -> List[EvidenceConflict]:
        """
        Detects contradictory observations or incompatible semantics across evidence items.
        """
        conflicts: List[EvidenceConflict] = []
        # Group evidence by source_record_id or shared asset/parameter
        by_record: Dict[str, List[EvidenceRecord]] = {}
        for ev in evidence_items:
            key = f"{ev.source_type.value}:{ev.source_record_id}"
            by_record.setdefault(key, []).append(ev)

        for key, group in by_record.items():
            if len(group) > 1:
                # Check for conflicting provenance or values
                provenances = {g.provenance for g in group}
                if len(provenances) > 1 and EvidenceProvenance.OBSERVED in provenances and EvidenceProvenance.SIMULATED in provenances:
                    conflict_id = f"conf_prov_{hashlib.sha256(key.encode()).hexdigest()[:12]}"
                    conflicts.append(
                        EvidenceConflict(
                            conflict_id=conflict_id,
                            evidence_ids=[g.evidence_id for g in group],
                            conflict_type=ConflictType.UNRESOLVED_DISAGREEMENT,
                            description=f"Conflicting provenance types observed for record {key}: {sorted([p.value for p in provenances])}.",
                            severity=SeverityLevel.MEDIUM,
                        )
                    )

        return conflicts


# =============================================================================
# 3. EVIDENCE LINEAGE GRAPH TRAVERSAL & BUILDER
# =============================================================================

class EvidenceLineageGraphBuilder:
    """
    Builds bounded, deterministic, cycle-free evidence lineage graphs.
    Enforces maximum depth, maximum node count, and tenant boundaries.
    """

    @staticmethod
    def build_lineage_graph(
        root_id: str,
        initial_evidence: List[EvidenceRecord],
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str] = None,
        max_depth: int = SAGE_EXPLAINABILITY_MAX_GRAPH_DEPTH,
        max_nodes: int = SAGE_EXPLAINABILITY_MAX_NODES,
        max_edges: int = SAGE_EXPLAINABILITY_MAX_EDGES,
    ) -> Tuple[EvidenceLineageGraph, List[EvidenceGap]]:
        nodes_dict: Dict[str, EvidenceRecord] = {}
        edges_list: List[EvidenceLineageEdge] = []
        unresolved_refs: List[str] = []
        gaps: List[EvidenceGap] = []
        has_cycles = False
        is_truncated = False

        # Populate initial evidence
        for ev in initial_evidence:
            if ev.tenant_id == tenant_id:
                if not plant_id or not ev.plant_id or ev.plant_id == plant_id:
                    nodes_dict[ev.evidence_id] = ev

        # Cycle detection using 3-color DFS
        has_cycles = False
        color: Dict[str, int] = {}  # 0: white, 1: gray (visiting), 2: black (done)

        def dfs_detect_cycle(u: str) -> bool:
            color[u] = 1
            node = nodes_dict.get(u)
            if node:
                for p in node.parent_evidence_ids:
                    if p == u:
                        return True
                    if p in nodes_dict:
                        if color.get(p, 0) == 1:
                            return True
                        if color.get(p, 0) == 0:
                            if dfs_detect_cycle(p):
                                return True
            color[u] = 2
            return False

        for nid in list(nodes_dict.keys()):
            if color.get(nid, 0) == 0:
                if dfs_detect_cycle(nid):
                    has_cycles = True
                    break

        # Traversal queues and visited tracking
        visited_edges: Set[Tuple[str, str, str]] = set()

        # Build adjacency maps for bidirectional navigation
        parents_map: Dict[str, List[str]] = {nid: list(node.parent_evidence_ids) for nid, node in nodes_dict.items()}
        children_map: Dict[str, List[str]] = {nid: [] for nid in nodes_dict}
        for nid, plist in parents_map.items():
            for p in plist:
                if p in children_map:
                    children_map[p].append(nid)

        # Depth-bounded BFS from root_id
        if root_id in nodes_dict:
            frontier = [root_id]
            visited_nodes: Set[str] = {root_id}
        else:
            frontier = list(nodes_dict.keys())
            visited_nodes = set(frontier)

        current_depth = 0

        while frontier and current_depth < max_depth:
            next_frontier: List[str] = []
            layer_added_nodes = False

            for u in frontier:
                # Upstream exploration (towards parents)
                node_u = nodes_dict.get(u)
                if not node_u:
                    continue

                for p in node_u.parent_evidence_ids:
                    if p not in nodes_dict:
                        unresolved_refs.append(p)
                        gaps.append(
                            EvidenceGap(
                                gap_id=f"gap_parent_{p[:12]}",
                                target_type="EVIDENCE_RECORD",
                                target_id=p,
                                description=f"Parent evidence {p} referenced by {u} is unresolved in current scope.",
                                gap_type=GapType.MISSING_PARENT,
                                impact="Lineage branch terminated early.",
                            )
                        )
                    else:
                        edge_type = LineageEdgeType.SIMULATED_FROM if node_u.provenance == EvidenceProvenance.SIMULATED else LineageEdgeType.DERIVED_FROM
                        edge_id = f"edge_{p[:8]}_{u[:8]}"
                        edge_key = (p, u, edge_type.value)
                        if edge_key not in visited_edges and len(edges_list) < max_edges:
                            visited_edges.add(edge_key)
                            trans = node_u.transformations[0] if node_u.transformations else None
                            edges_list.append(
                                EvidenceLineageEdge(
                                    edge_id=edge_id,
                                    source_evidence_id=p,
                                    target_evidence_id=u,
                                    edge_type=edge_type,
                                    transformation=trans,
                                    weight=1.0,
                                )
                            )
                        if p not in visited_nodes:
                            if len(visited_nodes) < max_nodes:
                                visited_nodes.add(p)
                                next_frontier.append(p)
                                layer_added_nodes = True
                            else:
                                is_truncated = True

                # Downstream exploration (towards children)
                for c in children_map.get(u, []):
                    child_node = nodes_dict[c]
                    edge_type = LineageEdgeType.SIMULATED_FROM if child_node.provenance == EvidenceProvenance.SIMULATED else LineageEdgeType.DERIVED_FROM
                    edge_id = f"edge_{u[:8]}_{c[:8]}"
                    edge_key = (u, c, edge_type.value)
                    if edge_key not in visited_edges and len(edges_list) < max_edges:
                        visited_edges.add(edge_key)
                        trans = child_node.transformations[0] if child_node.transformations else None
                        edges_list.append(
                            EvidenceLineageEdge(
                                edge_id=edge_id,
                                source_evidence_id=u,
                                target_evidence_id=c,
                                edge_type=edge_type,
                                transformation=trans,
                                weight=1.0,
                            )
                        )
                    if c not in visited_nodes:
                        if len(visited_nodes) < max_nodes:
                            visited_nodes.add(c)
                            next_frontier.append(c)
                            layer_added_nodes = True
                        else:
                            is_truncated = True

            if layer_added_nodes or (not next_frontier and current_depth == 0 and len(visited_nodes) > 1):
                current_depth += 1
            frontier = next_frontier

        # Include nodes that were visited
        included_nodes = [nodes_dict[nid] for nid in visited_nodes if nid in nodes_dict]
        if len(included_nodes) > max_nodes:
            included_nodes = included_nodes[:max_nodes]
            is_truncated = True

        # Deterministic sorting of nodes and edges
        sorted_nodes = sorted(included_nodes, key=lambda n: n.evidence_id)
        sorted_edges = sorted(edges_list, key=lambda e: (e.source_evidence_id, e.target_evidence_id, e.edge_type.value))

        # Fingerprint of graph
        graph_dict = {
            "root_id": root_id,
            "tenant_id": tenant_id,
            "node_ids": [n.evidence_id for n in sorted_nodes],
            "edge_ids": [e.edge_id for e in sorted_edges],
            "has_cycles": has_cycles,
        }
        graph_fingerprint = hashlib.sha256(json.dumps(graph_dict, sort_keys=True).encode("utf-8")).hexdigest()

        graph = EvidenceLineageGraph(
            graph_id=f"lg_{graph_fingerprint[:16]}",
            root_id=root_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            nodes=sorted_nodes,
            edges=sorted_edges,
            depth=current_depth,
            fingerprint=graph_fingerprint,
            has_cycles=has_cycles,
            unresolved_references=sorted(list(set(unresolved_refs))),
            is_truncated=is_truncated,
        )
        return graph, gaps


# =============================================================================
# 4. DECISION ENGINE EXPLAINABILITY BUILDER
# =============================================================================

class DecisionExplainabilityBuilder:
    """
    Constructs comprehensive explanation graphs and traces for Decision Engine evaluations (Prompt 30).
    Maps recommendations, candidate alternatives, criteria scores, constraint violations,
    policy checks, and underlying evidence references without altering original evaluations.
    """

    @staticmethod
    def explain_decision(
        decision_data: Dict[str, Any],
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str],
        assessment_ts: str,
        freshness_threshold: float,
    ) -> Tuple[
        str,  # summary
        Dict[str, Any],  # recommendation_or_conclusion
        List[EvidenceRecord],  # supporting_evidence
        List[EvidenceRecord],  # excluded_evidence
        List[EvidenceValidationResult],
        List[EvidenceContribution],
        List[EvidenceRejection],
        List[EvidenceConflict],
        List[EvidenceGap],
        List[ExplanationLimitation],
        ExplanationGraph,
    ]:
        decision_id = decision_data.get("decision_id", "unknown_dec")
        decision_type = decision_data.get("decision_type", "GENERAL")
        status = decision_data.get("status", "RECOMMENDED")
        recommendation = decision_data.get("recommendation", {})
        recommended_opt_id = recommendation.get("recommended_option_id")
        primary_rationale = recommendation.get("primary_rationale", "Deterministic evaluation completed.")

        alternatives = recommendation.get("alternatives", [])
        criterion_evaluations = decision_data.get("criterion_evaluations", [])
        constraint_evaluations = decision_data.get("constraint_evaluations", [])
        policy_evaluations = decision_data.get("policy_evaluations", [])
        evidence_snapshot = decision_data.get("evidence_snapshot", [])
        original_limitations = decision_data.get("limitations", [])

        # Convert evidence snapshot to EvidenceRecord models
        supporting_evidence: List[EvidenceRecord] = []
        excluded_evidence: List[EvidenceRecord] = []
        validations: List[EvidenceValidationResult] = []
        rejections: List[EvidenceRejection] = []
        limitations: List[ExplanationLimitation] = []
        gaps: List[EvidenceGap] = []

        # Convert original limitations
        for l in original_limitations:
            limitations.append(
                ExplanationLimitation(
                    limitation_id=l.get("limitation_id", f"lim_{decision_id[:8]}"),
                    code=l.get("code", "DECISION_LIMITATION"),
                    description=l.get("description", "Identified limitation"),
                    severity=SeverityLevel(l.get("severity", "MEDIUM")) if l.get("severity") in ("LOW", "MEDIUM", "HIGH", "BLOCKING") else SeverityLevel.MEDIUM,
                    mitigation=l.get("mitigation"),
                )
            )

        # Process each evidence item in snapshot
        for item in evidence_snapshot:
            ev_id = item.get("evidence_id", f"ev_{decision_id[:8]}")
            src_sys = item.get("source_subsystem", "UNKNOWN").upper()
            src_rec_id = item.get("source_record_id", ev_id)
            ts = item.get("timestamp", assessment_ts)
            prov_str = item.get("provenance", "OBSERVED")
            try:
                prov = EvidenceProvenance(prov_str)
            except ValueError:
                prov = EvidenceProvenance.UNKNOWN

            # Map source subsystem string to EvidenceSourceType
            src_type = EvidenceSourceType.EXTERNAL_SYSTEM
            for st in EvidenceSourceType:
                if st.value in src_sys or src_sys in st.value:
                    src_type = st
                    break

            ev_record = EvidenceRecord(
                evidence_id=ev_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                plant_id=plant_id or item.get("plant_id"),
                source_type=src_type,
                source_record_id=src_rec_id,
                title=f"Evidence for {src_sys} ({src_rec_id})",
                description=f"Extracted from {src_sys} supporting decision {decision_id}.",
                observed_at=ts,
                assessed_at=assessment_ts,
                provenance=prov,
                quality_score=float(item.get("quality_score", 1.0)),
                freshness_seconds=float(item.get("freshness_seconds")) if item.get("freshness_seconds") is not None else None,
                confidence_score=float(item.get("confidence", 1.0)),
                fingerprint=hashlib.sha256(f"{ev_id}:{src_rec_id}:{ts}".encode()).hexdigest(),
                payload=item.get("details", {}),
            )

            # Validate evidence
            val_res, rej_obj = EvidenceValidationEngine.validate_item(
                ev_record,
                tenant_id,
                workspace_id,
                plant_id,
                assessment_ts,
                freshness_threshold,
            )
            validations.append(val_res)

            if val_res.is_valid:
                supporting_evidence.append(ev_record)
            else:
                excluded_evidence.append(ev_record)
                if rej_obj:
                    rejections.append(rej_obj)

        if not supporting_evidence and not excluded_evidence:
            gaps.append(
                EvidenceGap(
                    gap_id=f"gap_no_evidence_{decision_id[:8]}",
                    target_type="DECISION_ENGINE",
                    target_id=decision_id,
                    description="No evidence snapshot attached to this decision evaluation.",
                    gap_type=GapType.INSUFFICIENT_COVERAGE,
                    impact="Explanation relies solely on declared option parameters and criteria weights.",
                )
            )

        # Detect conflicts among evidence items
        conflicts = EvidenceValidationEngine.detect_conflicts(supporting_evidence + excluded_evidence)

        # Build criterion contributions
        contributions: List[EvidenceContribution] = []
        for ce in criterion_evaluations:
            cid = ce.get("criterion_id", "c_unknown")
            oid = ce.get("option_id", "opt_unknown")
            weighted_s = float(ce.get("weighted_score", 0.0))
            raw_v = float(ce.get("raw_value", 0.0))

            # Match evidence supporting this criterion
            matching_ev = [e for e in supporting_evidence if cid in str(e.payload) or cid in e.evidence_id]
            ev_id_to_use = matching_ev[0].evidence_id if matching_ev else (supporting_evidence[0].evidence_id if supporting_evidence else f"ev_synth_{cid}")

            contributions.append(
                EvidenceContribution(
                    evidence_id=ev_id_to_use,
                    target_id=oid,
                    target_type="DECISION_ALTERNATIVE",
                    criterion_id=cid,
                    option_id=oid,
                    weight=round(weighted_s, 4),
                    contribution_score=round(weighted_s, 4),
                    explanation=f"Criterion '{cid}' for option '{oid}' raw value: {raw_v}, weighted score: {round(weighted_s, 4)}.",
                )
            )

        # Build Explanation Graph
        exp_nodes: List[ExplanationNode] = []
        exp_edges: List[ExplanationEdge] = []

        # Root Node: Decision Outcome
        exp_nodes.append(
            ExplanationNode(
                node_id=f"node_dec_{decision_id}",
                node_type=ExplanationNodeType.TARGET,
                title=f"Decision {decision_id} ({decision_type})",
                provenance=EvidenceProvenance.DERIVED,
                status=status,
                metadata={"status": status, "recommended_option_id": recommended_opt_id},
            )
        )

        # Option Nodes (Alternatives)
        for alt in alternatives:
            opt_id = alt.get("option_id", "opt_unknown")
            opt_name = alt.get("option_name", opt_id)
            comp_score = float(alt.get("composite_score", 0.0))
            is_rec = bool(alt.get("is_recommended", False))
            is_feas = bool(alt.get("is_feasible", True))
            is_pol = bool(alt.get("is_policy_compliant", True))

            opt_status = "RECOMMENDED" if is_rec else ("FEASIBLE" if is_feas and is_pol else "REJECTED")

            exp_nodes.append(
                ExplanationNode(
                    node_id=f"node_opt_{opt_id}",
                    node_type=ExplanationNodeType.OPTION,
                    title=f"{opt_name} (Rank {alt.get('rank', 1)})",
                    provenance=EvidenceProvenance.DERIVED,
                    status=opt_status,
                    score=comp_score,
                    metadata={
                        "binding_constraints": alt.get("binding_constraints", []),
                        "violations": alt.get("violations", []),
                        "is_feasible": is_feas,
                        "is_policy_compliant": is_pol,
                    },
                )
            )

            # Edge from Option to Decision
            rel = ExplanationEdgeRelation.SUPPORTS if is_rec else ExplanationEdgeRelation.EVALUATES
            exp_edges.append(
                ExplanationEdge(
                    edge_id=f"edge_opt_dec_{opt_id}",
                    from_node_id=f"node_opt_{opt_id}",
                    to_node_id=f"node_dec_{decision_id}",
                    relation=rel,
                    weight=comp_score,
                    notes=f"Option score: {comp_score}, status: {opt_status}.",
                )
            )

        # Constraint Nodes
        for ce in constraint_evaluations:
            cid = ce.get("constraint_id", "cn_unknown")
            oid = ce.get("option_id", "opt_unknown")
            sat = bool(ce.get("satisfied", True))
            exp_nodes.append(
                ExplanationNode(
                    node_id=f"node_cn_{cid}_{oid}",
                    node_type=ExplanationNodeType.CONSTRAINT,
                    title=f"Constraint {cid}",
                    provenance=EvidenceProvenance.DERIVED,
                    status="SATISFIED" if sat else "VIOLATED",
                    metadata={"explanation": ce.get("explanation", "")},
                )
            )
            exp_edges.append(
                ExplanationEdge(
                    edge_id=f"edge_cn_opt_{cid}_{oid}",
                    from_node_id=f"node_cn_{cid}_{oid}",
                    to_node_id=f"node_opt_{oid}",
                    relation=ExplanationEdgeRelation.SATISFIES if sat else ExplanationEdgeRelation.VIOLATES,
                    notes=ce.get("explanation", ""),
                )
            )

        # Policy Nodes
        for pe in policy_evaluations:
            pid = pe.get("policy_id", "pol_unknown")
            oid = pe.get("option_id", "opt_unknown")
            p_stat = pe.get("status", "COMPLIANT")
            exp_nodes.append(
                ExplanationNode(
                    node_id=f"node_pol_{pid}_{oid}",
                    node_type=ExplanationNodeType.POLICY,
                    title=f"Policy {pid}",
                    provenance=EvidenceProvenance.DERIVED,
                    status=p_stat,
                    metadata={"reason": pe.get("reason", "")},
                )
            )
            exp_edges.append(
                ExplanationEdge(
                    edge_id=f"edge_pol_opt_{pid}_{oid}",
                    from_node_id=f"node_pol_{pid}_{oid}",
                    to_node_id=f"node_opt_{oid}",
                    relation=ExplanationEdgeRelation.SATISFIES if p_stat == "COMPLIANT" else ExplanationEdgeRelation.VIOLATES,
                    notes=pe.get("reason", ""),
                )
            )

        # Evidence Nodes
        for ev in supporting_evidence:
            exp_nodes.append(
                ExplanationNode(
                    node_id=f"node_ev_{ev.evidence_id}",
                    node_type=ExplanationNodeType.EVIDENCE,
                    title=ev.title,
                    provenance=ev.provenance,
                    status="VALID",
                    score=ev.quality_score,
                    metadata={"source_type": ev.source_type.value, "source_record_id": ev.source_record_id},
                )
            )
            # Connect to relevant option or decision
            target_node = f"node_opt_{recommended_opt_id}" if recommended_opt_id else f"node_dec_{decision_id}"
            exp_edges.append(
                ExplanationEdge(
                    edge_id=f"edge_ev_node_{ev.evidence_id}",
                    from_node_id=f"node_ev_{ev.evidence_id}",
                    to_node_id=target_node,
                    relation=ExplanationEdgeRelation.CONTRIBUTES_TO,
                    weight=ev.confidence_score,
                )
            )

        for ev in excluded_evidence:
            exp_nodes.append(
                ExplanationNode(
                    node_id=f"node_ev_ex_{ev.evidence_id}",
                    node_type=ExplanationNodeType.EVIDENCE,
                    title=f"[EXCLUDED] {ev.title}",
                    provenance=ev.provenance,
                    status="EXCLUDED",
                    metadata={"source_type": ev.source_type.value},
                )
            )
            exp_edges.append(
                ExplanationEdge(
                    edge_id=f"edge_ev_ex_{ev.evidence_id}",
                    from_node_id=f"node_ev_ex_{ev.evidence_id}",
                    to_node_id=f"node_dec_{decision_id}",
                    relation=ExplanationEdgeRelation.EXCLUDES,
                    notes="Excluded from active evaluation",
                )
            )

        # Deduplicate graph nodes & edges
        unique_nodes = {n.node_id: n for n in exp_nodes}
        unique_edges = {e.edge_id: e for e in exp_edges}

        sorted_exp_nodes = sorted(unique_nodes.values(), key=lambda n: n.node_id)
        sorted_exp_edges = sorted(unique_edges.values(), key=lambda e: (e.from_node_id, e.to_node_id, e.edge_id))

        graph_fingerprint = hashlib.sha256(
            json.dumps({"nodes": [n.node_id for n in sorted_exp_nodes], "edges": [e.edge_id for e in sorted_exp_edges]}, sort_keys=True).encode()
        ).hexdigest()

        explanation_graph = ExplanationGraph(
            graph_id=f"eg_{graph_fingerprint[:16]}",
            nodes=sorted_exp_nodes,
            edges=sorted_exp_edges,
            fingerprint=graph_fingerprint,
        )

        summary = (
            f"Decision '{decision_id}' ({decision_type}) evaluated with outcome {status}. "
            f"Recommended option: '{recommended_opt_id or 'NONE'}'. {primary_rationale} "
            f"Supported by {len(supporting_evidence)} valid evidence items; {len(excluded_evidence)} excluded."
        )

        conclusion_payload = {
            "decision_id": decision_id,
            "status": status,
            "recommended_option_id": recommended_opt_id,
            "primary_rationale": primary_rationale,
            "alternatives_count": len(alternatives),
            "top_composite_score": alternatives[0].get("composite_score", 0.0) if alternatives else 0.0,
            "tradeoffs": recommendation.get("tradeoffs", []),
        }

        return (
            summary,
            conclusion_payload,
            supporting_evidence,
            excluded_evidence,
            validations,
            contributions,
            rejections,
            conflicts,
            gaps,
            limitations,
            explanation_graph,
        )


# =============================================================================
# 5. EVIDENCE AND EXPLAINABILITY SERVICE ORCHESTRATOR
# =============================================================================

class EvidenceExplainabilityService:
    """
    Core deterministic Evidence and Explainability intelligence service.
    Produces reproducible explanations, bounded lineage graphs, itemized validations,
    and append-only audit ledgers. Strictly read-only for upstream systems.
    """

    def __init__(self, repository: Optional[EvidenceExplainabilityRepository] = None):
        self.repository = repository or evidence_explainability_repository

    def explain(
        self,
        request: ExplanationRequest,
        actor_id: str = "system",
    ) -> ExplanationResult:
        """
        Executes the deterministic explainability pipeline for a requested target.
        Returns a structured ExplanationResult with MANDATORY_EXPLAINABILITY_NOTICE.
        """
        assessment_ts = request.assessment_timestamp or datetime.now(timezone.utc).isoformat()
        freshness_threshold = request.freshness_threshold_seconds or SAGE_EXPLAINABILITY_DEFAULT_FRESHNESS_SECONDS

        # Step 1: Retrieve source record from upstream repository via adapter
        source_rec = SubsystemEvidenceAdapterRegistry.get_source_record(
            request.target_type,
            request.target_id,
            request.tenant_id,
        )

        # If source record is completely missing or inaccessible, return non-disclosing error / partial explanation
        is_partial = False
        summary = ""
        conclusion: Dict[str, Any] = {}
        supporting_evidence: List[EvidenceRecord] = []
        excluded_evidence: List[EvidenceRecord] = []
        validations: List[EvidenceValidationResult] = []
        contributions: List[EvidenceContribution] = []
        rejections: List[EvidenceRejection] = []
        conflicts: List[EvidenceConflict] = []
        gaps: List[EvidenceGap] = []
        limitations: List[ExplanationLimitation] = []
        exp_graph: Optional[ExplanationGraph] = None
        lineage_graph: Optional[EvidenceLineageGraph] = None

        if not source_rec:
            # Check if this is a Decision Engine target or other target
            is_partial = True
            gaps.append(
                EvidenceGap(
                    gap_id=f"gap_missing_target_{request.target_id[:12]}",
                    target_type=request.target_type.value,
                    target_id=request.target_id,
                    description=f"Target record '{request.target_id}' of type '{request.target_type.value}' was not found in caller's tenant partition.",
                    gap_type=GapType.UNAVAILABLE_RECORD,
                    impact="Cannot construct complete analytical explanation.",
                )
            )
            limitations.append(
                ExplanationLimitation(
                    limitation_id=f"lim_missing_target_{request.target_id[:12]}",
                    code="TARGET_RECORD_UNAVAILABLE",
                    description=f"Target {request.target_id} could not be retrieved from {request.target_type.value}.",
                    severity=SeverityLevel.BLOCKING,
                    mitigation="Verify target record ID and caller tenant permissions.",
                )
            )
            summary = f"Partial explanation: Target record '{request.target_id}' was not found in subsystem '{request.target_type.value}'."
            conclusion = {"target_id": request.target_id, "status": "UNAVAILABLE"}

        elif request.target_type == EvidenceSourceType.DECISION_ENGINE:
            # Specialized Decision Engine explainability
            (
                summary,
                conclusion,
                supporting_evidence,
                excluded_evidence,
                validations,
                contributions,
                rejections,
                conflicts,
                gaps,
                limitations,
                exp_graph,
            ) = DecisionExplainabilityBuilder.explain_decision(
                source_rec,
                request.tenant_id,
                request.workspace_id,
                request.plant_id,
                assessment_ts,
                freshness_threshold,
            )
        else:
            # Generic upstream subsystem explainability (Prompts 14–29)
            summary, conclusion, supporting_evidence, excluded_evidence, validations, gaps, limitations = (
                self._explain_generic_subsystem(
                    request.target_type,
                    request.target_id,
                    source_rec,
                    request.tenant_id,
                    request.workspace_id,
                    request.plant_id,
                    assessment_ts,
                    freshness_threshold,
                )
            )

        # Step 2: Build Lineage Graph if requested
        if request.include_lineage and (supporting_evidence or excluded_evidence):
            all_evidence = supporting_evidence + excluded_evidence
            lineage_graph, lineage_gaps = EvidenceLineageGraphBuilder.build_lineage_graph(
                root_id=request.target_id,
                initial_evidence=all_evidence,
                tenant_id=request.tenant_id,
                workspace_id=request.workspace_id,
                plant_id=request.plant_id,
                max_depth=request.depth_limit or SAGE_EXPLAINABILITY_MAX_GRAPH_DEPTH,
            )
            gaps.extend(lineage_gaps)

        # Determine if partial
        if not supporting_evidence or any(g.gap_type == GapType.UNAVAILABLE_RECORD for g in gaps):
            is_partial = True

        # Step 3: Compute deterministic fingerprint
        supporting_ids = [e.evidence_id for e in supporting_evidence]
        excluded_ids = [e.evidence_id for e in excluded_evidence]
        rej_codes = [r.reason_code for r in rejections]
        gap_descs = [g.description for g in gaps]
        lim_codes = [l.code for l in limitations]

        fingerprint = compute_explanation_fingerprint(
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            target_type=request.target_type,
            target_id=request.target_id,
            assessment_timestamp=assessment_ts,
            algorithm_version=ALGORITHM_VERSION,
            contract_version=CONTRACT_VERSION,
            supporting_evidence_ids=supporting_ids,
            excluded_evidence_ids=excluded_ids,
            rejection_reasons=rej_codes,
            gaps=gap_descs,
            limitations=lim_codes,
            recommendation_summary=summary,
        )

        explanation_id = f"exp_{fingerprint[:16]}"

        result = ExplanationResult(
            explanation_id=explanation_id,
            target_type=request.target_type,
            target_id=request.target_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            fingerprint=fingerprint,
            assessment_timestamp=assessment_ts,
            algorithm_version=ALGORITHM_VERSION,
            contract_version=CONTRACT_VERSION,
            summary=summary,
            recommendation_or_conclusion=conclusion,
            lineage_graph=lineage_graph,
            explanation_graph=exp_graph,
            supporting_evidence=supporting_evidence,
            excluded_evidence=excluded_evidence if request.include_excluded else [],
            validations=validations if request.include_validation else [],
            contributions=contributions,
            rejections=rejections,
            conflicts=conflicts,
            gaps=gaps,
            limitations=limitations,
            is_partial=is_partial,
            mandatory_notice=MANDATORY_EXPLAINABILITY_NOTICE,
            metadata={
                "target_type": request.target_type.value,
                "target_id": request.target_id,
                "supporting_count": len(supporting_evidence),
                "excluded_count": len(excluded_evidence),
                "lineage_depth": lineage_graph.depth if lineage_graph else 0,
            },
        )

        # Step 4: Persist explanation and audit record
        self.repository.save_explanation(result, actor_id=actor_id)

        return result

    def validate_batch(
        self,
        request: EvidenceValidationRequest,
        actor_id: str = "system",
    ) -> EvidenceValidationBatchResponse:
        """
        Deterministic batch validation of evidence records.
        """
        if request.assessment_timestamp:
            assessment_ts = request.assessment_timestamp
        else:
            max_item_ts = None
            for item in request.evidence_items:
                for ts in (item.assessed_at, item.observed_at, item.received_at):
                    if ts:
                        if max_item_ts is None or ts > max_item_ts:
                            max_item_ts = ts
            assessment_ts = max_item_ts or datetime.now(timezone.utc).isoformat()
        threshold = request.freshness_threshold_seconds or SAGE_EXPLAINABILITY_DEFAULT_FRESHNESS_SECONDS

        validations: List[EvidenceValidationResult] = []
        rejections: List[EvidenceRejection] = []

        valid_count = 0
        invalid_count = 0
        stale_count = 0
        conflicting_count = 0

        verify_source = getattr(request, "verify_source_existence", False)
        for item in request.evidence_items:
            val_res, rej_obj = EvidenceValidationEngine.validate_item(
                item,
                request.tenant_id,
                request.workspace_id,
                request.plant_id,
                assessment_ts,
                threshold,
                verify_source_existence=verify_source,
            )
            validations.append(val_res)

            if val_res.status == EvidenceValidationStatus.VALID:
                valid_count += 1
            elif val_res.status == EvidenceValidationStatus.STALE:
                stale_count += 1
            elif val_res.status == EvidenceValidationStatus.CONFLICTING:
                conflicting_count += 1
            else:
                invalid_count += 1

            if rej_obj:
                rejections.append(rej_obj)

        conflicts = EvidenceValidationEngine.detect_conflicts(request.evidence_items)
        if conflicts:
            conflicting_count += len(conflicts)

        # Fingerprint of batch validation
        batch_hash = hashlib.sha256(
            json.dumps({
                "tenant_id": request.tenant_id,
                "items": [v.evidence_id for v in validations],
                "statuses": [v.status.value for v in validations],
                "evaluated_at": assessment_ts,
            }, sort_keys=True).encode()
        ).hexdigest()

        return EvidenceValidationBatchResponse(
            validations=validations,
            valid_count=valid_count,
            invalid_count=invalid_count,
            stale_count=stale_count,
            conflicting_count=conflicting_count,
            rejections=rejections,
            conflicts=conflicts,
            evaluated_at=assessment_ts,
            fingerprint=batch_hash,
        )

    # -------------------------------------------------------------------------
    # PRIVATE HELPER METHODS
    # -------------------------------------------------------------------------

    def _explain_generic_subsystem(
        self,
        source_type: EvidenceSourceType,
        target_id: str,
        source_rec: Dict[str, Any],
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str],
        assessment_ts: str,
        freshness_threshold: float,
    ) -> Tuple[
        str,
        Dict[str, Any],
        List[EvidenceRecord],
        List[EvidenceRecord],
        List[EvidenceValidationResult],
        List[EvidenceGap],
        List[ExplanationLimitation],
    ]:
        """Explains non-decision analytical subsystems (Optimization, Simulation, etc.)."""
        supporting_evidence: List[EvidenceRecord] = []
        excluded_evidence: List[EvidenceRecord] = []
        validations: List[EvidenceValidationResult] = []
        gaps: List[EvidenceGap] = []
        limitations: List[ExplanationLimitation] = []

        # Determine provenance based on subsystem
        prov_map = {
            EvidenceSourceType.OPTIMIZATION: EvidenceProvenance.DERIVED,
            EvidenceSourceType.WHAT_IF_SIMULATION: EvidenceProvenance.SIMULATED,
            EvidenceSourceType.SENSOR_FUSION: EvidenceProvenance.DERIVED,
            EvidenceSourceType.PREDICTIVE_MAINTENANCE: EvidenceProvenance.FORECAST,
            EvidenceSourceType.DEMAND_FORECASTING: EvidenceProvenance.FORECAST,
            EvidenceSourceType.ROOT_CAUSE_ANALYSIS: EvidenceProvenance.DERIVED,
            EvidenceSourceType.BLAST_RADIUS: EvidenceProvenance.DERIVED,
            EvidenceSourceType.INCIDENT_MANAGEMENT: EvidenceProvenance.OBSERVED,
            EvidenceSourceType.DATA_QUALITY: EvidenceProvenance.DERIVED,
            EvidenceSourceType.ANOMALY_DETECTION: EvidenceProvenance.OBSERVED,
            EvidenceSourceType.SUPPLIER_RISK: EvidenceProvenance.DERIVED,
            EvidenceSourceType.SLA_CUSTOMER_RISK: EvidenceProvenance.FORECAST,
            EvidenceSourceType.FINANCIAL_IMPACT: EvidenceProvenance.ESTIMATED,
            EvidenceSourceType.SUSTAINABILITY: EvidenceProvenance.DERIVED,
            EvidenceSourceType.DIGITAL_TWIN: EvidenceProvenance.OBSERVED,
            EvidenceSourceType.OPERATIONAL_KNOWLEDGE_GRAPH: EvidenceProvenance.OBSERVED,
            EvidenceSourceType.INDUSTRIAL_ONTOLOGY: EvidenceProvenance.OBSERVED,
        }
        provenance = prov_map.get(source_type, EvidenceProvenance.UNKNOWN)

        # Extract underlying evidence references if the subsystem payload has them
        raw_evidence = source_rec.get("evidence") or source_rec.get("evidence_items") or source_rec.get("evidence_references") or []
        rec_ts = source_rec.get("timestamp") or source_rec.get("created_at") or source_rec.get("assessment_timestamp") or assessment_ts

        if isinstance(raw_evidence, list) and raw_evidence:
            for idx, item in enumerate(raw_evidence):
                ev_id = item.get("evidence_id", f"ev_{target_id[:8]}_{idx}") if isinstance(item, dict) else f"ev_{target_id[:8]}_{idx}"
                ev_payload = item if isinstance(item, dict) else {"raw": str(item)}

                ev_record = EvidenceRecord(
                    evidence_id=ev_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    plant_id=plant_id,
                    source_type=source_type,
                    source_record_id=target_id,
                    title=f"Evidence from {source_type.value} ({target_id})",
                    observed_at=rec_ts,
                    assessed_at=assessment_ts,
                    provenance=provenance,
                    quality_score=float(item.get("quality_score", 1.0)) if isinstance(item, dict) else 1.0,
                    confidence_score=float(item.get("confidence", 1.0)) if isinstance(item, dict) else 1.0,
                    fingerprint=hashlib.sha256(f"{ev_id}:{rec_ts}".encode()).hexdigest(),
                    payload=ev_payload,
                )

                val_res, _ = EvidenceValidationEngine.validate_item(
                    ev_record, tenant_id, workspace_id, plant_id, assessment_ts, freshness_threshold
                )
                validations.append(val_res)
                if val_res.is_valid:
                    supporting_evidence.append(ev_record)
                else:
                    excluded_evidence.append(ev_record)
        else:
            # Create a single synthetic root evidence record for the analytical artifact itself
            root_ev = EvidenceRecord(
                evidence_id=f"ev_{source_type.value.lower()}_{target_id[:12]}",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                plant_id=plant_id,
                source_type=source_type,
                source_record_id=target_id,
                title=f"Assessment result for {source_type.value} ({target_id})",
                observed_at=rec_ts,
                assessed_at=assessment_ts,
                provenance=provenance,
                quality_score=1.0,
                confidence_score=float(source_rec.get("confidence", 0.9)),
                fingerprint=hashlib.sha256(f"{target_id}:{rec_ts}".encode()).hexdigest(),
                payload={k: v for k, v in source_rec.items() if not isinstance(v, (list, dict)) or k in ("metrics", "scores", "status")},
            )
            val_res, _ = EvidenceValidationEngine.validate_item(
                root_ev, tenant_id, workspace_id, plant_id, assessment_ts, freshness_threshold
            )
            validations.append(val_res)
            if val_res.is_valid:
                supporting_evidence.append(root_ev)
            else:
                excluded_evidence.append(root_ev)

        summary = (
            f"Analytical assessment for '{target_id}' in subsystem '{source_type.value}' "
            f"classified as provenance '{provenance.value}'. "
            f"Contains {len(supporting_evidence)} supporting evidence records."
        )

        conclusion = {
            "target_id": target_id,
            "source_type": source_type.value,
            "provenance": provenance.value,
            "status": source_rec.get("status", "COMPLETED"),
            "summary_metrics": {k: v for k, v in source_rec.items() if isinstance(v, (int, float, str)) and k not in ("payload_json",)},
        }

        return summary, conclusion, supporting_evidence, excluded_evidence, validations, gaps, limitations


# Singleton service instance
evidence_explainability_service = EvidenceExplainabilityService()
