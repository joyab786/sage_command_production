# backend/api/organizational_memory_routes.py
"""
SageCommand V3 — Governed Organizational Memory Foundation API Routes (Prompt 34)

Versioned REST endpoints rooted at /api/v3/memory.
Enforces authentication, RBAC/ABAC permissions, fail-closed tenant isolation,
plant boundary restrictions, classification clearance gates, governed lifecycle transitions,
and safe non-disclosing error responses.

Notice:
ADVISORY ORGANIZATIONAL MEMORY CONTEXT ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT,
OR BYPASSES OPERATIONAL GOVERNANCE.
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger("organizational_memory_routes")

try:
    from core.auth import Identity, get_current_identity, require_permission
    from core.config import SAGE_MEMORY_MAX_SEARCH_RESULTS
    from data.schemas.organizational_memory_contract import (
        OrganizationalMemoryEntry,
        MemoryDraftCreateRequest,
        MemoryDraftUpdateRequest,
        MemoryVerifyRequest,
        MemorySupersedeRequest,
        MemoryArchiveRequest,
        MemorySearchRequest,
        MemorySearchResponse,
        MemoryContextAssemblyRequest,
        MemoryContextResponse,
        MemoryAuditRecord,
        MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE,
    )
    from services.organizational_memory_service import (
        OrganizationalMemoryService,
        organizational_memory_service,
    )
    from repositories.organizational_memory_repository import (
        organizational_memory_repository,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.core.config import SAGE_MEMORY_MAX_SEARCH_RESULTS
    from backend.data.schemas.organizational_memory_contract import (
        OrganizationalMemoryEntry,
        MemoryDraftCreateRequest,
        MemoryDraftUpdateRequest,
        MemoryVerifyRequest,
        MemorySupersedeRequest,
        MemoryArchiveRequest,
        MemorySearchRequest,
        MemorySearchResponse,
        MemoryContextAssemblyRequest,
        MemoryContextResponse,
        MemoryAuditRecord,
        MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE,
    )
    from backend.services.organizational_memory_service import (
        OrganizationalMemoryService,
        organizational_memory_service,
    )
    from backend.repositories.organizational_memory_repository import (
        organizational_memory_repository,
    )

router = APIRouter(
    prefix="/api/v3/memory",
    tags=["Governed Organizational Memory Foundation"],
)


# ---------------------------------------------------------------------------
# POST /api/v3/memory/drafts - Create memory draft
# ---------------------------------------------------------------------------

@router.post("/drafts", response_model=OrganizationalMemoryEntry, status_code=status.HTTP_201_CREATED)
async def create_memory_draft(
    request: MemoryDraftCreateRequest,
    user: Identity = Depends(require_permission("memory.write")),
):
    """
    Creates a new draft organizational memory entry.
    Requires 'memory.write' permission.
    Server-derives tenant and workspace scope; enforces epistemic validations.
    """
    try:
        return organizational_memory_service.create_draft(request, user)
    except PermissionError as pe:
        logger.warning("Draft creation permission denied: %s", pe)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        logger.warning("Draft creation validation error: %s", ve)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error("Draft creation internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create organizational memory draft.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/memory/{memory_id} - Retrieve entry
# ---------------------------------------------------------------------------

@router.get("/{memory_id}", response_model=OrganizationalMemoryEntry)
async def get_memory_entry(
    memory_id: str,
    user: Identity = Depends(require_permission("memory.read")),
):
    """
    Retrieves a single organizational memory entry.
    Requires 'memory.read' permission. Enforces tenant, plant, and clearance boundaries.
    """
    try:
        entry = organizational_memory_service.get_entry(memory_id, user)
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organizational memory entry '{memory_id}' not found.",
            )
        return entry
    except HTTPException:
        raise
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error("Memory retrieval internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve organizational memory entry.",
        )


# ---------------------------------------------------------------------------
# PUT /api/v3/memory/drafts/{memory_id} - Update draft
# ---------------------------------------------------------------------------

@router.put("/drafts/{memory_id}", response_model=OrganizationalMemoryEntry)
async def update_memory_draft(
    memory_id: str,
    request: MemoryDraftUpdateRequest,
    user: Identity = Depends(require_permission("memory.write")),
):
    """
    Updates an existing DRAFT organizational memory entry.
    Requires 'memory.write' permission. Active/verified entries cannot be updated in place.
    """
    try:
        return organizational_memory_service.update_draft(memory_id, request, user)
    except KeyError as ke:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ke))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error("Draft update internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update organizational memory draft.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/memory/{memory_id}/submit - Submit draft for review
# ---------------------------------------------------------------------------

@router.post("/{memory_id}/submit", response_model=OrganizationalMemoryEntry)
async def submit_memory_for_review(
    memory_id: str,
    user: Identity = Depends(require_permission("memory.write")),
):
    """
    Submits a DRAFT memory entry for verification review.
    Transitions status to PENDING_REVIEW.
    """
    try:
        return organizational_memory_service.submit_for_review(memory_id, user)
    except KeyError as ke:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ke))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error("Memory submit internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit organizational memory entry for review.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/memory/{memory_id}/verify - Verify memory entry
# ---------------------------------------------------------------------------

@router.post("/{memory_id}/verify", response_model=OrganizationalMemoryEntry)
async def verify_memory_entry(
    memory_id: str,
    request: MemoryVerifyRequest,
    user: Identity = Depends(require_permission("memory.verify")),
):
    """
    Verifies an organizational memory entry and records authoritative verifier identity.
    Requires 'memory.verify' permission.
    """
    try:
        return organizational_memory_service.verify_entry(memory_id, request, user)
    except KeyError as ke:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ke))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error("Memory verification internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify organizational memory entry.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/memory/{memory_id}/activate - Activate memory entry
# ---------------------------------------------------------------------------

@router.post("/{memory_id}/activate", response_model=OrganizationalMemoryEntry)
async def activate_memory_entry(
    memory_id: str,
    user: Identity = Depends(require_permission("memory.verify")),
):
    """
    Transitions a VERIFIED memory entry into ACTIVE status.
    Requires 'memory.verify' permission.
    """
    try:
        return organizational_memory_service.activate_entry(memory_id, user)
    except KeyError as ke:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ke))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error("Memory activation internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate organizational memory entry.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/memory/{memory_id}/supersede - Supersede memory entry
# ---------------------------------------------------------------------------

@router.post("/{memory_id}/supersede", response_model=Dict[str, Any])
async def supersede_memory_entry(
    memory_id: str,
    request: MemorySupersedeRequest,
    user: Identity = Depends(require_permission("memory.verify")),
):
    """
    Supersedes a memory entry, preserving history and establishing explicit revision linkage.
    Requires 'memory.verify' permission. Blocked if entry is on hold.
    """
    try:
        superseded, replacement = organizational_memory_service.supersede_entry(
            memory_id, request, user
        )
        return {
            "superseded_entry": superseded,
            "replacement_entry": replacement,
            "advisory_notice": MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE,
        }
    except KeyError as ke:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ke))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error("Memory supersession internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to supersede organizational memory entry.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/memory/{memory_id}/archive - Archive memory entry
# ---------------------------------------------------------------------------

@router.post("/{memory_id}/archive", response_model=OrganizationalMemoryEntry)
async def archive_memory_entry(
    memory_id: str,
    request: MemoryArchiveRequest,
    user: Identity = Depends(require_permission("memory.admin")),
):
    """
    Archives an organizational memory entry.
    Requires 'memory.admin' permission. Blocked if entry is on hold.
    """
    try:
        return organizational_memory_service.archive_entry(memory_id, request, user)
    except KeyError as ke:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ke))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error("Memory archival internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to archive organizational memory entry.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/memory/search - Bounded search
# ---------------------------------------------------------------------------

@router.post("/search", response_model=MemorySearchResponse)
async def search_organizational_memory(
    request: MemorySearchRequest,
    user: Identity = Depends(require_permission("memory.read")),
):
    """
    Executes a bounded, authorized search across organizational memory.
    Enforces tenant boundaries, plant scope, and classification ceiling.
    """
    try:
        return organizational_memory_service.search_memory(request, user)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error("Memory search internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search organizational memory.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/memory/context - AI context assembly
# ---------------------------------------------------------------------------

@router.post("/context", response_model=MemoryContextResponse)
async def assemble_ai_memory_context(
    request: MemoryContextAssemblyRequest,
    user: Identity = Depends(require_permission("memory.read")),
):
    """
    Assembles bounded, safe organizational memory context for the AI reasoning layer.
    Encloses entries inside untrusted data fences; surfaces unresolved conflicts.
    """
    try:
        return organizational_memory_service.assemble_context(request, user)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error("Memory context assembly internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assemble organizational memory context.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/memory/{memory_id}/audit - Retrieve audit records
# ---------------------------------------------------------------------------

@router.get("/{memory_id}/audit", response_model=List[MemoryAuditRecord])
async def get_memory_audit_trail(
    memory_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    user: Identity = Depends(require_permission("memory.read")),
):
    """
    Retrieves the audit trail for a specific organizational memory entry.
    Requires 'memory.read' permission.
    """
    try:
        if not user.workspace_id or not user.workspace_id.strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authoritative workspace_id is missing from identity context.",
            )
        entry = organizational_memory_service.get_entry(memory_id, user)
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organizational memory entry '{memory_id}' not found.",
            )
        return organizational_memory_repository.get_audit_records(
            tenant_id=user.tenant_id,
            workspace_id=user.workspace_id,
            memory_id=memory_id,
            limit=limit,
        )
    except HTTPException:
        raise
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error("Memory audit retrieval internal failure: %s", type(e).__name__, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve memory audit records.",
        )
