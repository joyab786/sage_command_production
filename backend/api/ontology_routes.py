# backend/api/ontology_routes.py
"""
SageCommand V3 — Industrial Ontology API Endpoints
Base Prefix: /api/v3/ontology
Provides authorized multi-tenant query and management access to canonical industrial
entities, semantic relationships, external identity lookups, and taxonomy definitions.

Security & Architectural Invariants:
- All queries and mutations enforce server-authoritative tenant isolation.
- Reading ontology requires 'ontology.read' capability.
- Managing ontology entities/relationships requires 'ontology.manage' capability.
- Purely semantic operations: this API never executes operational or database mutations.
"""

from typing import Optional
from fastapi import APIRouter, Header, Depends, Query, HTTPException, status

try:
    from core.auth import Identity, get_current_identity, require_permission
    from governance.rate_limiter import rate_limiter
    from data.schemas.ontology_contract import (
        OntologyEntity,
        OntologyRelationship,
        ExternalIdMapping,
        EntityCreateRequest,
        EntityUpdateRequest,
        RelationshipCreateRequest,
        ExternalMappingRequest,
        EntityResponse,
        EntityListResponse,
        RelationshipResponse,
        RelationshipListResponse,
        ExternalLookupResponse,
        TaxonomyResponse,
    )
    from services.ontology_service import ontology_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.governance.rate_limiter import rate_limiter
    from backend.data.schemas.ontology_contract import (
        OntologyEntity,
        OntologyRelationship,
        ExternalIdMapping,
        EntityCreateRequest,
        EntityUpdateRequest,
        RelationshipCreateRequest,
        ExternalMappingRequest,
        EntityResponse,
        EntityListResponse,
        RelationshipResponse,
        RelationshipListResponse,
        ExternalLookupResponse,
        TaxonomyResponse,
    )
    from backend.services.ontology_service import ontology_service

router = APIRouter(prefix="/api/v3/ontology", tags=["Industrial Ontology"])


def enforce_rate_limit(user_id: str):
    allowed, _ = rate_limiter.is_allowed(user_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please retry later."
        )


# =====================================================================
# 1. TAXONOMY & CONTROLLED VOCABULARY
# =====================================================================

@router.get(
    "/taxonomy",
    response_model=TaxonomyResponse,
    summary="Get Industrial Taxonomy",
    description="Returns controlled entity types, relationship types, lifecycle states, and compatibility rules."
)
async def get_taxonomy(
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.read"))
):
    enforce_rate_limit(identity.user_id)
    return ontology_service.get_taxonomy()


# =====================================================================
# 2. ENTITY QUERY & RETRIEVAL (READ APIs)
# =====================================================================

@router.get(
    "/entities",
    response_model=EntityListResponse,
    summary="List Canonical Entities",
    description="Returns a paginated list of canonical ontology entities strictly scoped to caller's tenant."
)
async def list_entities(
    entity_type: Optional[str] = Query(None, description="Filter by EntityType"),
    plant_id: Optional[str] = Query(None, description="Filter by Plant ID"),
    status: Optional[str] = Query(None, description="Filter by EntityLifecycleState"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.read"))
):
    enforce_rate_limit(identity.user_id)
    entities, total_count = ontology_service.list_entities(
        identity=identity,
        entity_type=entity_type,
        plant_id=plant_id,
        status=status,
        limit=limit,
        offset=offset
    )
    return EntityListResponse(
        success=True,
        data=entities,
        total_count=total_count,
        limit=limit,
        offset=offset
    )


@router.get(
    "/entities/{entity_id}",
    response_model=EntityResponse,
    summary="Get Canonical Entity",
    description="Retrieves an entity by its canonical ID within caller's tenant."
)
async def get_entity(
    entity_id: str,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.read"))
):
    enforce_rate_limit(identity.user_id)
    entity = ontology_service.get_entity(entity_id=entity_id, identity=identity)
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in tenant '{identity.tenant_id}'."
        )
    return EntityResponse(success=True, data=entity)


@router.get(
    "/entities/{entity_id}/relationships",
    response_model=RelationshipListResponse,
    summary="Get Entity Relationships",
    description="Retrieves semantic relationship edges connected to this entity."
)
async def get_entity_relationships(
    entity_id: str,
    direction: str = Query("BOTH", description="Edge direction: INCOMING, OUTGOING, or BOTH"),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.read"))
):
    enforce_rate_limit(identity.user_id)
    # Check entity exists in caller's tenant
    entity = ontology_service.get_entity(entity_id=entity_id, identity=identity)
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in tenant '{identity.tenant_id}'."
        )

    rels = ontology_service.get_entity_relationships(
        entity_id=entity_id,
        identity=identity,
        direction=direction
    )
    return RelationshipListResponse(
        success=True,
        data=rels,
        total_count=len(rels)
    )


@router.get(
    "/lookup",
    response_model=ExternalLookupResponse,
    summary="Resolve External Identifier",
    description="Resolves an external system identifier (e.g. MES:MCH-007) to its canonical ontology entity."
)
async def lookup_external_id(
    system: str = Query(..., description="External system name, e.g. SAP, MES, SCADA, PLC"),
    external_id: str = Query(..., description="External system native identifier"),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.read"))
):
    enforce_rate_limit(identity.user_id)
    return ontology_service.lookup_by_external_id(
        identity=identity,
        system=system,
        external_id=external_id
    )


# =====================================================================
# 3. ENTITY MANAGEMENT (WRITE APIs)
# =====================================================================

@router.post(
    "/entities",
    response_model=EntityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Canonical Entity",
    description="Registers a new canonical entity in the industrial ontology."
)
async def create_entity(
    req: EntityCreateRequest,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.manage"))
):
    enforce_rate_limit(identity.user_id)
    try:
        created = ontology_service.create_entity(
            identity=identity,
            entity_type=req.entity_type,
            canonical_name=req.canonical_name,
            display_name=req.display_name,
            entity_id=req.entity_id,
            plant_id=req.plant_id,
            workspace_id=req.workspace_id,
            external_ids=req.external_ids,
            attributes=req.attributes,
            metadata=req.metadata,
            status=req.status,
            source=req.source
        )
        return EntityResponse(
            success=True,
            data=created,
            message=f"Entity '{created.entity_id}' successfully created."
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )


@router.put(
    "/entities/{entity_id}",
    response_model=EntityResponse,
    summary="Update Canonical Entity",
    description="Updates attributes, display name, lifecycle state, or external mappings of an entity."
)
async def update_entity(
    entity_id: str,
    req: EntityUpdateRequest,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.manage"))
):
    enforce_rate_limit(identity.user_id)
    try:
        updated = ontology_service.update_entity(
            entity_id=entity_id,
            identity=identity,
            display_name=req.display_name,
            plant_id=req.plant_id,
            attributes=req.attributes,
            metadata=req.metadata,
            status=req.status,
            source=req.source,
            external_ids_to_add=req.external_ids_to_add,
            external_ids_to_remove=req.external_ids_to_remove
        )
        return EntityResponse(
            success=True,
            data=updated,
            message=f"Entity '{updated.entity_id}' successfully updated to version {updated.version}."
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in tenant '{identity.tenant_id}'."
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )


@router.post(
    "/relationships",
    response_model=RelationshipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Semantic Relationship",
    description="Establishes a semantic relationship edge between two entities within tenant boundary."
)
async def create_relationship(
    req: RelationshipCreateRequest,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.manage"))
):
    enforce_rate_limit(identity.user_id)
    try:
        rel = ontology_service.create_relationship(
            identity=identity,
            relationship_type=req.relationship_type,
            source_entity_id=req.source_entity_id,
            target_entity_id=req.target_entity_id,
            plant_id=req.plant_id,
            workspace_id=req.workspace_id,
            attributes=req.attributes,
            valid_from=req.valid_from,
            valid_to=req.valid_to,
            source=req.source,
            confidence=req.confidence
        )
        return RelationshipResponse(
            success=True,
            data=rel,
            message=f"Relationship '{rel.relationship_id}' created."
        )
    except KeyError as key_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(key_err)
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )


@router.delete(
    "/relationships/{relationship_id}",
    summary="Delete Semantic Relationship",
    description="Removes a semantic relationship edge within caller's tenant boundary."
)
async def delete_relationship(
    relationship_id: str,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.manage"))
):
    enforce_rate_limit(identity.user_id)
    deleted = ontology_service.delete_relationship(relationship_id=relationship_id, identity=identity)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Relationship '{relationship_id}' not found in tenant '{identity.tenant_id}'."
        )
    return {"success": True, "deleted": True, "relationship_id": relationship_id}


@router.post(
    "/entities/{entity_id}/mappings",
    response_model=ExternalIdMapping,
    status_code=status.HTTP_201_CREATED,
    summary="Register External Identifier Mapping",
    description="Maps an external system identifier to an existing canonical entity."
)
async def register_external_mapping(
    entity_id: str,
    req: ExternalMappingRequest,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.manage"))
):
    enforce_rate_limit(identity.user_id)
    try:
        return ontology_service.register_external_mapping(
            identity=identity,
            entity_id=entity_id,
            system=req.get_system(),
            external_id=req.external_id,
            confidence=req.confidence,
            metadata=req.metadata
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in tenant '{identity.tenant_id}'."
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )


@router.post(
    "/mappings",
    response_model=ExternalIdMapping,
    status_code=status.HTTP_201_CREATED,
    summary="Register External Identifier Mapping (Flat)",
    description="Maps an external system identifier to an existing canonical entity."
)
async def register_external_mapping_flat(
    req: ExternalMappingRequest,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("ontology.manage"))
):
    enforce_rate_limit(identity.user_id)
    if not req.entity_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'entity_id' is required in request body."
        )
    try:
        return ontology_service.register_external_mapping(
            identity=identity,
            entity_id=req.entity_id,
            system=req.get_system(),
            external_id=req.external_id,
            confidence=req.confidence,
            metadata=req.metadata
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{req.entity_id}' not found in tenant '{identity.tenant_id}'."
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )
