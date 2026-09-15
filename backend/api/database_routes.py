# backend/api/database_routes.py
"""
SageCommand V3 — Database Connection Gateway Canonical API Endpoints
Base Prefix: /api/v3/database
Implements full canonical API contract for connection management, reachability testing,
schema discovery, sensitive-masked sampling, lifecycle management, and strict action boundaries.
"""

import uuid
import re
from typing import Optional
from fastapi import APIRouter, Request, Header, Depends, status
from fastapi.responses import JSONResponse

try:
    from core.auth import Identity, require_role, get_current_identity
    from governance.rate_limiter import rate_limiter
    from governance.audit import log_security_event
    from gateway.db_gateway import db_gateway, GatewayAPIException
    from data.schemas.database_contract import (
        DatabaseType,
        ConnectionStatus,
        AccessMode,
        DataMode,
        GatewayErrorCode,
        ErrorResponse,
        ErrorDetail,
        CreateConnectionRequest,
        CreateConnectionResponse,
        TestConnectionRequest,
        TestConnectionResponse,
        GetConnectionResponse,
        ListConnectionsResponse,
        HealthCheckResponse,
        SchemaDiscoveryResponse,
        SampleDataRequest,
        SampleDataResponse,
        DisconnectResponse,
        RevokeResponse,
    )
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_role, get_current_identity
    from backend.governance.rate_limiter import rate_limiter
    from backend.governance.audit import log_security_event
    from backend.gateway.db_gateway import db_gateway, GatewayAPIException
    from backend.data.schemas.database_contract import (
        DatabaseType,
        ConnectionStatus,
        AccessMode,
        DataMode,
        GatewayErrorCode,
        ErrorResponse,
        ErrorDetail,
        CreateConnectionRequest,
        CreateConnectionResponse,
        TestConnectionRequest,
        TestConnectionResponse,
        GetConnectionResponse,
        ListConnectionsResponse,
        HealthCheckResponse,
        SchemaDiscoveryResponse,
        SampleDataRequest,
        SampleDataResponse,
        DisconnectResponse,
        RevokeResponse,
    )

router = APIRouter(prefix="/api/v3/database", tags=["Database Connection Gateway"])


def extract_request_id(x_request_id: Optional[str] = None) -> str:
    """Extracts, sanitizes, or generates a correlation request identifier."""
    if x_request_id:
        sanitized = re.sub(r"[^\w\-]", "", x_request_id)[:64]
        if sanitized:
            return sanitized
    return f"req_{uuid.uuid4().hex[:12]}"


def error_json_response(status_code: int, code: GatewayErrorCode, message: str, request_id: str) -> JSONResponse:
    """Generates canonical error response envelope."""
    payload = {
        "success": False,
        "request_id": request_id,
        "error": {
            "code": code.value if hasattr(code, "value") else str(code),
            "message": message
        }
    }
    return JSONResponse(status_code=status_code, content=payload)


# =====================================================================
# 1. CREATE CONNECTION
# =====================================================================

@router.post(
    "/connections",
    response_model=CreateConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Database Connection",
    description="Validates target, executes SSRF and TLS checks, stores secrets out-of-band, and registers session connection.",
    responses={
        201: {"model": CreateConnectionResponse, "description": "Connection established safely"},
        400: {"model": ErrorResponse, "description": "Invalid database configuration or TLS violation"},
        403: {"model": ErrorResponse, "description": "Blocked by SSRF/Network policy or unauthorized"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"}
    }
)
async def create_connection(
    request: CreateConnectionRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    identity: Identity = Depends(require_role("manager"))
):
    req_id = extract_request_id(x_request_id)
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        return error_json_response(429, GatewayErrorCode.RATE_LIMITED, "Rate limit exceeded.", req_id)

    try:
        conn = db_gateway.create_canonical_connection(
            request=request,
            identity=identity,
            idempotency_key=idempotency_key
        )
        return CreateConnectionResponse(
            success=True,
            request_id=req_id,
            connection=conn
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 2. TEST CONNECTION
# =====================================================================

@router.post(
    "/connections/test",
    response_model=TestConnectionResponse,
    summary="Test Database Reachability",
    description="Validates reachability and credentials without creating a persistent connection.",
    responses={
        200: {"model": TestConnectionResponse, "description": "Ping test succeeded"},
        400: {"model": ErrorResponse, "description": "Configuration or TLS validation failed"},
        401: {"model": ErrorResponse, "description": "Database authentication failed"},
        403: {"model": ErrorResponse, "description": "Blocked by network policy"},
        408: {"model": ErrorResponse, "description": "Connection timed out"},
        503: {"model": ErrorResponse, "description": "Database unreachable"}
    }
)
async def test_connection(
    request: TestConnectionRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("operator"))
):
    req_id = extract_request_id(x_request_id)
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        return error_json_response(429, GatewayErrorCode.RATE_LIMITED, "Rate limit exceeded.", req_id)

    try:
        result = db_gateway.test_canonical_connection(request=request, identity=identity)
        return TestConnectionResponse(
            success=True,
            request_id=req_id,
            result=result
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 3. LIST CONNECTIONS
# =====================================================================

@router.get(
    "/connections",
    response_model=ListConnectionsResponse,
    summary="List Database Connections",
    description="Returns scoped database connections visible to authorized tenant/session with pagination and filters.",
    responses={
        200: {"model": ListConnectionsResponse, "description": "List of active scoped connections"},
        403: {"model": ErrorResponse, "description": "Cross-tenant access forbidden"}
    }
)
async def list_connections(
    workspace_id: Optional[str] = None,
    plant_id: Optional[str] = None,
    status: Optional[ConnectionStatus] = None,
    database_type: Optional[DatabaseType] = None,
    data_mode: Optional[DataMode] = None,
    limit: int = 20,
    offset: int = 0,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("operator"))
):
    req_id = extract_request_id(x_request_id)
    try:
        items, total = db_gateway.list_canonical_connections(
            tenant_id=identity.tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            status=status,
            database_type=database_type,
            data_mode=data_mode,
            limit=limit,
            offset=offset,
            identity=identity
        )
        return ListConnectionsResponse(
            success=True,
            request_id=req_id,
            connections=items,
            total=total
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 4. GET CONNECTION
# =====================================================================

@router.get(
    "/connections/{connection_id}",
    response_model=GetConnectionResponse,
    summary="Get Database Connection Metadata",
    description="Retrieves canonical connection resource without leaking passwords, tokens, or raw connection strings.",
    responses={
        200: {"model": GetConnectionResponse, "description": "Connection details"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
        409: {"model": ErrorResponse, "description": "Connection revoked"}
    }
)
async def get_connection(
    connection_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("operator"))
):
    req_id = extract_request_id(x_request_id)
    try:
        conn = db_gateway.get_canonical_connection(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity
        )
        return GetConnectionResponse(
            success=True,
            request_id=req_id,
            connection=conn
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 5. HEALTH CHECK
# =====================================================================

@router.get(
    "/connections/{connection_id}/health",
    response_model=HealthCheckResponse,
    summary="Database Connection Health Check",
    description="Executes a live ping on active connection and reports round-trip latency.",
    responses={
        200: {"model": HealthCheckResponse, "description": "Connection healthy"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
        503: {"model": ErrorResponse, "description": "Database health check failed"}
    }
)
async def health_check(
    connection_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("operator"))
):
    req_id = extract_request_id(x_request_id)
    try:
        health_info = db_gateway.health_check_canonical(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity
        )
        return HealthCheckResponse(
            success=True,
            request_id=req_id,
            health=health_info
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 6. SCHEMA DISCOVERY
# =====================================================================

@router.get(
    "/connections/{connection_id}/schema",
    response_model=SchemaDiscoveryResponse,
    summary="Discover Database Schema",
    description="Provides controlled table and column schema inspection with configurable limits.",
    responses={
        200: {"model": SchemaDiscoveryResponse, "description": "Bounded schema discovered"},
        404: {"model": ErrorResponse, "description": "Connection not found"}
    }
)
async def discover_schema(
    connection_id: str,
    schema: Optional[str] = None,
    table: Optional[str] = None,
    limit: int = 50,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("operator"))
):
    req_id = extract_request_id(x_request_id)
    try:
        schema_meta = db_gateway.discover_schema_canonical(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity,
            schema=schema,
            table=table,
            limit=limit
        )
        return SchemaDiscoveryResponse(
            success=True,
            request_id=req_id,
            schema=schema_meta
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 7. SAMPLE DATA
# =====================================================================

@router.post(
    "/connections/{connection_id}/sample",
    response_model=SampleDataResponse,
    summary="Sample Table Data",
    description="Retrieves limited sample rows (max 10) with automatic sensitive-field redaction.",
    responses={
        200: {"model": SampleDataResponse, "description": "Sample rows retrieved with masked sensitive fields"},
        400: {"model": ErrorResponse, "description": "Invalid table or column query"},
        404: {"model": ErrorResponse, "description": "Connection not found"}
    }
)
async def sample_data(
    connection_id: str,
    request: SampleDataRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("operator"))
):
    req_id = extract_request_id(x_request_id)
    try:
        sample_info = db_gateway.get_sample_data_canonical(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity,
            table=request.table,
            limit=request.limit,
            columns=request.columns
        )
        return SampleDataResponse(
            success=True,
            request_id=req_id,
            sample=sample_info
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 8. DISCONNECT
# =====================================================================

@router.post(
    "/connections/{connection_id}/disconnect",
    response_model=DisconnectResponse,
    summary="Disconnect Database Connection",
    description="Disconnects the connection handle and disposes active pool engines.",
    responses={
        200: {"model": DisconnectResponse, "description": "Connection disconnected"},
        404: {"model": ErrorResponse, "description": "Connection not found"}
    }
)
async def disconnect_connection(
    connection_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("manager"))
):
    req_id = extract_request_id(x_request_id)
    try:
        info = db_gateway.disconnect_canonical(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity
        )
        return DisconnectResponse(
            success=True,
            request_id=req_id,
            connection=info
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 9. REVOKE
# =====================================================================

@router.post(
    "/connections/{connection_id}/revoke",
    response_model=RevokeResponse,
    summary="Revoke Database Connection",
    description="Permanently revokes connection for security compliance; subsequent access attempts will be rejected.",
    responses={
        200: {"model": RevokeResponse, "description": "Connection revoked permanently"},
        404: {"model": ErrorResponse, "description": "Connection not found"}
    }
)
async def revoke_connection(
    connection_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("manager"))
):
    req_id = extract_request_id(x_request_id)
    try:
        info = db_gateway.revoke_canonical(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity
        )
        return RevokeResponse(
            success=True,
            request_id=req_id,
            connection=info
        )
    except GatewayAPIException as g_err:
        return error_json_response(g_err.status_code, g_err.code, g_err.message, req_id)
    except Exception as e:
        return error_json_response(500, GatewayErrorCode.INTERNAL_ERROR, f"Internal server error: {str(e)}", req_id)


# =====================================================================
# 10. ROTATE CREDENTIALS (Reserved: 501 Not Implemented)
# =====================================================================

@router.post(
    "/connections/{connection_id}/rotate-credentials",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Rotate Database Credentials (Reserved)",
    description="Returns 501 Not Implemented conforming to canonical API contract.",
    responses={
        501: {"model": ErrorResponse, "description": "Credential rotation not implemented in current release"}
    }
)
async def rotate_credentials(
    connection_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("manager"))
):
    req_id = extract_request_id(x_request_id)
    return error_json_response(
        status.HTTP_501_NOT_IMPLEMENTED,
        GatewayErrorCode.NOT_IMPLEMENTED,
        "Credential rotation is not implemented in current release.",
        req_id
    )
