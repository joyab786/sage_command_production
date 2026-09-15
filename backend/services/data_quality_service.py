# backend/services/data_quality_service.py
"""
Data Quality Engine Service (Prompt 14)

Evaluates rules across 10 dimensions for the Industrial Ontology, Knowledge Graph, and Digital Twin.
Strictly isolated from Execution Gateway. Performs ZERO mutations.
"""
import uuid
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

try:
    from core.auth import Identity
    from data.schemas.data_quality_contract import (
        QualityRule, QualityDimension, QualitySeverity, QualityStatus,
        QualityResult, QualityIssue, IssueLifecycle, AssessmentRun, AssessmentScope
    )
    from services.data_quality_repository import DataQualityRepository
    from services.ontology_service import OntologyService
    from services.knowledge_graph_service import KnowledgeGraphService
    from services.digital_twin_service import DigitalTwinService
    from data.schemas.ontology_contract import EntityLifecycleState, OntologyEntity
    from data.schemas.knowledge_graph_contract import OperationalFact
    from data.schemas.digital_twin_contract import TwinStateVersion
    from core.config import SAGE_DQ_MAX_ENTITIES_PER_ASSESSMENT
except ImportError:
    from backend.core.auth import Identity
    from backend.data.schemas.data_quality_contract import (
        QualityRule, QualityDimension, QualitySeverity, QualityStatus,
        QualityResult, QualityIssue, IssueLifecycle, AssessmentRun, AssessmentScope
    )
    from backend.services.data_quality_repository import DataQualityRepository
    from backend.services.ontology_service import OntologyService
    from backend.services.knowledge_graph_service import KnowledgeGraphService
    from backend.services.digital_twin_service import DigitalTwinService
    from backend.data.schemas.ontology_contract import EntityLifecycleState, OntologyEntity
    from backend.data.schemas.knowledge_graph_contract import OperationalFact
    from backend.data.schemas.digital_twin_contract import TwinStateVersion
    from backend.core.config import SAGE_DQ_MAX_ENTITIES_PER_ASSESSMENT


class DataQualityService:
    def __init__(self, 
                 repository: DataQualityRepository,
                 ontology_svc: OntologyService,
                 kg_svc: KnowledgeGraphService,
                 dt_svc: DigitalTwinService):
        self._repo = repository
        self._ontology_svc = ontology_svc
        self._kg_svc = kg_svc
        self._dt_svc = dt_svc
        self._seed_system_rules()

    def _seed_system_rules(self):
        # Completeness
        self._repo.save_rule(QualityRule(
            rule_id="sys_comp_001", name="Missing Entity Required Field",
            description="Detect missing required fields on Ontology entities.",
            dimension=QualityDimension.COMPLETENESS, severity=QualitySeverity.HIGH
        ))
        # Freshness
        self._repo.save_rule(QualityRule(
            rule_id="sys_fresh_001", name="Stale Digital Twin State",
            description="Detect stale or expired Twin state.",
            dimension=QualityDimension.FRESHNESS, severity=QualitySeverity.MEDIUM
        ))
        # Accuracy
        self._repo.save_rule(QualityRule(
            rule_id="sys_acc_001", name="Unknown Accuracy",
            description="Accuracy is UNKNOWN if no reference ground truth is available.",
            dimension=QualityDimension.ACCURACY, severity=QualitySeverity.INFO
        ))
        # Consistency
        self._repo.save_rule(QualityRule(
            rule_id="sys_consist_001", name="Conflicting Authoritative Facts",
            description="Detect conflicting authoritative sources.",
            dimension=QualityDimension.CONSISTENCY, severity=QualitySeverity.CRITICAL
        ))
        # Integrity
        self._repo.save_rule(QualityRule(
            rule_id="sys_integ_001", name="Dangling Relationship",
            description="Detect relationship pointing to missing entity.",
            dimension=QualityDimension.INTEGRITY, severity=QualitySeverity.HIGH
        ))
        # Uniqueness
        self._repo.save_rule(QualityRule(
            rule_id="sys_uniq_001", name="Duplicate Identity",
            description="Detect duplicate canonical urn identities.",
            dimension=QualityDimension.UNIQUENESS, severity=QualitySeverity.HIGH
        ))
        # Conformity
        self._repo.save_rule(QualityRule(
            rule_id="sys_conf_001", name="Invalid Ontology Conformity",
            description="Detect semantic rule violation against ontology.",
            dimension=QualityDimension.CONFORMITY, severity=QualitySeverity.MEDIUM
        ))
        # Validity
        self._repo.save_rule(QualityRule(
            rule_id="sys_valid_001", name="Invalid State Configuration",
            description="State is completely invalid for the entity type.",
            dimension=QualityDimension.VALIDITY, severity=QualitySeverity.HIGH
        ))
        # Provenance
        self._repo.save_rule(QualityRule(
            rule_id="sys_prov_001", name="Missing Provenance",
            description="Data lacks source provenance.",
            dimension=QualityDimension.PROVENANCE, severity=QualitySeverity.MEDIUM
        ))
        # Coverage
        self._repo.save_rule(QualityRule(
            rule_id="sys_cov_001", name="Population Coverage",
            description="Measures known subset versus expected denominator.",
            dimension=QualityDimension.COVERAGE, severity=QualitySeverity.INFO
        ))


    def list_rules(self, identity: Identity) -> List[QualityRule]:
        return self._repo.get_rules(tenant_id=identity.tenant_id, include_system=True)

    def list_issues(self, identity: Identity) -> List[QualityIssue]:
        return self._repo.get_issues(tenant_id=identity.tenant_id)

    def get_assessment(self, identity: Identity, assessment_id: str) -> Optional[AssessmentRun]:
        return self._repo.get_assessment_run(tenant_id=identity.tenant_id, assessment_id=assessment_id)

    def get_assessments(self, identity: Identity) -> List[AssessmentRun]:
        return self._repo.get_assessment_runs(tenant_id=identity.tenant_id)

    def run_assessment(self, identity: Identity, scope: AssessmentScope) -> AssessmentRun:
        start_ts = time.time()
        start_iso = datetime.now(timezone.utc).isoformat()
        
        entities, _ = self._ontology_svc.list_entities(identity, limit=SAGE_DQ_MAX_ENTITIES_PER_ASSESSMENT)
        if scope.entity_types:
            entities = [e for e in entities if e.entity_type.value in scope.entity_types]
            
        entities = entities[:SAGE_DQ_MAX_ENTITIES_PER_ASSESSMENT]
        
        rules = self.list_rules(identity)
        if scope.dimensions:
            rules = [r for r in rules if r.dimension in scope.dimensions]
            
        results: List[QualityResult] = []
        
        # 1. Evaluate Entities
        for e in entities:
            results.extend(self._evaluate_completeness(e))
            results.extend(self._evaluate_uniqueness(e, entities))
            results.extend(self._evaluate_conformity(e))
            
            # Relationships
            rels = self._ontology_svc.get_entity_relationships(e.entity_id, identity)
            results.extend(self._evaluate_integrity(e, rels, identity))

            # Digital Twin
            dt_entity = self._dt_svc.get_twin_entity(identity.tenant_id, e.entity_id)
            dt_state = dt_entity.current_state if dt_entity else None
            if dt_state:
                results.extend(self._evaluate_freshness(e, dt_state))
                results.extend(self._evaluate_validity(e, dt_state))
                results.extend(self._evaluate_provenance(e, dt_state))
            
            # Knowledge Graph
            kg_facts = self._kg_svc.get_neighbors(e.entity_id, identity)
            if kg_facts:
                results.extend(self._evaluate_consistency(e, kg_facts))

        results.extend(self._evaluate_accuracy())
        results.extend(self._evaluate_coverage(entities))

        # Process Results -> Issues
        counts_by_dim = {d.value: 0 for d in QualityDimension}
        counts_by_status = {s.value: 0 for s in QualityStatus}
        
        new_issues = 0
        resolved_issues = 0
        
        for res in results:
            counts_by_dim[res.dimension.value] += 1
            counts_by_status[res.status.value] += 1
            
            if res.status in (QualityStatus.FAIL, QualityStatus.WARN):
                issue_id = f"iss_{uuid.uuid4().hex[:12]}"
                # Upsert logic (simplified for test)
                self._repo.save_issue(QualityIssue(
                    issue_id=issue_id,
                    tenant_id=identity.tenant_id,
                    workspace_id=identity.workspace_id,
                    plant_id=getattr(identity, 'plant_id', None),
                    entity_id=res.entity_id,
                    dimension=res.dimension,
                    rule_id=res.rule_id,
                    severity=res.severity,
                    status=IssueLifecycle.OPEN,
                    evidence=res.evidence,
                    first_detected_at=start_iso,
                    last_detected_at=start_iso,
                    occurrence_count=1,
                    source="DQ_ENGINE"
                ))
                new_issues += 1
                
        # Deterministic Score
        applicable = counts_by_status[QualityStatus.PASS.value] + counts_by_status[QualityStatus.FAIL.value] + counts_by_status[QualityStatus.WARN.value]
        score = (counts_by_status[QualityStatus.PASS.value] / applicable) if applicable > 0 else 1.0

        run = AssessmentRun(
            assessment_id=f"ass_{uuid.uuid4().hex[:12]}",
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=getattr(identity, 'plant_id', None),
            scope=scope.model_dump(),
            start_time=start_iso,
            completion_time=datetime.now(timezone.utc).isoformat(),
            rules_evaluated=len(rules),
            entities_evaluated=len(entities),
            counts_by_dimension=counts_by_dim,
            counts_by_status=counts_by_status,
            overall_score=score,
            execution_duration_ms=int((time.time() - start_ts) * 1000)
        )
        
        self._repo.save_assessment_run(run)
        return run

    # --- Dimension Evaluators ---

    def _evaluate_completeness(self, entity: OntologyEntity) -> List[QualityResult]:
        if not entity.canonical_name:
            return [QualityResult(
                rule_id="sys_comp_001", rule_version=1, dimension=QualityDimension.COMPLETENESS,
                status=QualityStatus.FAIL, severity=QualitySeverity.HIGH,
                entity_id=entity.entity_id, evidence="Missing required field 'canonical_name'", source="Ontology"
            )]
        return [QualityResult(
            rule_id="sys_comp_001", rule_version=1, dimension=QualityDimension.COMPLETENESS,
            status=QualityStatus.PASS, severity=QualitySeverity.INFO,
            entity_id=entity.entity_id, evidence="All required fields present", source="Ontology"
        )]

    def _evaluate_uniqueness(self, entity: OntologyEntity, all_entities: List[OntologyEntity]) -> List[QualityResult]:
        duplicates = [e for e in all_entities if e.entity_id != entity.entity_id and e.canonical_name == entity.canonical_name]
        if duplicates:
            return [QualityResult(
                rule_id="sys_uniq_001", rule_version=1, dimension=QualityDimension.UNIQUENESS,
                status=QualityStatus.FAIL, severity=QualitySeverity.HIGH,
                entity_id=entity.entity_id, evidence=f"Duplicate canonical_name found: {entity.canonical_name}", source="Ontology"
            )]
        return [QualityResult(
            rule_id="sys_uniq_001", rule_version=1, dimension=QualityDimension.UNIQUENESS,
            status=QualityStatus.PASS, severity=QualitySeverity.INFO,
            entity_id=entity.entity_id, evidence="URN is unique", source="Ontology"
        )]

    def _evaluate_conformity(self, entity: OntologyEntity) -> List[QualityResult]:
        if entity.status == EntityLifecycleState.CONFLICT:
            return [QualityResult(
                rule_id="sys_conf_001", rule_version=1, dimension=QualityDimension.CONFORMITY,
                status=QualityStatus.WARN, severity=QualitySeverity.MEDIUM,
                entity_id=entity.entity_id, evidence="Entity is in CONFLICT lifecycle state", source="Ontology"
            )]
        return [QualityResult(
            rule_id="sys_conf_001", rule_version=1, dimension=QualityDimension.CONFORMITY,
            status=QualityStatus.PASS, severity=QualitySeverity.INFO,
            entity_id=entity.entity_id, evidence="Entity conforms to taxonomy", source="Ontology"
        )]

    def _evaluate_integrity(self, entity: OntologyEntity, rels: List[Any], identity: Identity) -> List[QualityResult]:
        res = []
        for r in rels:
            # Check if target exists
            target = self._ontology_svc.get_entity(r.target_entity_id, identity)
            if not target:
                res.append(QualityResult(
                    rule_id="sys_integ_001", rule_version=1, dimension=QualityDimension.INTEGRITY,
                    status=QualityStatus.FAIL, severity=QualitySeverity.HIGH,
                    entity_id=entity.entity_id, relationship_id=r.relationship_id,
                    evidence=f"Dangling relationship: target {r.target_entity_id} does not exist", source="Ontology"
                ))
        if not res:
            res.append(QualityResult(
                rule_id="sys_integ_001", rule_version=1, dimension=QualityDimension.INTEGRITY,
                status=QualityStatus.PASS, severity=QualitySeverity.INFO,
                entity_id=entity.entity_id, evidence="All relationships intact", source="Ontology"
            ))
        return res

    def _evaluate_freshness(self, entity: OntologyEntity, dt_state: Dict[str, TwinStateVersion]) -> List[QualityResult]:
        res = []
        for k, v in dt_state.items():
            if v.is_expired:
                res.append(QualityResult(
                    rule_id="sys_fresh_001", rule_version=1, dimension=QualityDimension.FRESHNESS,
                    status=QualityStatus.FAIL, severity=QualitySeverity.HIGH,
                    entity_id=entity.entity_id, field=k,
                    evidence=f"State {k} is EXPIRED (recorded {v.recorded_at})", source="DigitalTwin"
                ))
            elif v.is_stale:
                res.append(QualityResult(
                    rule_id="sys_fresh_001", rule_version=1, dimension=QualityDimension.FRESHNESS,
                    status=QualityStatus.WARN, severity=QualitySeverity.MEDIUM,
                    entity_id=entity.entity_id, field=k,
                    evidence=f"State {k} is STALE (recorded {v.recorded_at})", source="DigitalTwin"
                ))
        if not res:
            res.append(QualityResult(
                rule_id="sys_fresh_001", rule_version=1, dimension=QualityDimension.FRESHNESS,
                status=QualityStatus.PASS, severity=QualitySeverity.INFO,
                entity_id=entity.entity_id, evidence="All state is fresh", source="DigitalTwin"
            ))
        return res

    def _evaluate_validity(self, entity: OntologyEntity, dt_state: Dict[str, TwinStateVersion]) -> List[QualityResult]:
        res = []
        for k, v in dt_state.items():
            if v.property_type.value == "UNKNOWN":
                res.append(QualityResult(
                    rule_id="sys_valid_001", rule_version=1, dimension=QualityDimension.VALIDITY,
                    status=QualityStatus.FAIL, severity=QualitySeverity.HIGH,
                    entity_id=entity.entity_id, field=k,
                    evidence=f"State {k} has unknown type / invalid state", source="DigitalTwin"
                ))
        if not res:
            res.append(QualityResult(
                rule_id="sys_valid_001", rule_version=1, dimension=QualityDimension.VALIDITY,
                status=QualityStatus.PASS, severity=QualitySeverity.INFO,
                entity_id=entity.entity_id, evidence="All state values valid", source="DigitalTwin"
            ))
        return res

    def _evaluate_provenance(self, entity: OntologyEntity, dt_state: Dict[str, TwinStateVersion]) -> List[QualityResult]:
        res = []
        for k, v in dt_state.items():
            if not v.source_id:
                res.append(QualityResult(
                    rule_id="sys_prov_001", rule_version=1, dimension=QualityDimension.PROVENANCE,
                    status=QualityStatus.WARN, severity=QualitySeverity.MEDIUM,
                    entity_id=entity.entity_id, field=k,
                    evidence=f"State {k} is missing source_id", source="DigitalTwin"
                ))
        if not res:
            res.append(QualityResult(
                rule_id="sys_prov_001", rule_version=1, dimension=QualityDimension.PROVENANCE,
                status=QualityStatus.PASS, severity=QualitySeverity.INFO,
                entity_id=entity.entity_id, evidence="All state has provenance", source="DigitalTwin"
            ))
        return res

    def _evaluate_consistency(self, entity: OntologyEntity, kg_facts: List[Any]) -> List[QualityResult]:
        # Detect conflicting operational facts (e.g. multiple distinct status values)
        status_facts = [f for f in kg_facts if getattr(f, "relationship_type", None) == "OPERATES_AT"]
        if len(status_facts) > 1:
            return [QualityResult(
                rule_id="sys_consist_001", rule_version=1, dimension=QualityDimension.CONSISTENCY,
                status=QualityStatus.FAIL, severity=QualitySeverity.CRITICAL,
                entity_id=entity.entity_id, evidence="Conflicting authoritative facts detected in Knowledge Graph", source="KnowledgeGraph"
            )]
        return [QualityResult(
            rule_id="sys_consist_001", rule_version=1, dimension=QualityDimension.CONSISTENCY,
            status=QualityStatus.PASS, severity=QualitySeverity.INFO,
            entity_id=entity.entity_id, evidence="No conflicts detected", source="KnowledgeGraph"
        )]

    def _evaluate_accuracy(self) -> List[QualityResult]:
        return [QualityResult(
            rule_id="sys_acc_001", rule_version=1, dimension=QualityDimension.ACCURACY,
            status=QualityStatus.UNKNOWN, severity=QualitySeverity.INFO,
            evidence="No authoritative ground truth available for accuracy score", source="System"
        )]
        
    def _evaluate_coverage(self, entities: List[OntologyEntity]) -> List[QualityResult]:
        if not entities:
            return [QualityResult(
                rule_id="sys_cov_001", rule_version=1, dimension=QualityDimension.COVERAGE,
                status=QualityStatus.UNKNOWN, severity=QualitySeverity.INFO,
                evidence="No expected denominator defined for coverage", source="System"
            )]
        return [QualityResult(
            rule_id="sys_cov_001", rule_version=1, dimension=QualityDimension.COVERAGE,
            status=QualityStatus.PASS, severity=QualitySeverity.INFO,
            evidence=f"Coverage metrics derived from {len(entities)} known entities", source="System"
        )]
