# backend/services/knowledge_graph_service.py
"""
SageCommand V3 — Operational Knowledge Graph Domain Service
Orchestrates operational fact ingestion, bitemporal queries, provenance tracking,
freshness evaluation, bounded graph traversals (BFS, shortest path, context expansion),
graph consistency validation, and read-only operational projections.

Cardinal Invariant:
The Operational Knowledge Graph is purely an informational context and query layer.
It never performs operational mutations or bypasses the Execution Gateway.
"""

import os
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple, Set
import sqlite3
import logging

try:
    from core.config import (
        DEFAULT_DB_PATH,
        SAGE_KG_MAX_TRAVERSAL_DEPTH,
        SAGE_KG_MAX_TRAVERSAL_NODES,
        SAGE_KG_MAX_TRAVERSAL_EDGES,
        SAGE_KG_FRESHNESS_STALE_SECONDS,
        SAGE_KG_FRESHNESS_EXPIRED_SECONDS,
    )
    from core.auth import Identity
    from data.schemas.ontology_contract import (
        EntityType,
        RelationshipType,
        validate_relationship_compatibility,
    )
    from data.schemas.knowledge_graph_contract import (
        OperationalFact,
        OperationalEdge,
        KnowledgeGraphNode,
        GraphNeighbor,
        GraphPath,
        GraphContextResponse,
        GraphValidationIssue,
        GraphValidationReport,
        FactValueType,
        FactSourceType,
        FactLifecycleState,
        FreshnessState,
        TraversalDirection,
        ProjectionSyncResponse,
    )
    from services.ontology_service import OntologyService, ontology_service
    from services.knowledge_graph_repository import (
        KnowledgeGraphRepository,
        knowledge_graph_repository,
    )
except ModuleNotFoundError:
    from backend.core.config import (
        DEFAULT_DB_PATH,
        SAGE_KG_MAX_TRAVERSAL_DEPTH,
        SAGE_KG_MAX_TRAVERSAL_NODES,
        SAGE_KG_MAX_TRAVERSAL_EDGES,
        SAGE_KG_FRESHNESS_STALE_SECONDS,
        SAGE_KG_FRESHNESS_EXPIRED_SECONDS,
    )
    from backend.core.auth import Identity
    from backend.data.schemas.ontology_contract import (
        EntityType,
        RelationshipType,
        validate_relationship_compatibility,
    )
    from backend.data.schemas.knowledge_graph_contract import (
        OperationalFact,
        OperationalEdge,
        KnowledgeGraphNode,
        GraphNeighbor,
        GraphPath,
        GraphContextResponse,
        GraphValidationIssue,
        GraphValidationReport,
        FactValueType,
        FactSourceType,
        FactLifecycleState,
        FreshnessState,
        TraversalDirection,
        ProjectionSyncResponse,
    )
    from backend.services.ontology_service import OntologyService, ontology_service
    from backend.services.knowledge_graph_repository import (
        KnowledgeGraphRepository,
        knowledge_graph_repository,
    )

logger = logging.getLogger("sagecommand.knowledge_graph.service")


def parse_iso(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        return datetime.fromisoformat(iso_str)
    except Exception:
        return None


class KnowledgeGraphService:
    """
    Core Domain Service for the Operational Knowledge Graph.
    Enforces deterministic validation rules, tenant isolation, temporal semantics,
    and bounded graph traversals.
    """

    def __init__(
        self,
        repo: KnowledgeGraphRepository = knowledge_graph_repository,
        ontology_svc: OntologyService = ontology_service,
        datacore_db_path: str = DEFAULT_DB_PATH
    ):
        self.repo = repo
        self.ontology_svc = ontology_svc
        self.datacore_db_path = datacore_db_path

    # =========================================================================
    # 1. FACT INGESTION & LIFECYCLE
    # =========================================================================

    def ingest_fact(
        self,
        identity: Identity,
        subject_entity_id: str,
        predicate: str,
        value: Any,
        value_type: FactValueType = FactValueType.STRING,
        object_entity_id: Optional[str] = None,
        unit: Optional[str] = None,
        source_type: FactSourceType = FactSourceType.API,
        source_id: str = "api",
        observed_at: Optional[str] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None
    ) -> OperationalFact:
        """
        Ingests a verified operational fact for an existing canonical ontology entity.
        Enforces tenant boundary, ontology existence, timestamp ordering, and
        deterministic superseding of prior active facts for singular predicates.
        """
        tenant_id = identity.tenant_id
        clean_subj = subject_entity_id.strip()
        clean_pred = predicate.strip().upper()
        now_str = datetime.now(timezone.utc).isoformat()
        obs_at = observed_at or now_str
        v_from = valid_from or obs_at

        # 1. Subject entity must exist within caller's tenant
        subj_entity = self.ontology_svc.get_entity(clean_subj, identity)
        if not subj_entity:
            raise KeyError(f"ENTITY_NOT_FOUND: Subject entity '{clean_subj}' not found in tenant '{tenant_id}'.")

        # 2. Object entity (if provided) must exist within caller's tenant
        clean_obj = object_entity_id.strip() if object_entity_id else None
        if clean_obj:
            obj_entity = self.ontology_svc.get_entity(clean_obj, identity)
            if not obj_entity:
                raise KeyError(f"TARGET_ENTITY_NOT_FOUND: Object entity '{clean_obj}' not found in tenant '{tenant_id}'.")

            # Check compatibility if predicate matches an ontology relationship type
            if clean_pred in RelationshipType._value2member_map_:
                rtype = RelationshipType(clean_pred)
                is_compat, err_msg = validate_relationship_compatibility(
                    source_type=subj_entity.entity_type,
                    relationship_type=rtype,
                    target_type=obj_entity.entity_type
                )
                if not is_compat:
                    raise ValueError(f"RELATIONSHIP_INCOMPATIBLE: {err_msg}")

        # 3. Validate timestamp ordering
        dt_from = parse_iso(v_from)
        dt_to = parse_iso(valid_to)
        if dt_from and dt_to and dt_to < dt_from:
            raise ValueError(f"INVALID_TEMPORAL_RANGE: 'valid_to' ({valid_to}) cannot precede 'valid_from' ({v_from}).")

        # 4. Automatically supersede prior active facts for matching (tenant, subject, predicate)
        self.repo.supersede_prior_facts(
            tenant_id=tenant_id,
            subject_entity_id=clean_subj,
            predicate=clean_pred,
            new_valid_from=v_from,
            archive_reason=f"SUPERSEDED_BY_{source_type.value}"
        )

        fact = OperationalFact(
            fact_id=f"fact_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            workspace_id=workspace_id or identity.workspace_id or "workspace_default",
            plant_id=plant_id or subj_entity.plant_id,
            subject_entity_id=clean_subj,
            predicate=clean_pred,
            object_entity_id=clean_obj,
            value_type=value_type,
            value=value,
            unit=unit,
            source_type=source_type,
            source_id=source_id,
            observed_at=obs_at,
            valid_from=v_from,
            valid_to=valid_to,
            recorded_at=now_str,
            confidence=confidence,
            status=FactLifecycleState.ACTIVE,
            metadata=metadata or {}
        )

        return self.repo.save_fact(fact)

    def revoke_fact(self, fact_id: str, identity: Identity, reason: str) -> bool:
        """Revokes an active fact, moving it to REVOKED status and archiving it."""
        tenant_id = identity.tenant_id
        fact = self.repo.get_fact(fact_id.strip(), tenant_id)
        if not fact:
            return False

        now_str = datetime.now(timezone.utc).isoformat()
        fact.status = FactLifecycleState.REVOKED
        fact.valid_to = now_str
        fact.metadata["revocation_reason"] = reason
        fact.metadata["revoked_by"] = identity.user_id
        fact.metadata["revoked_at"] = now_str

        self.repo.save_fact(fact)
        return True

    def get_fact(self, fact_id: str, identity: Identity) -> Optional[OperationalFact]:
        """Retrieves a fact strictly within caller's tenant boundary."""
        return self.repo.get_fact(fact_id.strip(), identity.tenant_id)

    def create_operational_edge(
        self,
        identity: Identity,
        source_entity_id: str,
        target_entity_id: str,
        predicate: str,
        attributes: Optional[Dict[str, Any]] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
        source_type: FactSourceType = FactSourceType.SYSTEM,
        source_id: str = "system"
    ) -> OperationalEdge:
        """
        Establishes a dynamic operational edge between two entities within tenant boundary.
        Validates both entities exist in ontology and satisfy compatibility.
        """
        tenant_id = identity.tenant_id
        src_id = source_entity_id.strip()
        tgt_id = target_entity_id.strip()
        clean_pred = predicate.strip().upper()
        now_str = datetime.now(timezone.utc).isoformat()

        src_ent = self.ontology_svc.get_entity(src_id, identity)
        if not src_ent:
            raise KeyError(f"SOURCE_ENTITY_NOT_FOUND: Source entity '{src_id}' not found in tenant '{tenant_id}'.")

        tgt_ent = self.ontology_svc.get_entity(tgt_id, identity)
        if not tgt_ent:
            raise KeyError(f"TARGET_ENTITY_NOT_FOUND: Target entity '{tgt_id}' not found in tenant '{tenant_id}'.")

        # Compatibility check if predicate matches an ontology relationship
        if clean_pred in RelationshipType._value2member_map_:
            rtype = RelationshipType(clean_pred)
            is_compat, err_msg = validate_relationship_compatibility(
                source_type=src_ent.entity_type,
                relationship_type=rtype,
                target_type=tgt_ent.entity_type
            )
            if not is_compat:
                raise ValueError(f"RELATIONSHIP_INCOMPATIBLE: {err_msg}")

        edge = OperationalEdge(
            edge_id=f"op_edge_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            workspace_id=identity.workspace_id or "workspace_default",
            plant_id=src_ent.plant_id,
            source_entity_id=src_id,
            target_entity_id=tgt_id,
            predicate=clean_pred,
            attributes=attributes or {},
            valid_from=valid_from or now_str,
            valid_to=valid_to,
            source_type=source_type,
            source_id=source_id,
            status=FactLifecycleState.ACTIVE,
            created_at=now_str,
            updated_at=now_str
        )

        return self.repo.save_edge(edge)

    # =========================================================================
    # 2. FRESHNESS EVALUATION
    # =========================================================================

    def calculate_freshness(self, observed_at: Optional[str]) -> FreshnessState:
        """Calculates freshness state based on observation age and configured thresholds."""
        if not observed_at:
            return FreshnessState.UNKNOWN

        dt_obs = parse_iso(observed_at)
        if not dt_obs:
            return FreshnessState.UNKNOWN

        now = datetime.now(timezone.utc)
        if dt_obs.tzinfo is None:
            dt_obs = dt_obs.replace(tzinfo=timezone.utc)

        age_seconds = (now - dt_obs).total_seconds()
        if age_seconds < 0:
            return FreshnessState.FRESH
        if age_seconds <= SAGE_KG_FRESHNESS_STALE_SECONDS:
            return FreshnessState.FRESH
        elif age_seconds <= SAGE_KG_FRESHNESS_EXPIRED_SECONDS:
            return FreshnessState.STALE
        else:
            return FreshnessState.EXPIRED

    # =========================================================================
    # 3. CONTEXT & NODE RETRIEVAL
    # =========================================================================

    def get_entity_node(
        self,
        entity_id: str,
        identity: Identity,
        at_time: Optional[str] = None
    ) -> Optional[KnowledgeGraphNode]:
        """
        Builds a contextual KnowledgeGraphNode combining canonical ontology identity
        with active or historical operational facts, status, and freshness.
        """
        tenant_id = identity.tenant_id
        ent = self.ontology_svc.get_entity(entity_id.strip(), identity)
        if not ent:
            return None

        # Fetch facts (active or point-in-time)
        if at_time:
            facts = self.repo.get_facts_at_time(ent.entity_id, tenant_id, at_time)
        else:
            facts = self.repo.get_active_facts_for_entity(ent.entity_id, tenant_id)

        # Derive current operational status (e.g. from OPERATIONAL_STATUS fact if present)
        op_status = None
        last_obs = None
        for f in facts:
            if f.predicate == "OPERATIONAL_STATUS":
                op_status = str(f.value)
            if not last_obs or (f.observed_at and f.observed_at > last_obs):
                last_obs = f.observed_at

        freshness = self.calculate_freshness(last_obs)

        return KnowledgeGraphNode(
            entity_id=ent.entity_id,
            entity_type=ent.entity_type,
            canonical_name=ent.canonical_name,
            display_name=ent.display_name,
            tenant_id=ent.tenant_id,
            workspace_id=ent.workspace_id,
            plant_id=ent.plant_id,
            lifecycle_status=ent.status,
            operational_status=op_status,
            active_facts=facts,
            freshness=freshness,
            last_observed_at=last_obs,
            attributes=ent.attributes,
            external_ids=ent.external_ids
        )

    # =========================================================================
    # 4. NEIGHBORS & DETERMINISTIC GRAPH TRAVERSAL
    # =========================================================================

    def get_neighbors(
        self,
        entity_id: str,
        identity: Identity,
        direction: str = "BOTH",
        predicate: Optional[str] = None,
        at_time: Optional[str] = None
    ) -> List[GraphNeighbor]:
        """
        Retrieves direct 1-hop graph neighbors connected via either:
        1. Canonical ontology relationships (Prompt 11 structural layer)
        2. Dynamic operational edges (Prompt 12 dynamic operational layer)
        """
        tenant_id = identity.tenant_id
        clean_id = entity_id.strip()
        direction = direction.upper().strip()
        if direction not in ("UPSTREAM", "DOWNSTREAM", "BOTH"):
            direction = "BOTH"

        neighbors: List[GraphNeighbor] = []
        seen_neighbor_keys: Set[Tuple[str, str, str]] = set()

        # 1. Structural Ontology Edges
        onto_dir = "BOTH"
        if direction == "DOWNSTREAM":
            onto_dir = "OUTGOING"
        elif direction == "UPSTREAM":
            onto_dir = "INCOMING"

        onto_rels = self.ontology_svc.get_entity_relationships(clean_id, identity, direction=onto_dir)
        for r in onto_rels:
            is_outgoing = (r.source_entity_id == clean_id)
            neighbor_id = r.target_entity_id if is_outgoing else r.source_entity_id
            dir_label = "OUTGOING" if is_outgoing else "INCOMING"

            # Filter predicate
            if predicate and r.relationship_type.value != predicate.upper():
                continue

            # Temporal filter if at_time specified
            if at_time and r.valid_from:
                if r.valid_from > at_time or (r.valid_to and r.valid_to <= at_time):
                    continue

            key = (neighbor_id, r.relationship_type.value, dir_label)
            if key in seen_neighbor_keys:
                continue
            seen_neighbor_keys.add(key)

            n_ent = self.ontology_svc.get_entity(neighbor_id, identity)
            if n_ent:
                neighbors.append(GraphNeighbor(
                    entity_id=n_ent.entity_id,
                    entity_type=n_ent.entity_type,
                    display_name=n_ent.display_name,
                    relationship_type=r.relationship_type.value,
                    direction=dir_label,
                    edge_source="ONTOLOGY",
                    valid_from=r.valid_from,
                    valid_to=r.valid_to,
                    freshness=FreshnessState.FRESH
                ))

        # 2. Dynamic Operational Edges
        op_dir = "BOTH"
        if direction == "DOWNSTREAM":
            op_dir = "OUTGOING"
        elif direction == "UPSTREAM":
            op_dir = "INCOMING"

        op_edges = self.repo.get_edges_for_entity(clean_id, tenant_id, direction=op_dir, predicate=predicate, at_time=at_time)
        for e in op_edges:
            is_outgoing = (e.source_entity_id == clean_id)
            neighbor_id = e.target_entity_id if is_outgoing else e.source_entity_id
            dir_label = "OUTGOING" if is_outgoing else "INCOMING"

            key = (neighbor_id, e.predicate, dir_label)
            if key in seen_neighbor_keys:
                continue
            seen_neighbor_keys.add(key)

            n_ent = self.ontology_svc.get_entity(neighbor_id, identity)
            if n_ent:
                neighbors.append(GraphNeighbor(
                    entity_id=n_ent.entity_id,
                    entity_type=n_ent.entity_type,
                    display_name=n_ent.display_name,
                    relationship_type=e.predicate,
                    direction=dir_label,
                    edge_source="OPERATIONAL",
                    valid_from=e.valid_from,
                    valid_to=e.valid_to,
                    freshness=self.calculate_freshness(e.valid_from)
                ))

        return neighbors

    def get_context(
        self,
        entity_id: str,
        identity: Identity,
        depth: int = 2,
        max_nodes: int = 50,
        direction: str = "BOTH",
        at_time: Optional[str] = None
    ) -> GraphContextResponse:
        """
        Bounded k-hop neighborhood expansion using Breadth-First Search (BFS).
        Guarantees cycle avoidance via visited set and strictly bounds depth and node limits.
        """
        clean_id = entity_id.strip()
        depth = min(max(1, depth), SAGE_KG_MAX_TRAVERSAL_DEPTH)
        max_nodes = min(max(1, max_nodes), SAGE_KG_MAX_TRAVERSAL_NODES)

        root_node = self.get_entity_node(clean_id, identity, at_time=at_time)
        if not root_node:
            raise KeyError(f"ENTITY_NOT_FOUND: Root entity '{clean_id}' not found in tenant '{identity.tenant_id}'.")

        nodes: Dict[str, KnowledgeGraphNode] = {clean_id: root_node}
        edges: List[Dict[str, Any]] = []
        visited: Set[str] = {clean_id}
        queue: deque = deque([(clean_id, 0)])

        max_depth_reached = 0

        while queue and len(nodes) < max_nodes:
            curr_id, curr_depth = queue.popleft()
            max_depth_reached = max(max_depth_reached, curr_depth)

            if curr_depth >= depth:
                continue

            neighbors = self.get_neighbors(curr_id, identity, direction=direction, at_time=at_time)
            for nb in neighbors:
                # Add edge to response
                edge_record = {
                    "source": curr_id if nb.direction == "OUTGOING" else nb.entity_id,
                    "target": nb.entity_id if nb.direction == "OUTGOING" else curr_id,
                    "predicate": nb.relationship_type,
                    "edge_source": nb.edge_source,
                    "direction": nb.direction
                }
                edges.append(edge_record)

                if nb.entity_id not in visited and len(nodes) < max_nodes:
                    visited.add(nb.entity_id)
                    nb_node = self.get_entity_node(nb.entity_id, identity, at_time=at_time)
                    if nb_node:
                        nodes[nb.entity_id] = nb_node
                        queue.append((nb.entity_id, curr_depth + 1))

        return GraphContextResponse(
            root_entity_id=clean_id,
            nodes=nodes,
            edges=edges,
            total_nodes=len(nodes),
            total_edges=len(edges),
            depth_reached=max_depth_reached
        )

    def get_upstream(
        self,
        entity_id: str,
        identity: Identity,
        max_depth: int = 3
    ) -> GraphContextResponse:
        """Explores upstream dependencies (inward edges)."""
        return self.get_context(
            entity_id=entity_id,
            identity=identity,
            depth=max_depth,
            direction="UPSTREAM"
        )

    def get_downstream(
        self,
        entity_id: str,
        identity: Identity,
        max_depth: int = 3
    ) -> GraphContextResponse:
        """Explores downstream dependencies (outward edges)."""
        return self.get_context(
            entity_id=entity_id,
            identity=identity,
            depth=max_depth,
            direction="DOWNSTREAM"
        )

    def find_path(
        self,
        source_entity_id: str,
        target_entity_id: str,
        identity: Identity,
        max_depth: int = 5
    ) -> Optional[GraphPath]:
        """
        Finds the shortest deterministic path between source and target entities using BFS.
        Enforces cycle avoidance and maximum depth limits.
        """
        src_id = source_entity_id.strip()
        tgt_id = target_entity_id.strip()
        max_depth = min(max(1, max_depth), SAGE_KG_MAX_TRAVERSAL_DEPTH)

        if src_id == tgt_id:
            return GraphPath(source_entity_id=src_id, target_entity_id=tgt_id, path=[src_id], depth=0, edges=[])

        # Verify source and target exist
        if not self.ontology_svc.get_entity(src_id, identity):
            raise KeyError(f"SOURCE_ENTITY_NOT_FOUND: Entity '{src_id}' not found.")
        if not self.ontology_svc.get_entity(tgt_id, identity):
            raise KeyError(f"TARGET_ENTITY_NOT_FOUND: Entity '{tgt_id}' not found.")

        # BFS queue storing (current_node, path_so_far, edges_so_far)
        visited: Set[str] = {src_id}
        queue: deque = deque([(src_id, [src_id], [])])

        while queue:
            curr_id, path, edges = queue.popleft()
            if len(path) - 1 >= max_depth:
                continue

            neighbors = self.get_neighbors(curr_id, identity, direction="BOTH")
            for nb in neighbors:
                if nb.entity_id == tgt_id:
                    final_path = path + [tgt_id]
                    final_edges = edges + [{
                        "source": curr_id if nb.direction == "OUTGOING" else tgt_id,
                        "target": tgt_id if nb.direction == "OUTGOING" else curr_id,
                        "predicate": nb.relationship_type,
                        "edge_source": nb.edge_source
                    }]
                    return GraphPath(
                        source_entity_id=src_id,
                        target_entity_id=tgt_id,
                        path=final_path,
                        depth=len(final_path) - 1,
                        edges=final_edges
                    )

                if nb.entity_id not in visited:
                    visited.add(nb.entity_id)
                    next_edges = edges + [{
                        "source": curr_id if nb.direction == "OUTGOING" else nb.entity_id,
                        "target": nb.entity_id if nb.direction == "OUTGOING" else curr_id,
                        "predicate": nb.relationship_type,
                        "edge_source": nb.edge_source
                    }]
                    queue.append((nb.entity_id, path + [nb.entity_id], next_edges))

        return None

    def get_history(
        self,
        entity_id: str,
        identity: Identity,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        predicate: Optional[str] = None
    ) -> List[OperationalFact]:
        """Retrieves temporal fact timeline for an entity strictly within tenant boundary."""
        return self.repo.get_fact_history(
            entity_id=entity_id.strip(),
            tenant_id=identity.tenant_id,
            start_time=start_time,
            end_time=end_time,
            predicate=predicate
        )

    def get_snapshot(
        self,
        identity: Identity,
        at_time: Optional[str] = None,
        plant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reconstructs point-in-time knowledge graph representation at timestamp at_time.
        Does NOT modify underlying historical records.
        """
        tenant_id = identity.tenant_id
        target_time = at_time or datetime.now(timezone.utc).isoformat()

        all_facts, _ = self.repo.get_all_tenant_facts(tenant_id, limit=500)
        snapshot_facts = [
            f for f in all_facts
            if f.valid_from <= target_time and (f.valid_to is None or f.valid_to > target_time)
            and (not plant_id or f.plant_id == plant_id)
        ]

        all_edges = self.repo.get_all_tenant_edges(tenant_id)
        snapshot_edges = [
            e for e in all_edges
            if e.valid_from <= target_time and (e.valid_to is None or e.valid_to > target_time)
            and (not plant_id or e.plant_id == plant_id)
        ]

        return {
            "snapshot_id": f"snap_{uuid.uuid4().hex[:12]}",
            "tenant_id": tenant_id,
            "at_time": target_time,
            "plant_id": plant_id,
            "active_facts_count": len(snapshot_facts),
            "active_edges_count": len(snapshot_edges),
            "facts": snapshot_facts,
            "edges": snapshot_edges
        }

    # =========================================================================
    # 5. GRAPH CONSISTENCY VALIDATION
    # =========================================================================

    def validate_graph(self, identity: Identity) -> GraphValidationReport:
        """
        Performs comprehensive graph consistency audit:
        - Missing ontology entity check
        - Incompatible relationship edge check
        - Conflicting active facts for singular predicates
        - Inverted timestamp ordering
        """
        tenant_id = identity.tenant_id
        issues: List[GraphValidationIssue] = []

        # 1. Inspect facts
        facts, total_facts = self.repo.get_all_tenant_facts(tenant_id, limit=1000)
        seen_active_singular: Dict[Tuple[str, str], str] = {}

        for f in facts:
            # Subject check
            subj_ent = self.ontology_svc.get_entity(f.subject_entity_id, identity)
            if not subj_ent:
                issues.append(GraphValidationIssue(
                    severity="ERROR",
                    issue_type="DANGLING_SUBJECT_ENTITY",
                    entity_id=f.subject_entity_id,
                    fact_id=f.fact_id,
                    message=f"Fact references non-existent subject entity '{f.subject_entity_id}'."
                ))

            # Object check
            if f.object_entity_id:
                obj_ent = self.ontology_svc.get_entity(f.object_entity_id, identity)
                if not obj_ent:
                    issues.append(GraphValidationIssue(
                        severity="ERROR",
                        issue_type="DANGLING_OBJECT_ENTITY",
                        entity_id=f.object_entity_id,
                        fact_id=f.fact_id,
                        message=f"Fact references non-existent object entity '{f.object_entity_id}'."
                    ))

            # Timestamp sanity
            dt_from = parse_iso(f.valid_from)
            dt_to = parse_iso(f.valid_to)
            if dt_from and dt_to and dt_to < dt_from:
                issues.append(GraphValidationIssue(
                    severity="ERROR",
                    issue_type="INVALID_TEMPORAL_ORDERING",
                    entity_id=f.subject_entity_id,
                    fact_id=f.fact_id,
                    message=f"Fact has invalid temporal range: valid_to ({f.valid_to}) precedes valid_from ({f.valid_from})."
                ))

            # Check for multiple active facts for singular predicates
            if f.status == FactLifecycleState.ACTIVE:
                key = (f.subject_entity_id, f.predicate)
                if key in seen_active_singular:
                    issues.append(GraphValidationIssue(
                        severity="WARNING",
                        issue_type="CONFLICTING_ACTIVE_FACTS",
                        entity_id=f.subject_entity_id,
                        fact_id=f.fact_id,
                        message=f"Multiple active facts observed for singular predicate '{f.predicate}'."
                    ))
                seen_active_singular[key] = f.fact_id

        # 2. Inspect edges
        edges = self.repo.get_all_tenant_edges(tenant_id)
        for e in edges:
            src_ent = self.ontology_svc.get_entity(e.source_entity_id, identity)
            tgt_ent = self.ontology_svc.get_entity(e.target_entity_id, identity)
            if not src_ent or not tgt_ent:
                issues.append(GraphValidationIssue(
                    severity="ERROR",
                    issue_type="DANGLING_EDGE_ENDPOINT",
                    entity_id=e.source_entity_id if not src_ent else e.target_entity_id,
                    message=f"Edge '{e.edge_id}' connects to non-existent endpoint entity."
                ))
            elif e.predicate in RelationshipType._value2member_map_:
                rtype = RelationshipType(e.predicate)
                is_compat, err_msg = validate_relationship_compatibility(
                    source_type=src_ent.entity_type,
                    relationship_type=rtype,
                    target_type=tgt_ent.entity_type
                )
                if not is_compat:
                    issues.append(GraphValidationIssue(
                        severity="ERROR",
                        issue_type="INCOMPATIBLE_EDGE",
                        entity_id=e.source_entity_id,
                        message=f"Edge '{e.edge_id}' violates ontology compatibility: {err_msg}"
                    ))

        err_cnt = sum(1 for i in issues if i.severity == "ERROR")
        warn_cnt = sum(1 for i in issues if i.severity == "WARNING")

        return GraphValidationReport(
            tenant_id=tenant_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            is_valid=(err_cnt == 0),
            error_count=err_cnt,
            warning_count=warn_cnt,
            issues=issues
        )

    # =========================================================================
    # 6. READ-ONLY OPERATIONAL DATA PROJECTION
    # =========================================================================

    def sync_inventory_projection(self, identity: Identity) -> ProjectionSyncResponse:
        """
        Deterministic, strictly read-only projection adapter.
        Reads inventory records from operational datacore and projects them as
        INVENTORY_LEVEL operational facts onto corresponding canonical ontology entities.
        Does NOT execute any operational database writes.
        """
        tenant_id = identity.tenant_id
        if not os.path.exists(self.datacore_db_path):
            return ProjectionSyncResponse(
                success=True,
                facts_ingested=0,
                source_records_inspected=0,
                message=f"Datacore database '{self.datacore_db_path}' not found; projection skipped."
            )

        # Strictly READ_ONLY SQLite connection
        conn = sqlite3.connect(f"file:{self.datacore_db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, item_name, quantity, reorder_threshold, unit_price FROM inventory")
            rows = cursor.fetchall()
        except sqlite3.OperationalError as op_err:
            return ProjectionSyncResponse(
                success=False,
                facts_ingested=0,
                source_records_inspected=0,
                message=f"Failed to read inventory table: {str(op_err)}"
            )
        finally:
            conn.close()

        ingested_count = 0
        now_str = datetime.now(timezone.utc).isoformat()

        for row in rows:
            item_name = row["item_name"]
            qty = row["quantity"]
            reorder = row["reorder_threshold"]

            # Lookup canonical entity via slug or external mapping
            canonical_name = item_name
            # If entity doesn't exist yet, create or look up via ontology
            entities, _ = self.ontology_svc.list_entities(
                identity=identity,
                entity_type=EntityType.INVENTORY_ITEM.value,
                limit=100
            )
            matching = [e for e in entities if e.canonical_name.lower() == canonical_name.lower() or e.display_name.lower() == item_name.lower()]

            if not matching:
                # Create corresponding canonical ontology entity if permissible
                ent = self.ontology_svc.create_entity(
                    identity=identity,
                    entity_type=EntityType.INVENTORY_ITEM,
                    canonical_name=canonical_name,
                    display_name=item_name,
                    plant_id="plant_mumbai",
                    attributes={"source_table": "inventory", "source_row_id": row["id"]}
                )
            else:
                ent = matching[0]

            # Ingest INVENTORY_LEVEL operational fact
            self.ingest_fact(
                identity=identity,
                subject_entity_id=ent.entity_id,
                predicate="INVENTORY_LEVEL",
                value=qty,
                value_type=FactValueType.INTEGER,
                unit="UNITS",
                source_type=FactSourceType.DATABASE,
                source_id="datacore_inventory_sync",
                observed_at=now_str,
                valid_from=now_str
            )

            # Ingest REORDER_THRESHOLD operational fact
            self.ingest_fact(
                identity=identity,
                subject_entity_id=ent.entity_id,
                predicate="REORDER_THRESHOLD",
                value=reorder,
                value_type=FactValueType.INTEGER,
                unit="UNITS",
                source_type=FactSourceType.DATABASE,
                source_id="datacore_inventory_sync",
                observed_at=now_str,
                valid_from=now_str
            )
            ingested_count += 2

        return ProjectionSyncResponse(
            success=True,
            facts_ingested=ingested_count,
            source_records_inspected=len(rows),
            message=f"Successfully projected {len(rows)} inventory records into {ingested_count} operational facts."
        )


# Module-level default service singleton
knowledge_graph_service = KnowledgeGraphService()
