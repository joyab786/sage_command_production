# backend/api/sop_rag_routes.py
"""
SageCommand V3 — SOP / RAG Intelligence Foundation API Routes (Prompt 33 / 33A)

Versioned REST endpoints rooted at /api/v3/sop-rag.
Enforces authentication, RBAC/ABAC permissions, fail-closed tenant isolation,
plant boundary restrictions, classification clearance gates, governed publication state transitions,
payload bounds, and safe non-disclosing error responses.

Notice:
ADVISORY SOP KNOWLEDGE ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT, OR BYPASSES OPERATIONAL GOVERNANCE
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger("sop_rag_routes")

try:
    from core.auth import Identity, get_current_identity, require_permission
    from core.config import SAGE_SOP_MAX_RETRIEVAL_RESULTS
    from data.schemas.sop_rag_contract import (
        SOPDocument,
        DocumentChunk,
        DocumentLifecycleStatus,
        ClassificationLevel,
        IngestionRequest,
        IngestionResult,
        RetrievalRequest,
        RetrievalResponse,
        RAGQueryRequest,
        RAGAnswer,
        SOPAuditRecord,
        MANDATORY_SOP_RAG_NOTICE,
        CLASSIFICATION_CLEARANCE_MAP,
        VALID_LIFECYCLE_TRANSITIONS,
        get_allowed_classifications_for_clearance,
    )
    from services.sop_rag_service import (
        SOPRAGService,
        sop_rag_service,
    )
    from repositories.sop_rag_repository import (
        sop_rag_repository,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.core.config import SAGE_SOP_MAX_RETRIEVAL_RESULTS
    from backend.data.schemas.sop_rag_contract import (
        SOPDocument,
        DocumentChunk,
        DocumentLifecycleStatus,
        ClassificationLevel,
        IngestionRequest,
        IngestionResult,
        RetrievalRequest,
        RetrievalResponse,
        RAGQueryRequest,
        RAGAnswer,
        SOPAuditRecord,
        MANDATORY_SOP_RAG_NOTICE,
        CLASSIFICATION_CLEARANCE_MAP,
        VALID_LIFECYCLE_TRANSITIONS,
        get_allowed_classifications_for_clearance,
    )
    from backend.services.sop_rag_service import (
        SOPRAGService,
        sop_rag_service,
    )
    from backend.repositories.sop_rag_repository import (
        sop_rag_repository,
    )

router = APIRouter(
    prefix="/api/v3/sop-rag",
    tags=["SOP / RAG Intelligence Foundation"],
)


# ---------------------------------------------------------------------------
# POST /api/v3/sop-rag/documents/ingest
# ---------------------------------------------------------------------------

@router.post("/documents/ingest", response_model=IngestionResult)
async def ingest_sop_document(
    request: IngestionRequest,
    user: Identity = Depends(require_permission("sop_rag.ingest")),
):
    """
    Ingests, validates, chunks, and registers an authoritative SOP document.
    Enforces tenant partition isolation, plant boundary access control,
    and governed lifecycle defaulting (new documents default to DRAFT;
    ordinary ingestion permission cannot directly publish).
    """
    # Tenant boundary enforcement: prevent caller from spoofing a foreign tenant
    if request.tenant_id and request.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot ingest documents for another tenant partition.",
        )

    # Plant scope enforcement
    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")
        clearance = getattr(user, "clearance_level", 1)
        user_permissions = getattr(user, "permissions", [])
        is_admin = "sop_rag.admin" in user_permissions

        result = sop_rag_service.ingest_document(
            request=request,
            actor_id=actor_id,
            authoritative_tenant_id=user.tenant_id,
            clearance_level=clearance,
            user_permissions=user_permissions,
            is_admin=is_admin,
        )
        if result.ingestion_status == "FAILED":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Document ingestion validation failed", "errors": result.validation_errors},
            )
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning("Document ingestion validation error: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Document validation failed: invalid format or payload parameters.",
        )
    except Exception as e:
        logger.error("Document ingestion internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal processing error occurred during document ingestion.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/sop-rag/documents/{document_id}
# ---------------------------------------------------------------------------

@router.get("/documents/{document_id}", response_model=SOPDocument)
async def get_sop_document(
    document_id: str,
    version: Optional[str] = Query(default=None, description="Optional specific version"),
    user: Identity = Depends(require_permission("sop_rag.read")),
):
    """
    Retrieves full metadata and chunk list for an authoritative SOP document.
    Enforces tenant isolation, plant scoping, and classification clearance.
    """
    try:
        doc = sop_rag_repository.get_document(
            tenant_id=user.tenant_id,
            document_id=document_id,
            version=version,
        )
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SOP document '{document_id}' not found in tenant partition.",
            )

        # Plant check if document is assigned to a plant
        if doc.plant_id and user.assigned_plants and "*" not in user.assigned_plants:
            if doc.plant_id not in user.assigned_plants:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Plant boundary violation: user not authorized for this document plant partition.",
                )

        # Classification & Security Clearance verification
        user_clearance = getattr(user, "clearance_level", 1)
        required_clearance = CLASSIFICATION_CLEARANCE_MAP.get(doc.classification, 3)
        if user_clearance < required_clearance:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: document classification requires higher clearance level.",
            )

        return doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document retrieval failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving the document.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/sop-rag/documents
# ---------------------------------------------------------------------------

@router.get("/documents", response_model=List[SOPDocument])
async def list_sop_documents(
    plant_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    user: Identity = Depends(require_permission("sop_rag.read")),
):
    """
    Lists authoritative SOP documents in tenant partition with optional plant,
    lifecycle status, and clearance filtering.
    """
    if plant_id and user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{plant_id}'.",
            )

    try:
        user_clearance = getattr(user, "clearance_level", 1)
        allowed_cls = get_allowed_classifications_for_clearance(user_clearance)
        statuses = [status_filter] if status_filter else None
        return sop_rag_repository.list_documents(
            tenant_id=user.tenant_id,
            plant_id=plant_id,
            lifecycle_statuses=statuses,
            allowed_classifications=allowed_cls,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document listing failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while listing documents.",
        )


# ---------------------------------------------------------------------------
# PATCH /api/v3/sop-rag/documents/{document_id}/lifecycle
# ---------------------------------------------------------------------------

@router.patch("/documents/{document_id}/lifecycle")
async def update_document_lifecycle(
    document_id: str,
    new_status: DocumentLifecycleStatus = Query(..., description="Target lifecycle state"),
    version: str = Query(..., description="Document revision version"),
    user: Identity = Depends(require_permission("sop_rag.admin")),
):
    """
    Executes a governed lifecycle state transition for an SOP document
    (e.g., DRAFT -> PUBLISHED, PUBLISHED -> SUPERSEDED / REVOKED / ARCHIVED).
    Requires administrative authority (sop_rag.admin).
    Enforces valid state transition matrix and synchronizes child chunks.
    """
    try:
        actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")
        user_permissions = getattr(user, "permissions", [])
        user_roles = getattr(user, "roles", [])

        result = sop_rag_service.transition_lifecycle(
            tenant_id=user.tenant_id,
            document_id=document_id,
            version=version,
            new_status=new_status,
            actor_id=actor_id,
            user_permissions=user_permissions,
            user_roles=user_roles,
        )
        return result
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative permission 'sop_rag.admin' required for lifecycle transitions.",
        )
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' v{version} not found in tenant partition.",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Lifecycle transition failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while updating document lifecycle.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/sop-rag/retrieve
# ---------------------------------------------------------------------------

@router.post("/retrieve", response_model=RetrievalResponse)
async def retrieve_passages(
    request: RetrievalRequest,
    user: Identity = Depends(require_permission("sop_rag.query")),
):
    """
    Executes scoped, deterministic BM25 passage retrieval against eligible SOP chunks.
    Enforces strict tenant isolation, plant scoping, and clearance boundaries.
    """
    if request.tenant_id and request.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot query a different tenant partition.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")
        clearance = getattr(user, "clearance_level", 1)
        user_roles = getattr(user, "roles", [])
        return sop_rag_service.retrieve(
            request=request,
            actor_id=actor_id,
            authoritative_tenant_id=user.tenant_id,
            user_roles=user_roles,
            clearance_level=clearance,
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning("Retrieval validation error: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid retrieval parameters.",
        )
    except Exception as e:
        logger.error("Passage retrieval failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during passage retrieval.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/sop-rag/query
# ---------------------------------------------------------------------------

@router.post("/query", response_model=RAGAnswer)
async def query_rag_answer(
    request: RAGQueryRequest,
    user: Identity = Depends(require_permission("sop_rag.query")),
):
    """
    End-to-end RAG question answering.
    Retrieves authorized evidence, validates sufficiency, builds bounded context,
    and returns an evidence-backed advisory answer with real citations.
    Enforces strict clearance gates across retrieved context and citations.
    """
    if request.tenant_id and request.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot query a different tenant partition.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")
        clearance = getattr(user, "clearance_level", 1)
        user_roles = getattr(user, "roles", [])
        return sop_rag_service.answer_query(
            request=request,
            actor_id=actor_id,
            authoritative_tenant_id=user.tenant_id,
            user_roles=user_roles,
            clearance_level=clearance,
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning("RAG query validation error: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid query parameters.",
        )
    except Exception as e:
        logger.error("RAG query processing failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during RAG query processing.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/sop-rag/audits
# ---------------------------------------------------------------------------

@router.get("/audits", response_model=List[dict])
async def get_sop_audits(
    limit: int = Query(default=50, ge=1, le=200),
    user: Identity = Depends(require_permission("sop_rag.admin")),
):
    """
    Retrieves append-only SOP ingestion and retrieval audit logs for tenant.
    Requires administrative authority (sop_rag.admin).
    """
    try:
        return sop_rag_repository.get_audit_records(
            tenant_id=user.tenant_id,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Audit log retrieval failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving audit logs.",
        )
