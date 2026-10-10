# backend/api/sop_rag_routes.py
"""
SageCommand V3 — SOP / RAG Intelligence Foundation API Routes (Prompt 33)

Versioned REST endpoints rooted at /api/v3/sop-rag.
Enforces authentication, RBAC/ABAC permissions, fail-closed tenant isolation,
plant boundary restrictions, payload bounds, and non-disclosing error responses.

Notice:
ADVISORY SOP KNOWLEDGE ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT, OR BYPASSES OPERATIONAL GOVERNANCE
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, get_current_identity, require_permission
    from core.config import SAGE_SOP_MAX_RETRIEVAL_RESULTS
    from data.schemas.sop_rag_contract import (
        SOPDocument,
        DocumentChunk,
        DocumentLifecycleStatus,
        IngestionRequest,
        IngestionResult,
        RetrievalRequest,
        RetrievalResponse,
        RAGQueryRequest,
        RAGAnswer,
        SOPAuditRecord,
        MANDATORY_SOP_RAG_NOTICE,
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
        IngestionRequest,
        IngestionResult,
        RetrievalRequest,
        RetrievalResponse,
        RAGQueryRequest,
        RAGAnswer,
        SOPAuditRecord,
        MANDATORY_SOP_RAG_NOTICE,
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
    Enforces tenant partition isolation and plant boundary access control.
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
        result = sop_rag_service.ingest_document(
            request=request,
            actor_id=actor_id,
            authoritative_tenant_id=user.tenant_id,
            clearance_level=clearance,
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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion processing failed: {str(e)}",
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
    """
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
                detail=f"Plant boundary violation: user not authorized for plant '{doc.plant_id}'.",
            )

    return doc


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
    Lists authoritative SOP documents in tenant partition with optional plant and status filtering.
    """
    if plant_id and user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{plant_id}'.",
            )

    statuses = [status_filter] if status_filter else None
    return sop_rag_repository.list_documents(
        tenant_id=user.tenant_id,
        plant_id=plant_id,
        lifecycle_statuses=statuses,
        limit=limit,
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
    Updates the lifecycle status of an authoritative SOP document (e.g., PUBLISHED, REVOKED, ARCHIVED).
    Requires administrative authority.
    """
    success = sop_rag_repository.update_lifecycle_status(
        tenant_id=user.tenant_id,
        document_id=document_id,
        version=version,
        new_status=new_status,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' v{version} not found in tenant.",
        )
    return {
        "document_id": document_id,
        "version": version,
        "new_status": new_status.value,
        "message": f"Successfully updated lifecycle status to {new_status.value}.",
        "notice": MANDATORY_SOP_RAG_NOTICE,
    }


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
    Enforces strict tenant isolation and caller authorization boundaries.
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
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
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
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
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
    Requires administrative authority.
    """
    return sop_rag_repository.get_audit_records(
        tenant_id=user.tenant_id,
        limit=limit,
    )
