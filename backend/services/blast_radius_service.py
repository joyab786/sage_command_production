import logging
import math
from datetime import datetime, UTC
from typing import Optional, Dict, List, Set, Any
from collections import deque

try:
    from core.auth import Identity
    from core.config import (
        SAGE_BLAST_RADIUS_MAX_DEPTH,
        SAGE_BLAST_RADIUS_MAX_NODES,
        SAGE_BLAST_RADIUS_MAX_PATHS
    )
    from data.schemas.blast_radius_contract import (
        BlastRadiusAnalysis,
        BlastRadiusAnalysisStatus,
        ImpactClassification,
        ConfidenceLevel,
        ImpactNode,
        ImpactPath,
        ImpactScope,
        ImpactEvidence
    )
    from services.blast_radius_repository import blast_radius_repository, BlastRadiusRepository
    from services.knowledge_graph_service import KnowledgeGraphService, KnowledgeGraphNode
    from services.ontology_service import OntologyService
except ModuleNotFoundError:
    from backend.core.auth import Identity
    from backend.core.config import (
        SAGE_BLAST_RADIUS_MAX_DEPTH,
        SAGE_BLAST_RADIUS_MAX_NODES,
        SAGE_BLAST_RADIUS_MAX_PATHS
    )
    from backend.data.schemas.blast_radius_contract import (
        BlastRadiusAnalysis,
        BlastRadiusAnalysisStatus,
        ImpactClassification,
        ConfidenceLevel,
        ImpactNode,
        ImpactPath,
        ImpactScope,
        ImpactEvidence
    )
    from backend.services.blast_radius_repository import blast_radius_repository, BlastRadiusRepository
    from backend.services.knowledge_graph_service import KnowledgeGraphService, KnowledgeGraphNode
    from backend.services.ontology_service import OntologyService

logger = logging.getLogger(__name__)

class BlastRadiusService:
    """
    Core Domain Service for Blast-Radius Intelligence.
    Deterministically computes potential impact spread from a source anomaly or incident
    using the Operational Knowledge Graph.
    
    Invariants:
    - Purely analytical layer.
    - Never mutates the physical system.
    - Never bypasses the Execution Gateway.
    """

    def __init__(
        self,
        repository: BlastRadiusRepository = blast_radius_repository,
        kg_service: Optional[KnowledgeGraphService] = None,
        ontology_svc: Optional[OntologyService] = None
    ):
        self.repo = repository
        # Lazy initialization to avoid circular imports if any
        self.kg_service = kg_service
        self.ontology_svc = ontology_svc

    def _get_kg_service(self) -> KnowledgeGraphService:
        if not self.kg_service:
            try:
                from services.knowledge_graph_service import KnowledgeGraphService as KGS
                from services.ontology_service import ontology_service
            except ModuleNotFoundError:
                from backend.services.knowledge_graph_service import KnowledgeGraphService as KGS
                from backend.services.ontology_service import ontology_service
            self.kg_service = KGS(ontology_svc=ontology_service)
        return self.kg_service

    def analyze_impact(
        self,
        identity: Identity,
        source_entity_id: str,
        source_incident_id: Optional[str] = None,
        source_anomaly_id: Optional[str] = None,
        max_depth: int = SAGE_BLAST_RADIUS_MAX_DEPTH,
        max_nodes: int = SAGE_BLAST_RADIUS_MAX_NODES
    ) -> BlastRadiusAnalysis:
        """
        Executes a deterministic blast-radius propagation algorithm (BFS) starting from 
        the source_entity_id.
        """
        tenant_id = identity.tenant_id
        now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        kg = self._get_kg_service()
        
        # Build initial analysis record
        analysis = BlastRadiusAnalysis(
            tenant_id=tenant_id,
            workspace_id=identity.workspace_id,
            source_entity_id=source_entity_id,
            source_incident_id=source_incident_id,
            source_anomaly_id=source_anomaly_id,
            snapshot_timestamp=now_str,
            analysis_status=BlastRadiusAnalysisStatus.RUNNING,
            method_version="deterministic_br_v1",
            confidence=ConfidenceLevel.HIGH
        )
        
        # Generate deduplication fingerprint
        fingerprint = analysis.generate_fingerprint()
        
        # Check cache
        cached = self.repo.get_analysis_by_fingerprint(fingerprint)
        if cached:
            return cached
            
        # Ensure source exists in KG
        root_node = kg.get_entity_node(source_entity_id, identity, at_time=now_str)
        if not root_node:
            analysis.analysis_status = BlastRadiusAnalysisStatus.FAILED
            analysis.uncertainty = f"Source entity '{source_entity_id}' not found in Knowledge Graph."
            analysis.confidence = ConfidenceLevel.INSUFFICIENT_DATA
            self.repo.save_analysis(analysis)
            return analysis
            
        # Initialize Graph Traversal state
        visited_nodes: Dict[str, ImpactNode] = {}
        paths: List[ImpactPath] = []
        
        # Enforce bounds
        max_depth = min(max(1, max_depth), SAGE_BLAST_RADIUS_MAX_DEPTH)
        max_nodes = min(max(1, max_nodes), SAGE_BLAST_RADIUS_MAX_NODES)
        
        # Breadth-First Search queue: (current_entity_id, distance, current_impact_score, path_so_far, rel_types_so_far)
        queue = deque([(source_entity_id, 0, 100.0, [source_entity_id], [])])
        
        # Register root node
        visited_nodes[source_entity_id] = ImpactNode(
            entity_id=root_node.entity_id,
            tenant_id=tenant_id,
            plant_id=root_node.plant_id,
            entity_type=root_node.entity_type,
            impact_classification=ImpactClassification.DIRECT,
            impact_score=100.0,
            confidence=ConfidenceLevel.HIGH,
            distance=0,
            evidence_refs=[ImpactEvidence(
                source_type="KNOWLEDGE_GRAPH",
                source_id=source_entity_id,
                source_timestamp=now_str,
                metadata={"reason": "Source entity of blast radius analysis"}
            )]
        )
        
        # Scope counters
        scope = ImpactScope(total_assets=0, total_processes=0, total_production_areas=0)
        if root_node.entity_type == "ASSET": scope.total_assets += 1
        elif root_node.entity_type == "PROCESS": scope.total_processes += 1
        elif root_node.entity_type == "PRODUCTION_AREA": scope.total_production_areas += 1
        
        while queue and len(visited_nodes) < max_nodes:
            curr_id, distance, curr_score, path_so_far, rels_so_far = queue.popleft()
            
            if distance >= max_depth:
                continue
                
            # Decay factor per hop
            decay = 0.8
            next_score = curr_score * decay
            
            if next_score < 10.0:
                continue # Below threshold
                
            neighbors = kg.get_neighbors(curr_id, identity, direction="BOTH", at_time=now_str)
            
            for nb in neighbors:
                if len(visited_nodes) >= max_nodes:
                    break
                    
                target_id = nb.entity_id
                
                # We record paths up to SAGE_BLAST_RADIUS_MAX_PATHS
                if len(paths) < SAGE_BLAST_RADIUS_MAX_PATHS:
                    new_path = path_so_far + [target_id]
                    new_rels = rels_so_far + [nb.relationship_type]
                    
                    paths.append(ImpactPath(
                        source_node_id=source_entity_id,
                        target_node_id=target_id,
                        ordered_path=new_path,
                        relationship_types=new_rels,
                        traversal_depth=distance + 1,
                        confidence=ConfidenceLevel.MEDIUM,
                        evidence_refs=[ImpactEvidence(
                            source_type="KNOWLEDGE_GRAPH",
                            source_id=f"{curr_id}_{nb.relationship_type}_{target_id}",
                            source_timestamp=now_str,
                            metadata={"edge_source": nb.edge_source}
                        )]
                    ))
                
                if target_id not in visited_nodes:
                    nb_node = kg.get_entity_node(target_id, identity, at_time=now_str)
                    if not nb_node:
                        continue
                        
                    # Classify impact direction
                    cls_val = ImpactClassification.UNKNOWN
                    if nb.direction == "OUTGOING":
                        cls_val = ImpactClassification.DOWNSTREAM
                        scope.total_downstream_dependencies += 1
                    elif nb.direction == "INCOMING":
                        cls_val = ImpactClassification.UPSTREAM
                        scope.total_upstream_dependencies += 1
                        
                    # Increment scope counts
                    if nb_node.entity_type == "ASSET": scope.total_assets += 1
                    elif nb_node.entity_type == "PROCESS": scope.total_processes += 1
                    elif nb_node.entity_type == "PRODUCTION_AREA": scope.total_production_areas += 1
                    
                    visited_nodes[target_id] = ImpactNode(
                        entity_id=nb_node.entity_id,
                        tenant_id=tenant_id,
                        plant_id=nb_node.plant_id,
                        entity_type=nb_node.entity_type,
                        impact_classification=cls_val,
                        impact_score=next_score,
                        confidence=ConfidenceLevel.MEDIUM,
                        distance=distance + 1,
                        evidence_refs=[ImpactEvidence(
                            source_type="KNOWLEDGE_GRAPH",
                            source_id=target_id,
                            source_timestamp=now_str
                        )]
                    )
                    
                    queue.append((target_id, distance + 1, next_score, path_so_far + [target_id], rels_so_far + [nb.relationship_type]))
                else:
                    # Update score if new path provides higher impact
                    existing_node = visited_nodes[target_id]
                    if next_score > existing_node.impact_score:
                        existing_node.impact_score = next_score
                        
        # Finalize analysis
        analysis.nodes = list(visited_nodes.values())
        analysis.paths = paths
        analysis.scope = scope
        analysis.analysis_status = BlastRadiusAnalysisStatus.COMPLETED
        analysis.analysis_timestamp = now_str
        
        # Persist
        self.repo.save_analysis(analysis)
        return analysis

# Global Singleton
blast_radius_service = BlastRadiusService()
