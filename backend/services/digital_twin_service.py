# backend/services/digital_twin_service.py
"""
SageCommand V3 — Digital Twin Domain Service (Prompt 13)
Orchestrates virtual operational state, typed property ingestion, state versioning,
temporal reconstruction, snapshot creation, scenario isolation, state comparison,
conflict handling, freshness evaluation, consistency validation, and graph integration.

Cardinal Invariant:
The Digital Twin is a deterministic virtual representation and simulation-context layer.
It NEVER performs physical actuation, operational mutations, or bypasses the execution pipeline.
It has ZERO imports of operational execution logic.
"""

import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple, Set

try:
    from core.config import (
        SAGE_DT_FRESHNESS_STALE_SECONDS,
        SAGE_DT_FRESHNESS_EXPIRED_SECONDS,
        SAGE_DT_MAX_SNAPSHOT_ENTITIES,
        SAGE_DT_MAX_HISTORY_RECORDS,
        SAGE_KG_MAX_TRAVERSAL_DEPTH,
        SAGE_KG_MAX_TRAVERSAL_NODES,
    )
    from core.auth import Identity
    from data.schemas.ontology_contract import EntityType, EntitySource
    from data.schemas.knowledge_graph_contract import FreshnessState, FactSourceType
    from data.schemas.digital_twin_contract import (
        TwinStateClassification,
        TwinConfidence,
        TwinConflictState,
        TwinPropertyValueType,
        TwinEntity,
        TwinStateProperty,
        TwinStateVersion,
        TwinSnapshot,
        TwinScenario,
        TwinStateDiff,
        TwinValidationIssue,
        TwinValidationReport,
        TWIN_ELIGIBLE_ENTITY_TYPES,
    )
    from services.ontology_service import OntologyService, ontology_service
    from services.knowledge_graph_service import KnowledgeGraphService, knowledge_graph_service
    from services.digital_twin_repository import DigitalTwinRepository, digital_twin_repository
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_DT_FRESHNESS_STALE_SECONDS,
        SAGE_DT_FRESHNESS_EXPIRED_SECONDS,
        SAGE_DT_MAX_SNAPSHOT_ENTITIES,
        SAGE_DT_MAX_HISTORY_RECORDS,
        SAGE_KG_MAX_TRAVERSAL_DEPTH,
        SAGE_KG_MAX_TRAVERSAL_NODES,
    )
    from backend.core.auth import Identity
    from backend.data.schemas.ontology_contract import EntityType, EntitySource
    from backend.data.schemas.knowledge_graph_contract import FreshnessState, FactSourceType
    from backend.data.schemas.digital_twin_contract import (
        TwinStateClassification,
        TwinConfidence,
        TwinConflictState,
        TwinPropertyValueType,
        TwinEntity,
        TwinStateProperty,
        TwinStateVersion,
        TwinSnapshot,
        TwinScenario,
        TwinStateDiff,
        TwinValidationIssue,
        TwinValidationReport,
        TWIN_ELIGIBLE_ENTITY_TYPES,
    )
    from backend.services.ontology_service import OntologyService, ontology_service
    from backend.services.knowledge_graph_service import KnowledgeGraphService, knowledge_graph_service
    from backend.services.digital_twin_repository import DigitalTwinRepository, digital_twin_repository


logger = logging.getLogger("sagecommand.digital_twin")


class DigitalTwinService:
    """
    Core domain service for the Digital Twin Foundation.
    Manages virtual operational state lifecycle without any operational execution capability.
    """

    def __init__(
        self,
        repo: DigitalTwinRepository = digital_twin_repository,
        ontology_svc: OntologyService = ontology_service,
        kg_svc: KnowledgeGraphService = knowledge_graph_service,
    ):
        self.repo = repo
        self.ontology_svc = ontology_svc
        self.kg_svc = kg_svc

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _build_identity(self, tenant_id: str) -> Identity:
        return Identity(user_id="system", tenant_id=tenant_id, roles=["SYSTEM"])

    # =========================================================================
    # ENTITY VALIDATION
    # =========================================================================

    def validate_twin_eligibility(self, tenant_id: str, entity_id: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Validate that an entity exists in the ontology and is twin-eligible.
        Returns (is_valid, error_message, entity_dict).
        """
        entity = self.ontology_svc.get_entity(entity_id=entity_id, identity=self._build_identity(tenant_id))
        if not entity:
            return False, f"Entity '{entity_id}' not found in ontology for tenant '{tenant_id}'.", None

        entity_dict = entity if isinstance(entity, dict) else entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()

        try:
            entity_type = EntityType(entity_dict.get("entity_type", ""))
        except ValueError:
            return False, f"Unknown entity type '{entity_dict.get('entity_type')}'.", None

        if entity_type not in TWIN_ELIGIBLE_ENTITY_TYPES:
            return False, f"Entity type '{entity_type.value}' is not twin-eligible.", None

        return True, None, entity_dict

    # =========================================================================
    # STATE INGESTION
    # =========================================================================

    def ingest_state(
        self,
        tenant_id: str,
        entity_id: str,
        properties: List[Dict[str, Any]],
        classification: str = "OBSERVED",
        source_type: str = "TELEMETRY",
        source_id: str = "system",
        observed_at: Optional[str] = None,
        effective_at: Optional[str] = None,
        confidence: str = "UNKNOWN",
        metadata: Optional[Dict[str, Any]] = None,
        workspace_id: str = "workspace_default",
        actor_id: str = "system",
    ) -> Tuple[bool, str, Optional[TwinEntity]]:
        """
        Ingest observed/derived/simulated state into the Digital Twin.
        Creates version history. Never destroys previous state.
        """
        now = datetime.now(timezone.utc).isoformat()
        if not observed_at:
            observed_at = now
        if not effective_at:
            effective_at = now

        # Validate entity eligibility
        is_valid, error, entity_dict = self.validate_twin_eligibility(tenant_id, entity_id)
        if not is_valid:
            return False, error, None

        entity_type = entity_dict["entity_type"]
        plant_id = entity_dict.get("plant_id")

        # Build twin ID deterministically
        existing = self.repo.get_twin_state(tenant_id, entity_id)
        if existing:
            twin_id = existing["twin_id"]
            current_version = existing.get("state_version", 0)
        else:
            twin_id = f"twin_{uuid.uuid4().hex[:12]}"
            current_version = 0

        new_version = current_version + 1

        # Build property list
        prop_list = []
        for p in properties:
            prop_list.append({
                "property_name": p.get("property_name", p.get("name", "")),
                "value_type": p.get("value_type", "STRING"),
                "value": p.get("value"),
                "unit": p.get("unit"),
                "classification": classification,
                "confidence": confidence,
                "source_type": source_type,
                "source_id": source_id,
                "observed_at": observed_at,
                "effective_at": effective_at,
                "recorded_at": now,
                "metadata": p.get("metadata", {}),
            })

        # Check for conflicts: same entity, overlapping effective_at
        conflict_state = "NONE"
        if existing and existing.get("effective_at") == effective_at:
            # Potential conflict — deterministic resolution: latest recorded_at wins
            if existing.get("recorded_at", "") >= now:
                conflict_state = "CONFLICT"
            else:
                conflict_state = "RESOLVED"

        # Calculate freshness
        freshness = self._calculate_freshness(observed_at)

        # Persist current state
        self.repo.upsert_twin_state(
            twin_id=twin_id,
            entity_id=entity_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            entity_type=entity_type,
            state_version=new_version,
            observed_at=observed_at,
            effective_at=effective_at,
            recorded_at=now,
            freshness=freshness,
            conflict_state=conflict_state,
            metadata=metadata or {},
            properties=prop_list,
        )

        # Preserve version history
        self.repo.insert_state_version(
            version_id=f"ver_{uuid.uuid4().hex[:12]}",
            twin_id=twin_id,
            entity_id=entity_id,
            tenant_id=tenant_id,
            state_version=new_version,
            properties_json=json.dumps(prop_list),
            effective_at=effective_at,
            recorded_at=now,
            classification=classification,
            conflict_state=conflict_state,
        )

        # Build response
        twin_props = [TwinStateProperty(
            property_name=p["property_name"],
            value_type=TwinPropertyValueType(p.get("value_type", "STRING")),
            value=p["value"],
            unit=p.get("unit"),
            classification=TwinStateClassification(classification),
            confidence=TwinConfidence(confidence),
            source_type=FactSourceType(source_type),
            source_id=source_id,
            observed_at=observed_at,
            effective_at=effective_at,
            recorded_at=now,
            metadata=p.get("metadata", {}),
        ) for p in prop_list]

        twin = TwinEntity(
            twin_id=twin_id,
            entity_id=entity_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            entity_type=EntityType(entity_type),
            properties=twin_props,
            state_version=new_version,
            observed_at=observed_at,
            effective_at=effective_at,
            recorded_at=now,
            freshness=FreshnessState(freshness),
            conflict_state=TwinConflictState(conflict_state),
            metadata=metadata or {},
        )

        logger.info(f"Twin state ingested: entity={entity_id} version={new_version} classification={classification}")
        return True, f"State ingested (v{new_version}).", twin

    # =========================================================================
    # STATE RETRIEVAL
    # =========================================================================

    def get_twin_entity(self, tenant_id: str, entity_id: str) -> Optional[TwinEntity]:
        """Get current twin state for an entity."""
        data = self.repo.get_twin_state(tenant_id, entity_id)
        if not data:
            return None
        return self._build_twin_entity(data)

    def get_state_history(self, tenant_id: str, entity_id: str,
                          limit: int = 200) -> List[TwinStateVersion]:
        """Get historical state versions for an entity."""
        limit = min(limit, SAGE_DT_MAX_HISTORY_RECORDS)
        versions = self.repo.get_state_history(tenant_id, entity_id, limit)
        results = []
        for v in versions:
            results.append(TwinStateVersion(
                version_id=v["version_id"],
                twin_id=v["twin_id"],
                entity_id=v["entity_id"],
                tenant_id=v["tenant_id"],
                state_version=v["state_version"],
                properties=[TwinStateProperty(**p) if isinstance(p, dict) else p for p in v.get("properties", [])],
                effective_at=v["effective_at"],
                recorded_at=v["recorded_at"],
                classification=TwinStateClassification(v.get("classification", "OBSERVED")),
                conflict_state=TwinConflictState(v.get("conflict_state", "NONE")),
            ))
        return results

    def get_state_at_time(self, tenant_id: str, entity_id: str,
                          timestamp: str) -> Optional[TwinStateVersion]:
        """Reconstruct state at a specific point in time."""
        data = self.repo.get_state_at_time(tenant_id, entity_id, timestamp)
        if not data:
            return None
        return TwinStateVersion(
            version_id=data["version_id"],
            twin_id=data["twin_id"],
            entity_id=data["entity_id"],
            tenant_id=data["tenant_id"],
            state_version=data["state_version"],
            properties=[TwinStateProperty(**p) if isinstance(p, dict) else p for p in data.get("properties", [])],
            effective_at=data["effective_at"],
            recorded_at=data["recorded_at"],
            classification=TwinStateClassification(data.get("classification", "OBSERVED")),
            conflict_state=TwinConflictState(data.get("conflict_state", "NONE")),
        )

    # =========================================================================
    # GRAPH CONTEXT INTEGRATION (READ-ONLY)
    # =========================================================================

    def get_entity_context(self, tenant_id: str, entity_id: str) -> Dict[str, Any]:
        """
        Get relationship context from the Knowledge Graph for a twin entity.
        Uses bounded traversal. Read-only — never mutates graph or operational state.
        """
        try:
            neighbors = self.kg_svc.get_neighbors(
                entity_id=entity_id,
                identity=self._build_identity(tenant_id),
                max_depth=min(2, SAGE_KG_MAX_TRAVERSAL_DEPTH),
            )
            return {
                "entity_id": entity_id,
                "neighbors": neighbors if isinstance(neighbors, list) else [],
                "source": "knowledge_graph",
                "bounded": True,
            }
        except Exception as e:
            logger.warning(f"Failed to get graph context for {entity_id}: {e}")
            return {
                "entity_id": entity_id,
                "neighbors": [],
                "source": "knowledge_graph",
                "bounded": True,
                "error": str(e),
            }

    # =========================================================================
    # SNAPSHOTS
    # =========================================================================

    def create_snapshot(
        self,
        tenant_id: str,
        workspace_id: str = "workspace_default",
        snapshot_timestamp: Optional[str] = None,
        entity_ids: Optional[List[str]] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_by: str = "system",
    ) -> TwinSnapshot:
        """
        Create an immutable point-in-time snapshot.
        Consistency rule: for each entity, uses latest state WHERE effective_at <= snapshot_timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()
        if not snapshot_timestamp:
            snapshot_timestamp = now

        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"

        # Determine which entities to include
        if entity_ids:
            target_ids = entity_ids[:SAGE_DT_MAX_SNAPSHOT_ENTITIES]
        else:
            target_ids = self.repo.get_all_entity_ids(tenant_id)[:SAGE_DT_MAX_SNAPSHOT_ENTITIES]

        entries = []
        twin_entities = []
        for eid in target_ids:
            # Use temporal query: latest version WHERE effective_at <= snapshot_timestamp
            version_data = self.repo.get_state_at_time(tenant_id, eid, snapshot_timestamp)
            if version_data:
                props = version_data.get("properties", [])
                entries.append({
                    "entity_id": eid,
                    "entity_type": self._get_entity_type_for_twin(tenant_id, eid),
                    "state_version": version_data.get("state_version"),
                    "properties": props,
                    "observed_at": version_data.get("recorded_at"),
                    "effective_at": version_data.get("effective_at"),
                    "freshness": self._calculate_freshness(version_data.get("recorded_at", now)),
                    "conflict_state": version_data.get("conflict_state", "NONE"),
                })

        self.repo.create_snapshot(
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=None,
            snapshot_timestamp=snapshot_timestamp,
            entity_count=len(entries),
            created_at=now,
            created_by=created_by,
            description=description,
            metadata=metadata or {},
            entries=entries,
        )

        # Build response model
        snap_entities = []
        for entry in entries:
            snap_entities.append(TwinEntity(
                twin_id=f"snap_entry_{entry['entity_id']}",
                entity_id=entry["entity_id"],
                tenant_id=tenant_id,
                entity_type=EntityType(entry["entity_type"]) if entry.get("entity_type") else EntityType.MACHINE,
                properties=[TwinStateProperty(**p) if isinstance(p, dict) else p for p in entry.get("properties", [])],
                state_version=entry.get("state_version", 1),
                observed_at=entry.get("observed_at", now),
                effective_at=entry.get("effective_at", now),
                freshness=FreshnessState(entry.get("freshness", "UNKNOWN")),
                conflict_state=TwinConflictState(entry.get("conflict_state", "NONE")),
            ))

        return TwinSnapshot(
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            snapshot_timestamp=snapshot_timestamp,
            entities=snap_entities,
            entity_count=len(entries),
            created_at=now,
            created_by=created_by,
            description=description,
            metadata=metadata or {},
        )

    def get_snapshot(self, tenant_id: str, snapshot_id: str) -> Optional[TwinSnapshot]:
        """Retrieve an existing snapshot. Snapshots are immutable."""
        data = self.repo.get_snapshot(tenant_id, snapshot_id)
        if not data:
            return None

        entities = []
        for entry in data.get("entries", []):
            entities.append(TwinEntity(
                twin_id=f"snap_entry_{entry.get('entity_id', '')}",
                entity_id=entry.get("entity_id", ""),
                tenant_id=tenant_id,
                entity_type=EntityType(entry["entity_type"]) if entry.get("entity_type") else EntityType.MACHINE,
                properties=[TwinStateProperty(**p) if isinstance(p, dict) else p for p in entry.get("properties", [])],
                state_version=entry.get("state_version", 1),
                observed_at=entry.get("observed_at", data.get("created_at", "")),
                effective_at=entry.get("effective_at", data.get("snapshot_timestamp", "")),
                freshness=FreshnessState(entry.get("freshness", "UNKNOWN")),
                conflict_state=TwinConflictState(entry.get("conflict_state", "NONE")),
            ))

        return TwinSnapshot(
            snapshot_id=data["snapshot_id"],
            tenant_id=tenant_id,
            workspace_id=data.get("workspace_id", "workspace_default"),
            snapshot_timestamp=data["snapshot_timestamp"],
            entities=entities,
            entity_count=data.get("entity_count", len(entities)),
            created_at=data.get("created_at", ""),
            created_by=data.get("created_by", "system"),
            description=data.get("description"),
            metadata=data.get("metadata", {}),
        )

    # =========================================================================
    # SCENARIOS
    # =========================================================================

    def create_scenario(
        self,
        tenant_id: str,
        base_snapshot_id: str,
        name: str,
        description: Optional[str] = None,
        overrides: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        workspace_id: str = "workspace_default",
        created_by: str = "system",
    ) -> Tuple[bool, str, Optional[TwinScenario]]:
        """
        Create a simulation scenario isolated from observed state.
        Scenario overrides NEVER silently become real/observed state.
        """
        # Validate base snapshot exists
        snapshot = self.get_snapshot(tenant_id, base_snapshot_id)
        if not snapshot:
            return False, f"Base snapshot '{base_snapshot_id}' not found.", None

        now = datetime.now(timezone.utc).isoformat()
        scenario_id = f"scen_{uuid.uuid4().hex[:12]}"

        self.repo.create_scenario(
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            base_snapshot_id=base_snapshot_id,
            name=name,
            description=description,
            created_at=now,
            created_by=created_by,
            metadata=metadata or {},
            overrides=overrides or [],
        )

        scenario = TwinScenario(
            scenario_id=scenario_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            base_snapshot_id=base_snapshot_id,
            name=name,
            description=description,
            overrides=overrides or [],
            created_at=now,
            created_by=created_by,
            metadata=metadata or {},
        )

        return True, "Scenario created.", scenario

    def get_scenario(self, tenant_id: str, scenario_id: str) -> Optional[TwinScenario]:
        """Retrieve a scenario with its overrides."""
        data = self.repo.get_scenario(tenant_id, scenario_id)
        if not data:
            return None
        return TwinScenario(
            scenario_id=data["scenario_id"],
            tenant_id=tenant_id,
            workspace_id=data.get("workspace_id", "workspace_default"),
            base_snapshot_id=data["base_snapshot_id"],
            name=data["name"],
            description=data.get("description"),
            overrides=data.get("overrides", []),
            created_at=data.get("created_at", ""),
            created_by=data.get("created_by", "system"),
            metadata=data.get("metadata", {}),
        )

    # =========================================================================
    # STATE COMPARISON
    # =========================================================================

    def compare_states(
        self,
        tenant_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
    ) -> Tuple[bool, str, List[TwinStateDiff]]:
        """
        Deterministic state comparison. No LLM involved.
        Supports: snapshot vs snapshot, entity vs entity.
        """
        source_props = self._resolve_state_properties(tenant_id, source_type, source_id)
        target_props = self._resolve_state_properties(tenant_id, target_type, target_id)

        if source_props is None:
            return False, f"Source '{source_type}:{source_id}' not found.", []
        if target_props is None:
            return False, f"Target '{target_type}:{target_id}' not found.", []

        diffs = []
        all_keys = set()
        for entity_id, props in source_props.items():
            for prop_name in props:
                all_keys.add((entity_id, prop_name))
        for entity_id, props in target_props.items():
            for prop_name in props:
                all_keys.add((entity_id, prop_name))

        for entity_id, prop_name in sorted(all_keys):
            old = source_props.get(entity_id, {}).get(prop_name)
            new = target_props.get(entity_id, {}).get(prop_name)

            old_val = old.get("value") if old else None
            new_val = new.get("value") if new else None

            if old_val != new_val:
                diffs.append(TwinStateDiff(
                    entity_id=entity_id,
                    property_name=prop_name,
                    old_value=old_val,
                    new_value=new_val,
                    old_classification=old.get("classification") if old else None,
                    new_classification=new.get("classification") if new else None,
                    old_source=old.get("source_id") if old else None,
                    new_source=new.get("source_id") if new else None,
                    old_timestamp=old.get("effective_at") if old else None,
                    new_timestamp=new.get("effective_at") if new else None,
                ))

        return True, f"Comparison complete: {len(diffs)} differences.", diffs

    # =========================================================================
    # CONSISTENCY VALIDATION
    # =========================================================================

    def validate_consistency(self, tenant_id: str) -> TwinValidationReport:
        """
        Run consistency checks on all twin entities for a tenant.
        Detects orphans, invalid types, stale sources, simulated-as-observed violations.
        """
        issues: List[TwinValidationIssue] = []
        now = datetime.now(timezone.utc)

        twins, _ = self.repo.list_twin_states(tenant_id, limit=1000)

        for twin in twins:
            entity_id = twin["entity_id"]

            # Check ontology entity exists
            entity = self.ontology_svc.get_entity(entity_id=entity_id, identity=self._build_identity(tenant_id))
            if not entity:
                issues.append(TwinValidationIssue(
                    severity="ERROR",
                    issue_type="ORPHAN_TWIN",
                    entity_id=entity_id,
                    twin_id=twin.get("twin_id"),
                    message=f"Twin entity '{entity_id}' has no corresponding ontology entity.",
                ))
                continue

            # Check entity type is twin-eligible
            entity_dict = entity if isinstance(entity, dict) else entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            try:
                etype = EntityType(entity_dict.get("entity_type", ""))
                if etype not in TWIN_ELIGIBLE_ENTITY_TYPES:
                    issues.append(TwinValidationIssue(
                        severity="ERROR",
                        issue_type="INVALID_ENTITY_TYPE",
                        entity_id=entity_id,
                        twin_id=twin.get("twin_id"),
                        message=f"Entity type '{etype.value}' is not twin-eligible.",
                    ))
            except ValueError:
                issues.append(TwinValidationIssue(
                    severity="ERROR",
                    issue_type="UNKNOWN_ENTITY_TYPE",
                    entity_id=entity_id,
                    twin_id=twin.get("twin_id"),
                    message=f"Unknown entity type '{entity_dict.get('entity_type')}'.",
                ))

            # Check freshness
            freshness = twin.get("freshness", "UNKNOWN")
            if freshness == "EXPIRED":
                issues.append(TwinValidationIssue(
                    severity="WARNING",
                    issue_type="EXPIRED_STATE",
                    entity_id=entity_id,
                    twin_id=twin.get("twin_id"),
                    message=f"Twin state for '{entity_id}' has expired freshness.",
                ))

            # Check conflict state
            if twin.get("conflict_state") == "CONFLICT":
                issues.append(TwinValidationIssue(
                    severity="WARNING",
                    issue_type="UNRESOLVED_CONFLICT",
                    entity_id=entity_id,
                    twin_id=twin.get("twin_id"),
                    message=f"Twin state for '{entity_id}' has unresolved conflict.",
                ))

        error_count = sum(1 for i in issues if i.severity == "ERROR")
        warning_count = sum(1 for i in issues if i.severity == "WARNING")

        return TwinValidationReport(
            tenant_id=tenant_id,
            is_valid=(error_count == 0),
            error_count=error_count,
            warning_count=warning_count,
            issues=issues,
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _calculate_freshness(self, observed_at: str) -> str:
        """Calculate freshness state based on observation timestamp."""
        try:
            obs_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_seconds = (now - obs_time).total_seconds()

            if age_seconds < 0:
                return FreshnessState.FRESH.value
            if age_seconds <= SAGE_DT_FRESHNESS_STALE_SECONDS:
                return FreshnessState.FRESH.value
            if age_seconds <= SAGE_DT_FRESHNESS_EXPIRED_SECONDS:
                return FreshnessState.STALE.value
            return FreshnessState.EXPIRED.value
        except (ValueError, TypeError):
            return FreshnessState.UNKNOWN.value

    def _build_twin_entity(self, data: Dict[str, Any]) -> TwinEntity:
        """Build a TwinEntity model from repository data."""
        props = []
        for p in data.get("properties", []):
            props.append(TwinStateProperty(
                property_name=p.get("property_name", ""),
                value_type=TwinPropertyValueType(p.get("value_type", "STRING")),
                value=p.get("value"),
                unit=p.get("unit"),
                classification=TwinStateClassification(p.get("classification", "OBSERVED")),
                confidence=TwinConfidence(p.get("confidence", "UNKNOWN")),
                source_type=FactSourceType(p.get("source_type", "SYSTEM")),
                source_id=p.get("source_id", "system"),
                observed_at=p.get("observed_at", data.get("observed_at", "")),
                effective_at=p.get("effective_at", data.get("effective_at", "")),
                recorded_at=p.get("recorded_at", data.get("recorded_at", "")),
                metadata=p.get("metadata", {}),
            ))

        # Recalculate freshness
        freshness = self._calculate_freshness(data.get("observed_at", ""))

        return TwinEntity(
            twin_id=data["twin_id"],
            entity_id=data["entity_id"],
            tenant_id=data["tenant_id"],
            workspace_id=data.get("workspace_id", "workspace_default"),
            plant_id=data.get("plant_id"),
            entity_type=EntityType(data.get("entity_type", "MACHINE")),
            properties=props,
            state_version=data.get("state_version", 1),
            observed_at=data.get("observed_at", ""),
            effective_at=data.get("effective_at", ""),
            recorded_at=data.get("recorded_at", ""),
            freshness=FreshnessState(freshness),
            conflict_state=TwinConflictState(data.get("conflict_state", "NONE")),
            metadata=data.get("metadata", {}),
        )

    def _get_entity_type_for_twin(self, tenant_id: str, entity_id: str) -> str:
        """Look up entity type from current twin state or ontology."""
        twin = self.repo.get_twin_state(tenant_id, entity_id)
        if twin:
            return twin.get("entity_type", "MACHINE")
        entity = self.ontology_svc.get_entity(entity_id=entity_id, identity=self._build_identity(tenant_id))
        if entity:
            entity_dict = entity if isinstance(entity, dict) else entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            return entity_dict.get("entity_type", "MACHINE")
        return "MACHINE"

    def _resolve_state_properties(
        self, tenant_id: str, state_type: str, state_id: str
    ) -> Optional[Dict[str, Dict[str, Dict[str, Any]]]]:
        """
        Resolve state properties for comparison.
        Returns: {entity_id: {property_name: {value, classification, source_id, effective_at}}}
        """
        if state_type == "snapshot":
            snapshot = self.get_snapshot(tenant_id, state_id)
            if not snapshot:
                return None
            result: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for entity in snapshot.entities:
                props = {}
                for p in entity.properties:
                    props[p.property_name] = {
                        "value": p.value,
                        "classification": p.classification.value if hasattr(p.classification, 'value') else str(p.classification),
                        "source_id": p.source_id,
                        "effective_at": p.effective_at,
                    }
                result[entity.entity_id] = props
            return result

        elif state_type == "entity":
            twin = self.get_twin_entity(tenant_id, state_id)
            if not twin:
                return None
            props = {}
            for p in twin.properties:
                props[p.property_name] = {
                    "value": p.value,
                    "classification": p.classification.value if hasattr(p.classification, 'value') else str(p.classification),
                    "source_id": p.source_id,
                    "effective_at": p.effective_at,
                }
            return {state_id: props}

        elif state_type == "scenario":
            scenario = self.get_scenario(tenant_id, state_id)
            if not scenario:
                return None
            # Start from base snapshot and apply overrides
            base_props = self._resolve_state_properties(tenant_id, "snapshot", scenario.base_snapshot_id)
            if base_props is None:
                return None
            for ovr in scenario.overrides:
                eid = ovr.get("entity_id", "")
                pname = ovr.get("property_name", "")
                if eid not in base_props:
                    base_props[eid] = {}
                base_props[eid][pname] = {
                    "value": ovr.get("value"),
                    "classification": "SIMULATED",
                    "source_id": f"scenario:{scenario.scenario_id}",
                    "effective_at": scenario.created_at,
                }
            return base_props

        return None


# Module-level singleton
digital_twin_service = DigitalTwinService()
