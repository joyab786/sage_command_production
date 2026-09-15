# backend/api/routes.py
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import create_engine
import pandas as pd
import shutil

try:
    from services.db_service import dynamic_db, validate_db_connection_uri
    from services.connection_manager import db_manager
    from data.database_context import AccessMode, DataMode
    from services.simulator import inject_random_anomaly
    from core.config import DEFAULT_DB_PATH, SAGE_DB_CONNECTION_TIMEOUT
    from core.auth import Identity, get_current_identity, require_role
    from governance.redaction import parse_safe_connection_info, sanitize_connection_string
    from governance.audit import log_security_event
    from governance.rate_limiter import rate_limiter
    from gateway.db_gateway import db_gateway, DBConnectionRequest, DBConnectionResponse
    from gateway.network_policy import DatabasePolicyBlockedError
except ModuleNotFoundError:
    from backend.services.db_service import dynamic_db, validate_db_connection_uri
    from backend.services.connection_manager import db_manager
    from backend.data.database_context import AccessMode, DataMode
    from backend.services.simulator import inject_random_anomaly
    from backend.core.config import DEFAULT_DB_PATH, SAGE_DB_CONNECTION_TIMEOUT
    from backend.core.auth import Identity, get_current_identity, require_role
    from backend.governance.redaction import parse_safe_connection_info, sanitize_connection_string
    from backend.governance.audit import log_security_event
    from backend.governance.rate_limiter import rate_limiter
    from backend.gateway.db_gateway import db_gateway, DBConnectionRequest, DBConnectionResponse
    from backend.gateway.network_policy import DatabasePolicyBlockedError

router = APIRouter()

class LiveDBConnection(BaseModel):
    connection_string: str


@router.post("/trigger-anomaly")
async def trigger_manual_anomaly(identity: Identity = Depends(require_role("manager"))):
    """Triggers an immediate factory anomaly for manual testing (Requires Manager role)."""
    allowed, remaining = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        log_security_event("RATE_LIMIT_TRIGGERED", {"user_id": identity.user_id, "endpoint": "/trigger-anomaly"}, severity="WARNING")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")
        
    anomaly = inject_random_anomaly()
    log_security_event("SECURITY_POLICY_BLOCKED" if not anomaly else "INCIDENT_TRIGGERED", {"user_id": identity.user_id, "anomaly_type": anomaly.get("type")})
    return {"status": "success", "anomaly": anomaly}


@router.post("/connect-live-db")
async def connect_live_db(
    payload: LiveDBConnection,
    identity: Identity = Depends(require_role("manager"))
):
    """Takes a live database URI, validates scheme and network policy, redacts credentials, and registers session connection via Gateway (Requires Manager role)."""
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        log_security_event("RATE_LIMIT_TRIGGERED", {"user_id": identity.user_id, "endpoint": "/connect-live-db"}, severity="WARNING")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")

    try:
        # Determine database type from scheme
        safe_info = parse_safe_connection_info(payload.connection_string)
        
        req = DBConnectionRequest(
            database_type=safe_info.database_type,
            connection_string=payload.connection_string,
            access_mode=AccessMode.READ_WRITE,
            data_mode=DataMode.REAL,
            connection_id="sqlite_main"
        )
        
        resp = db_gateway.create_connection(req, identity=identity)
        
        # Sync adapter for V2/V3 compatibility
        new_engine = create_engine(
            payload.connection_string,
            connect_args={"connect_timeout": SAGE_DB_CONNECTION_TIMEOUT} if "sqlite" not in payload.connection_string else {"check_same_thread": False}
        )
        dynamic_db.update_engine_safely(new_engine, raw_uri=payload.connection_string)
        table_names = dynamic_db.db.get_usable_table_names() if dynamic_db.db else []

        return {
            "status": "success",
            "message": f"Live tether established safely to {resp.database_type}. Detected {len(table_names)} tables.",
            "tables": table_names,
            "connection_info": resp.dict()
        }
    except DatabasePolicyBlockedError as pol_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"DATABASE_POLICY_BLOCKED: {str(pol_err)}")
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))
    except Exception as e:
        safe_err_msg = sanitize_connection_string(str(e))
        log_security_event("DATABASE_CONNECTION_FAILED", {"user_id": identity.user_id, "error": safe_err_msg}, severity="WARNING")
        return {"status": "error", "message": f"Connection failed: {safe_err_msg}"}


@router.post("/upload-db")
async def upload_database(
    file: UploadFile = File(...),
    identity: Identity = Depends(require_role("manager"))
):
    """Receives a CSV/SQLite file, verifies schema, compiles to SQL, and mounts session-scoped engine via Gateway (Requires Manager role)."""
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        log_security_event("RATE_LIMIT_TRIGGERED", {"user_id": identity.user_id, "endpoint": "/upload-db"}, severity="WARNING")
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")

    try:
        file_location = DEFAULT_DB_PATH
        
        # Handle CSV Files
        if file.filename.endswith(".csv"):
            df = pd.read_csv(file.file)
            table_name = file.filename.rsplit('.', 1)[0].replace(" ", "_").replace("-", "_").lower()
            
            new_engine = create_engine(f"sqlite:///{file_location}", connect_args={"check_same_thread": False})
            df.to_sql(table_name, con=new_engine, if_exists="replace", index=False)
            
            req = DBConnectionRequest(
                database_type="SQLITE",
                connection_string=f"sqlite:///{file_location}",
                access_mode=AccessMode.READ_WRITE,
                data_mode=DataMode.REAL,
                connection_id="sqlite_main"
            )
            db_gateway.create_connection(req, identity=identity)
            dynamic_db.update_engine(new_engine)
            log_security_event("DATABASE_CONNECTION_SUCCEEDED", {"user_id": identity.user_id, "action": "csv_upload", "table": table_name})
            return {"status": "success", "message": f"CSV compiled to SQL. Table '{table_name}' mounted successfully."}

        # Handle SQLite/DB Files
        elif file.filename.endswith((".sqlite", ".db")):
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            new_engine = create_engine(f"sqlite:///{file_location}", connect_args={"check_same_thread": False})
            req = DBConnectionRequest(
                database_type="SQLITE",
                connection_string=f"sqlite:///{file_location}",
                access_mode=AccessMode.READ_WRITE,
                data_mode=DataMode.REAL,
                connection_id="sqlite_main"
            )
            db_gateway.create_connection(req, identity=identity)
            dynamic_db.update_engine(new_engine)
            log_security_event("DATABASE_CONNECTION_SUCCEEDED", {"user_id": identity.user_id, "action": "sqlite_upload", "file": file.filename})
            return {"status": "success", "message": f"Datacore {file.filename} mounted successfully."}
            
        else:
            return {"status": "error", "message": "Unsupported file format. Please upload .csv, .db, or .sqlite"}

    except Exception as e:
        safe_err_msg = sanitize_connection_string(str(e))
        return {"status": "error", "message": safe_err_msg}


# --- SAGECOMMAND V3 DATABASE GATEWAY REST API ENDPOINTS ---

@router.post("/api/v3/db/test")
async def gateway_test_connection(
    request: DBConnectionRequest,
    identity: Identity = Depends(require_role("operator"))
):
    """Safe Gateway Connection Test Endpoint (Transient ping without registration)."""
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")
    try:
        res = db_gateway.test_connection(request, identity=identity)
        return res
    except DatabasePolicyBlockedError as pol_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"DATABASE_POLICY_BLOCKED: {str(pol_err)}")
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))


@router.post("/api/v3/db/connect", response_model=DBConnectionResponse)
async def gateway_connect_database(
    request: DBConnectionRequest,
    identity: Identity = Depends(require_role("manager"))
):
    """Establishes and registers a secure database connection handle via Gateway (Requires Manager role)."""
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")
    try:
        resp = db_gateway.create_connection(request, identity=identity)
        return resp
    except DatabasePolicyBlockedError as pol_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"DATABASE_POLICY_BLOCKED: {str(pol_err)}")
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))


@router.post("/api/v3/db/disconnect")
async def gateway_disconnect_database(
    connection_id: str,
    identity: Identity = Depends(require_role("manager"))
):
    """Revokes active database connection handle and closes engine pool."""
    closed = db_gateway.disconnect(
        tenant_id=identity.tenant_id,
        workspace_id="workspace_default",
        session_id=identity.session_id,
        connection_id=connection_id,
        identity=identity
    )
    if not closed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connection '{connection_id}' not found or already closed.")
    return {"status": "success", "message": f"Connection '{connection_id}' revoked and disconnected."}


@router.get("/api/v3/db/health/{connection_id}")
async def gateway_health_check(
    connection_id: str,
    identity: Identity = Depends(require_role("operator"))
):
    """Performs ping health check query on active gateway connection."""
    try:
        return db_gateway.health_check(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity
        )
    except PermissionError as perm_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(perm_err))


@router.get("/api/v3/db/schema/{connection_id}")
async def gateway_discover_schema(
    connection_id: str,
    limit_tables: int = 50,
    identity: Identity = Depends(require_role("operator"))
):
    """Performs controlled schema discovery over an active gateway connection."""
    try:
        return db_gateway.discover_schema(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity,
            limit_tables=limit_tables
        )
    except PermissionError as perm_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(perm_err))


@router.get("/api/v3/db/sample/{connection_id}/{table_name}")
async def gateway_sample_data(
    connection_id: str,
    table_name: str,
    max_rows: int = 5,
    identity: Identity = Depends(require_role("operator"))
):
    """Retrieves limited sample data with automatic sensitive column masking."""
    try:
        return db_gateway.get_data_sample(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            table_name=table_name,
            identity=identity,
            max_rows=max_rows
        )
    except PermissionError as perm_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(perm_err))


@router.get("/api/v3/db/metadata/{connection_id}")
async def gateway_get_metadata(
    connection_id: str,
    identity: Identity = Depends(require_role("operator"))
):
    """Retrieves safe connection metadata without leaking internal credentials or topology."""
    try:
        return db_gateway.get_metadata(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_id=connection_id,
            identity=identity
        )
    except PermissionError as perm_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(perm_err))

