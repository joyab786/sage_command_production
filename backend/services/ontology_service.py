# backend/services/ontology_service.py
"""
SageCommand V3 — Industrial Ontology Domain Service
Orchestrates canonical semantic operations, identifier synthesis, relationship
compatibility enforcement, external identity mapping, lifecycle transitions,
and tenant boundary verification.

Cardinal Invariant:
The Industrial Ontology Service is purely a semantic truth and identity layer.
It never performs operational mutations or bypasses the Execution Gateway.
"""

import re
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
import logging

try:
    from core.auth import Identity
    from data.schemas.ontology_contract import (
        OntologyEntity,
        OntologyRelationship,
        ExternalIdMapping,
        EntityType,
        EntityLifecycleState,
        EntitySource,
        RelationshipType,
        RelationshipConfidence,
        validate_lifecycle_transition,
        validate_relationship_compatibility,
        RELATIONSHIP_COMPATIBILITY,
        TaxonomyResponse,
        ExternalLookupResponse,
    )
    from services.ontology_repository import OntologyRepository, ontology_repository
except ModuleNotFoundError:
    from backend.core.auth import Identity
    from backend.data.schemas.ontology_contract import (
        OntologyEntity,
        OntologyRelationship,
        ExternalIdMapping,
        EntityType,
        EntityLifecycleState,
        EntitySource,
        RelationshipType,
        RelationshipConfidence,
        validate_lifecycle_transition,
        validate_relationship_compatibility,
        RELATIONSHIP_COMPATIBILITY,
        TaxonomyResponse,
        ExternalLookupResponse,
    )
    from backend.services.ontology_repository import OntologyRepository, ontology_repository

logger = logging.getLogger("sagecommand.ontology")


def slugify(text: str) -> str:
    """Produces normalized slug for canonical IDs."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\.\-]+", "_", text)
    return text.strip("_")


class OntologyService:
    """
    Core Domain Service for Industrial Ontology.
    Enforces deterministic validation rules, tenant isolation, and semantic integrity.
    """

    def __init__(self, repo: OntologyRepository = ontology_repository):
        self.repo = repo

    def generate_canonical_id(
        self,
        entity_type: EntityType,
        canonical_name: str,
        plant_id: Optional[str] = None
    ) -> str:
        """
        Synthesizes a deterministic canonical URN for an industrial entity.
        Format: {entity_type}:{plant_or_scope}:{slug}
        """
        type_prefix = entity_type.value.lower()
        scope_part = slugify(plant_id) if plant_id else "global"
        name_part = slugify(canonical_name)
        return f"{type_prefix}:{scope_part}:{name_part}"

    # =========================================================================
    # 1. ENTITY LIFECYCLE & REGISTRATION
    # =========================================================================

    def create_entity(
        self,
        identity: Identity,
        entity_type: EntityType,
        canonical_name: str,
        display_name: str,
        entity_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        external_ids: Optional[Dict[str, str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: EntityLifecycleState = EntityLifecycleState.ACTIVE,
        source: EntitySource = EntitySource.MANUAL
    ) -> OntologyEntity:
        """
        Registers a new canonical entity in the ontology strictly scoped to caller's tenant.
        Fails if canonical ID already exists or if any external ID is already mapped to another entity.
        """
        tenant_id = identity.tenant_id
        target_workspace = workspace_id or identity.workspace_id or "workspace_default"

        # Validate or synthesize canonical ID
        if not entity_id or not entity_id.strip():
            cid = self.generate_canonical_id(entity_type, canonical_name, plant_id)
        else:
            cid = entity_id.strip()

        # Uniqueness verification
        existing = self.repo.get_entity(cid, tenant_id)
        if existing:
            raise ValueError(f"DUPLICATE_CANONICAL_ID: Entity '{cid}' already exists in tenant '{tenant_id}'.")

        # External IDs conflict check
        ext_dict = external_ids or {}
        for sys_name, ext_id in ext_dict.items():
            mapped = self.repo.lookup_external_id(tenant_id, sys_name, ext_id)
            if mapped and mapped.entity_id != cid:
                raise ValueError(
                    f"EXTERNAL_ID_CONFLICT: System '{sys_name}' identifier '{ext_id}' is already mapped "
                    f"to entity '{mapped.entity_id}'."
                )

        entity = OntologyEntity(
            entity_id=cid,
            entity_type=entity_type,
            canonical_name=canonical_name.strip(),
            display_name=display_name.strip(),
            tenant_id=tenant_id,
            workspace_id=target_workspace,
            plant_id=plant_id.strip() if plant_id else None,
            external_ids=ext_dict,
            attributes=attributes or {},
            metadata=metadata or {},
            status=status,
            source=source,
            version=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )

        return self.repo.save_entity(entity, snapshot_prior=False)

    def get_entity(self, entity_id: str, identity: Identity) -> Optional[OntologyEntity]:
        """Retrieves entity strictly within caller's tenant boundary."""
        return self.repo.get_entity(entity_id.strip(), identity.tenant_id)

    def list_entities(
        self,
        identity: Identity,
        entity_type: Optional[str] = None,
        plant_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[OntologyEntity], int]:
        """Lists entities within caller's tenant boundary with optional filters."""
        return self.repo.list_entities(
            tenant_id=identity.tenant_id,
            entity_type=entity_type,
            plant_id=plant_id,
            status=status,
            limit=limit,
            offset=offset
        )

    def update_entity(
        self,
        entity_id: str,
        identity: Identity,
        display_name: Optional[str] = None,
        plant_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[EntityLifecycleState] = None,
        source: Optional[EntitySource] = None,
        external_ids_to_add: Optional[Dict[str, str]] = None,
        external_ids_to_remove: Optional[List[str]] = None
    ) -> OntologyEntity:
        """
        Updates an existing ontology entity, increments version, and snapshots prior state.
        Enforces guarded lifecycle transitions and detects external mapping conflicts.
        """
        tenant_id = identity.tenant_id
        entity = self.repo.get_entity(entity_id.strip(), tenant_id)
        if not entity:
            raise KeyError(f"ENTITY_NOT_FOUND: Entity '{entity_id}' not found in tenant '{tenant_id}'.")

        # Lifecycle transition check
        if status and status != entity.status:
            if not validate_lifecycle_transition(entity.status, status):
                raise ValueError(
                    f"INVALID_LIFECYCLE_TRANSITION: Entity '{entity_id}' cannot transition "
                    f"from '{entity.status.value}' to '{status.value}'."
                )
            entity.status = status

        if display_name is not None:
            entity.display_name = display_name.strip()
        if plant_id is not None:
            entity.plant_id = plant_id.strip() if plant_id else None
        if attributes is not None:
            entity.attributes.update(attributes)
        if metadata is not None:
            entity.metadata.update(metadata)
        if source is not None:
            entity.source = source

        # External IDs management
        if external_ids_to_remove:
            for sys_name in external_ids_to_remove:
                normalized_sys = sys_name.upper().strip()
                if normalized_sys in entity.external_ids:
                    del entity.external_ids[normalized_sys]
                    self.repo.delete_external_mapping(tenant_id, normalized_sys, entity.external_ids.get(normalized_sys, ""))

        if external_ids_to_add:
            for sys_name, ext_id in external_ids_to_add.items():
                normalized_sys = sys_name.upper().strip()
                clean_ext_id = ext_id.strip()
                mapped = self.repo.lookup_external_id(tenant_id, normalized_sys, clean_ext_id)
                if mapped and mapped.entity_id != entity.entity_id:
                    # Mark entity in conflict state
                    entity.status = EntityLifecycleState.CONFLICT
                    raise ValueError(
                        f"EXTERNAL_ID_CONFLICT: Mapping '{normalized_sys}:{clean_ext_id}' is already "
                        f"assigned to entity '{mapped.entity_id}'. Entity '{entity_id}' marked in CONFLICT."
                    )
                entity.external_ids[normalized_sys] = clean_ext_id

        entity.version += 1
        entity.updated_at = datetime.now(timezone.utc).isoformat()

        return self.repo.save_entity(entity, snapshot_prior=True)

    # =========================================================================
    # 2. SEMANTIC RELATIONSHIPS & COMPATIBILITY
    # =========================================================================

    def create_relationship(
        self,
        identity: Identity,
        relationship_type: RelationshipType,
        source_entity_id: str,
        target_entity_id: str,
        plant_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
        source: EntitySource = EntitySource.MANUAL,
        confidence: RelationshipConfidence = RelationshipConfidence.CONFIRMED
    ) -> OntologyRelationship:
        """
        Creates a semantic relationship edge connecting two entities within tenant boundary.
        Fails closed on cross-tenant entities or invalid type compatibility.
        """
        tenant_id = identity.tenant_id
        src_id = source_entity_id.strip()
        tgt_id = target_entity_id.strip()

        # Both entities must exist in caller's tenant
        source_entity = self.repo.get_entity(src_id, tenant_id)
        if not source_entity:
            raise KeyError(f"SOURCE_ENTITY_NOT_FOUND: Source entity '{src_id}' not found in tenant '{tenant_id}'.")

        target_entity = self.repo.get_entity(tgt_id, tenant_id)
        if not target_entity:
            raise KeyError(f"TARGET_ENTITY_NOT_FOUND: Target entity '{tgt_id}' not found in tenant '{tenant_id}'.")

        # Deterministic compatibility verification
        is_compatible, err_msg = validate_relationship_compatibility(
            source_type=source_entity.entity_type,
            relationship_type=relationship_type,
            target_type=target_entity.entity_type
        )
        if not is_compatible:
            raise ValueError(f"RELATIONSHIP_INCOMPATIBLE: {err_msg}")

        rel = OntologyRelationship(
            relationship_id=f"rel_{uuid.uuid4().hex[:12]}",
            relationship_type=relationship_type,
            source_entity_id=src_id,
            target_entity_id=tgt_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id or identity.workspace_id or "workspace_default",
            plant_id=plant_id or source_entity.plant_id,
            attributes=attributes or {},
            valid_from=valid_from,
            valid_to=valid_to,
            source=source,
            confidence=confidence,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )

        return self.repo.save_relationship(rel)

    def get_entity_relationships(
        self,
        entity_id: str,
        identity: Identity,
        direction: str = "BOTH"
    ) -> List[OntologyRelationship]:
        """Retrieves semantic relationships for an entity strictly within tenant boundary."""
        return self.repo.get_entity_relationships(
            entity_id=entity_id.strip(),
            tenant_id=identity.tenant_id,
            direction=direction
        )

    def delete_relationship(self, relationship_id: str, identity: Identity) -> bool:
        """Deletes a relationship edge within tenant boundary."""
        return self.repo.delete_relationship(relationship_id.strip(), identity.tenant_id)

    # =========================================================================
    # 3. EXTERNAL IDENTIFIER RESOLUTION & CONFLICT HANDLING
    # =========================================================================

    def lookup_by_external_id(
        self,
        identity: Identity,
        system: str,
        external_id: str
    ) -> ExternalLookupResponse:
        """
        Resolves an external system identifier (e.g. MES:MCH-007) to its canonical entity.
        Returns resolution status or conflict details.
        """
        tenant_id = identity.tenant_id
        mapping = self.repo.lookup_external_id(tenant_id, system.upper().strip(), external_id.strip())
        if not mapping:
            return ExternalLookupResponse(
                success=True,
                resolved=False,
                entity=None,
                conflict=False,
                message=f"No entity mapped to external identifier '{system}:{external_id}'."
            )

        entity = self.repo.get_entity(mapping.entity_id, tenant_id)
        if not entity:
            return ExternalLookupResponse(
                success=True,
                resolved=False,
                entity=None,
                conflict=True,
                conflict_entity_ids=[mapping.entity_id],
                message=f"External mapping references non-existent entity '{mapping.entity_id}'."
            )

        is_conflict = (entity.status == EntityLifecycleState.CONFLICT)
        return ExternalLookupResponse(
            success=True,
            resolved=True,
            entity=entity,
            conflict=is_conflict,
            conflict_entity_ids=[entity.entity_id] if is_conflict else [],
            message="Entity successfully resolved." if not is_conflict else "Entity is in CONFLICT state."
        )

    def register_external_mapping(
        self,
        identity: Identity,
        entity_id: str,
        system: str,
        external_id: str,
        confidence: RelationshipConfidence = RelationshipConfidence.CONFIRMED,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ExternalIdMapping:
        """
        Binds an external system identifier to an existing canonical entity.
        Detects conflicts if the external ID is already registered to a different entity.
        """
        tenant_id = identity.tenant_id
        ent = self.repo.get_entity(entity_id.strip(), tenant_id)
        if not ent:
            raise KeyError(f"ENTITY_NOT_FOUND: Entity '{entity_id}' not found in tenant '{tenant_id}'.")

        norm_sys = system.upper().strip()
        clean_ext_id = external_id.strip()

        # Check existing mapping
        existing = self.repo.lookup_external_id(tenant_id, norm_sys, clean_ext_id)
        if existing and existing.entity_id != ent.entity_id:
            # Transition existing and current to CONFLICT
            ent.status = EntityLifecycleState.CONFLICT
            self.repo.save_entity(ent)
            raise ValueError(
                f"EXTERNAL_ID_CONFLICT: External identifier '{norm_sys}:{clean_ext_id}' is already "
                f"mapped to entity '{existing.entity_id}'. Entity '{entity_id}' marked in CONFLICT."
            )

        mapping = ExternalIdMapping(
            tenant_id=tenant_id,
            external_system=norm_sys,
            external_id=clean_ext_id,
            entity_id=ent.entity_id,
            confidence=confidence,
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        self.repo.save_external_mapping(mapping)

        # Update entity cached external_ids
        ent.external_ids[norm_sys] = clean_ext_id
        ent.updated_at = datetime.now(timezone.utc).isoformat()
        self.repo.save_entity(ent, snapshot_prior=False)
        return mapping

    # =========================================================================
    # 4. TAXONOMY & METADATA
    # =========================================================================

    def get_taxonomy(self) -> TaxonomyResponse:
        """Returns the full controlled entity and relationship taxonomy and rules."""
        rules_repr = {}
        for rtype, rule in RELATIONSHIP_COMPATIBILITY.items():
            rules_repr[rtype.value] = {
                "sources": sorted([s.value for s in rule["sources"]]),
                "targets": sorted([t.value for t in rule["targets"]]),
            }

        return TaxonomyResponse(
            success=True,
            entity_types=sorted([e.value for e in EntityType]),
            relationship_types=sorted([r.value for r in RelationshipType]),
            lifecycle_states=sorted([s.value for s in EntityLifecycleState]),
            sources=sorted([src.value for src in EntitySource]),
            compatibility_rules=rules_repr
        )


# Global singleton service
ontology_service = OntologyService()
