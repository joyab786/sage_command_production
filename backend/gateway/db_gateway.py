# backend/gateway/db_gateway.py
"""
SageCommand V3 — Secure Database Connection Gateway
Acts as the mandatory security boundary between SageCommand, external databases, and AI agents.
Enforces authentication, authorization, SSRF network policy, out-of-band secret handling,
connection lifecycle management, schema discovery boundaries, and sensitive data masking.
"""

import datetime
import time
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text, create_engine

try:
    from core.config import SAGE_DB_CONNECTION_TIMEOUT, SAGE_DB_MAX_SAMPLE_ROWS, SAGE_DB_SSL_POLICY, SAGE_DB_IDLE_TIMEOUT, SAGE_DB_MAX_LIFETIME
    from core.auth import Identity
    from data.database_context import DatabaseContext, AccessMode, DataMode, ConnectionStatus
    from services.connection_manager import db_manager, DatabaseConnectionManager
    from services.db_service import validate_db_connection_uri
    from governance.redaction import sanitize_connection_string, parse_safe_connection_info
    from governance.audit import log_security_event
    from gateway.network_policy import network_policy_engine, NetworkPolicyEngine, DatabasePolicyBlockedError
    from gateway.secret_provider import secret_provider, SecretProvider
    from gateway.db_adapters import get_adapter, DatabaseAdapter, DatabaseCapabilities, SupportedDBType
    from data.schemas.database_contract import (
        DatabaseType,
        ConnectionStatus as ContractStatus,
        AccessMode as ContractAccessMode,
        DataMode as ContractDataMode,
        GatewayErrorCode,
        DatabaseConnectionCapabilities,
        DatabaseConnection,
        DatabaseConnectionListItem,
        CreateConnectionRequest,
        TestConnectionRequest,
        TestConnectionResult,
        HealthCheckInfo,
        ColumnMetadata,
        TableMetadata,
        SchemaMetadata,
        SampleDataInfo,
        DisconnectConnectionInfo,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_DB_CONNECTION_TIMEOUT, SAGE_DB_MAX_SAMPLE_ROWS, SAGE_DB_SSL_POLICY, SAGE_DB_IDLE_TIMEOUT, SAGE_DB_MAX_LIFETIME
    from backend.core.auth import Identity
    from backend.data.database_context import DatabaseContext, AccessMode, DataMode, ConnectionStatus
    from backend.services.connection_manager import db_manager, DatabaseConnectionManager
    from backend.services.db_service import validate_db_connection_uri
    from backend.governance.redaction import sanitize_connection_string, parse_safe_connection_info
    from backend.governance.audit import log_security_event
    from backend.gateway.network_policy import network_policy_engine, NetworkPolicyEngine, DatabasePolicyBlockedError
    from backend.gateway.secret_provider import secret_provider, SecretProvider
    from backend.gateway.db_adapters import get_adapter, DatabaseAdapter, DatabaseCapabilities, SupportedDBType
    from backend.data.schemas.database_contract import (
        DatabaseType,
        ConnectionStatus as ContractStatus,
        AccessMode as ContractAccessMode,
        DataMode as ContractDataMode,
        GatewayErrorCode,
        DatabaseConnectionCapabilities,
        DatabaseConnection,
        DatabaseConnectionListItem,
        CreateConnectionRequest,
        TestConnectionRequest,
        TestConnectionResult,
        HealthCheckInfo,
        ColumnMetadata,
        TableMetadata,
        SchemaMetadata,
        SampleDataInfo,
        DisconnectConnectionInfo,
    )


class GatewayAPIException(Exception):
    """Exception carrying canonical Gateway error code, HTTP status, and safe description."""
    def __init__(self, status_code: int, code: GatewayErrorCode, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


SENSITIVE_COLUMN_PATTERNS = re.compile(
    r"(password|secret|token|api_key|apikey|ssn|credit_card|card_number|pin|auth|hash|salt|credential|jwt)",
    re.IGNORECASE
)


def normalize_db_error(err: Exception) -> tuple[str, str]:
    """Maps low-level database and driver exceptions to normalized safe error codes."""
    err_str = str(err).lower()
    if "timed out" in err_str or "timeout" in err_str:
        return "DATABASE_TIMEOUT", "Connection to database host timed out."
    elif "password authentication failed" in err_str or "access denied" in err_str or "login failed" in err_str:
        return "DATABASE_AUTH_FAILED", "Authentication failed for specified database credentials."
    elif "ssl" in err_str or "certificate" in err_str or "tls" in err_str:
        return "DATABASE_TLS_FAILED", "TLS/SSL negotiation failed."
    elif "does not exist" in err_str or "unknown database" in err_str:
        return "DATABASE_NOT_FOUND", "Specified database does not exist on target host."
    elif "refused" in err_str or "could not connect" in err_str or "unreachable" in err_str:
        return "DATABASE_HOST_UNREACHABLE", "Unable to establish network connection to database host."
    elif "policy" in err_str or "blocked" in err_str:
        return "DATABASE_POLICY_BLOCKED", sanitize_connection_string(str(err))
    return "DATABASE_HOST_UNREACHABLE", sanitize_connection_string(str(err))


class DBConnectionRequest(BaseModel):
    database_type: str = Field(default="POSTGRESQL", description="Supported DB engine type")
    host: Optional[str] = Field(default=None, description="Database server hostname or IP")
    port: Optional[int] = Field(default=None, description="Database port number")
    database: Optional[str] = Field(default=None, description="Database name or path")
    username: Optional[str] = Field(default=None, description="Database username")
    password: Optional[str] = Field(default=None, exclude=True, description="Database password (excluded from schema dumps)")
    connection_string: Optional[str] = Field(default=None, description="Raw connection URI (validated safely)")
    ssl_mode: str = Field(default="REQUIRED", description="SSL mode: REQUIRED, OPTIONAL, DISABLED")
    access_mode: AccessMode = Field(default=AccessMode.READ_ONLY, description="Access mode: READ_ONLY or READ_WRITE")
    data_mode: DataMode = Field(default=DataMode.REAL, description="Data mode: REAL or SIMULATION")
    plant_id: str = Field(default="plant_default", description="Associated plant identifier")
    connection_id: Optional[str] = Field(default=None, description="Optional custom connection ID")


class DBConnectionResponse(BaseModel):
    connection_id: str
    tenant_id: str
    workspace_id: str
    session_id: str
    plant_id: str
    database_type: str
    database_name: str
    status: str
    access_mode: str
    data_mode: str
    capabilities: DatabaseCapabilities
    safe_representation: str


class DatabaseConnectionGateway:
    """
    Secure Database Connection Gateway.
    Guarantees deterministic security controls before granting database connectivity.
    """

    def __init__(
        self,
        manager: DatabaseConnectionManager = db_manager,
        net_policy: NetworkPolicyEngine = network_policy_engine,
        sec_provider: SecretProvider = secret_provider
    ):
        self.manager = manager
        self.net_policy = net_policy
        self.sec_provider = sec_provider
        self._idempotency_cache: Dict[str, tuple[float, DatabaseConnection]] = {}
        self._revoked_connections: set[tuple[str, str]] = set()

    def clear_cache(self):
        """Clears transient idempotency and revocation caches (for test isolation)."""
        self._idempotency_cache.clear()
        self._revoked_connections.clear()

    def _validate_identity_ownership(self, identity: Identity, tenant_id: str, session_id: str):
        """Enforces tenant and session ownership matching."""
        if identity.tenant_id != tenant_id or identity.session_id != session_id:
            log_security_event(
                "DATABASE_CONNECTION_REJECTED",
                {"reason": "Tenant or Session ownership mismatch", "user_id": identity.user_id},
                severity="WARNING"
            )
            raise PermissionError("Access Denied: You are not authorized to access connection belonging to another tenant or session.")

    def _check_expiration(self, ctx: DatabaseContext, identity: Identity):
        """Validates connection idle timeout and maximum lifetime."""
        now = time.time()
        if (now - ctx.created_at) > SAGE_DB_MAX_LIFETIME:
            self.disconnect(ctx.tenant_id, ctx.workspace_id, ctx.session_id, ctx.connection_id, identity)
            raise PermissionError("Connection has expired: Maximum connection lifetime exceeded.")
        if (now - ctx.last_used_at) > SAGE_DB_IDLE_TIMEOUT:
            self.disconnect(ctx.tenant_id, ctx.workspace_id, ctx.session_id, ctx.connection_id, identity)
            raise PermissionError("Connection has expired: Idle timeout exceeded.")
        ctx.touch()

    def validate_request(self, request: DBConnectionRequest, identity: Identity) -> tuple[str, DatabaseAdapter]:
        """
        Validates database connection request against supported adapters, scheme whitelists,
        TLS policy, and SSRF network policy guardrails. Returns synthesized connection URI and adapter.
        """
        log_security_event(
            "DATABASE_CONNECTION_REQUESTED",
            {"user_id": identity.user_id, "database_type": request.database_type, "host": request.host or "N/A"},
            severity="INFO"
        )

        # 1. Resolve supported database adapter
        adapter = get_adapter(request.database_type)

        # 2. Enforce TLS Policy for remote databases
        if SAGE_DB_SSL_POLICY == "REQUIRED" and adapter.database_type != SupportedDBType.SQLITE:
            if request.ssl_mode.upper() == "DISABLED":
                log_security_event(
                    "DATABASE_CONNECTION_VALIDATION_FAILED",
                    {"user_id": identity.user_id, "reason": "TLS REQUIRED policy violated (ssl_mode=DISABLED)"},
                    severity="WARNING"
                )
                raise ValueError("DATABASE_TLS_FAILED: TLS is REQUIRED by system policy. Plaintext database connection rejected.")
            if request.connection_string:
                lower_conn = request.connection_string.lower()
                if "sslmode=disable" in lower_conn or "ssl_disabled=true" in lower_conn or "encrypt=no" in lower_conn:
                    log_security_event(
                        "DATABASE_CONNECTION_VALIDATION_FAILED",
                        {"user_id": identity.user_id, "reason": "TLS REQUIRED policy violated in connection string"},
                        severity="WARNING"
                    )
                    raise ValueError("DATABASE_TLS_FAILED: TLS is REQUIRED by system policy. Plaintext database connection rejected.")

        # 3. Extract or synthesize raw URI
        if request.connection_string:
            raw_uri = request.connection_string
            safe_info = parse_safe_connection_info(raw_uri)
            host = safe_info.host or "localhost"
            port = safe_info.port or adapter.default_port
            scheme = safe_info.database_type
        else:
            if not request.database and not request.host:
                raise ValueError("DATABASE_NOT_FOUND: Either host/database parameters or valid connection_string must be provided.")
            host = request.host or "localhost"
            port = request.port or adapter.default_port
            scheme = adapter.database_type.value.lower()
            raw_uri = adapter.build_connection_uri(
                host=host,
                port=port,
                database=request.database or "datacore",
                username=request.username,
                password=request.password,
                ssl_mode=request.ssl_mode
            )

        # 4. Validate connection URI scheme whitelist
        validate_db_connection_uri(raw_uri)

        # 5. Enforce SSRF & Network Policy Guardrails
        try:
            self.net_policy.validate_host_and_port(host=host, port=port, scheme=scheme)
        except DatabasePolicyBlockedError as pol_err:
            log_security_event(
                "DATABASE_CONNECTION_VALIDATION_FAILED",
                {"user_id": identity.user_id, "reason": str(pol_err)},
                severity="WARNING"
            )
            raise pol_err

        return raw_uri, adapter

    def test_connection(self, request: DBConnectionRequest, identity: Identity) -> Dict[str, Any]:
        """
        Performs a transient, safe database ping test without registering the connection.
        """
        raw_uri, adapter = self.validate_request(request, identity)
        start_time = time.time()

        connect_args = {}
        if "sqlite" in raw_uri:
            connect_args["check_same_thread"] = False
        else:
            connect_args["connect_timeout"] = SAGE_DB_CONNECTION_TIMEOUT

        temp_engine = None
        try:
            temp_engine = create_engine(raw_uri, connect_args=connect_args)
            with temp_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            temp_engine.dispose()

            latency_ms = round((time.time() - start_time) * 1000, 2)
            log_security_event(
                "DATABASE_CONNECTION_HEALTH_CHECK",
                {"user_id": identity.user_id, "status": "SUCCESS", "latency_ms": latency_ms},
                severity="INFO"
            )
            return {
                "status": "SUCCESS",
                "message": f"Connection to {adapter.database_type.value} database succeeded.",
                "latency_ms": latency_ms,
                "database_type": adapter.database_type.value,
                "capabilities": adapter.get_capabilities(request.access_mode.value).model_dump()
            }
        except Exception as err:
            if temp_engine:
                try:
                    temp_engine.dispose()
                except Exception:
                    pass
            code, safe_msg = normalize_db_error(err)
            log_security_event(
                "DATABASE_CONNECTION_VALIDATION_FAILED",
                {"user_id": identity.user_id, "error_code": code, "error": safe_msg},
                severity="WARNING"
            )
            return {
                "status": "FAILED",
                "error_code": code,
                "error": f"{code}: {safe_msg}",
                "database_type": adapter.database_type.value
            }

    def create_connection(self, request: DBConnectionRequest, identity: Identity) -> DBConnectionResponse:
        """
        Validates request, stores credentials out-of-band, delegates connection registration
        to DatabaseConnectionManager, and returns safe connection metadata.
        """
        raw_uri, adapter = self.validate_request(request, identity)

        # Store password in SecretProvider out-of-band if provided
        if request.password:
            self.sec_provider.store_secret(request.password, label=f"{identity.user_id}_db_pass")

        # Delegate connection creation & pooling to Prompt 03 Manager
        ctx = self.manager.create_connection(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_string=raw_uri,
            access_mode=request.access_mode,
            data_mode=request.data_mode,
            plant_id=request.plant_id,
            connection_id=request.connection_id
        )

        capabilities = adapter.get_capabilities(request.access_mode.value)

        log_security_event(
            "DATABASE_CONNECTION_ESTABLISHED",
            {
                "user_id": identity.user_id,
                "tenant_id": identity.tenant_id,
                "session_id": identity.session_id,
                "connection_id": ctx.connection_id,
                "database_type": ctx.database_type
            },
            severity="INFO"
        )

        return DBConnectionResponse(
            connection_id=ctx.connection_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=ctx.session_id,
            plant_id=ctx.plant_id,
            database_type=ctx.database_type,
            database_name=ctx.database_name,
            status=ctx.status.value,
            access_mode=ctx.access_mode.value,
            data_mode=ctx.data_mode.value,
            capabilities=capabilities,
            safe_representation=ctx.safe_representation
        )

    def get_connection(self, tenant_id: str, workspace_id: str, session_id: str, connection_id: str, identity: Identity):
        """Retrieves active connection engine handles with ownership and expiration validation."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        ctx, engine, db, query_tool = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        self._check_expiration(ctx, identity)
        return ctx, engine, db, query_tool

    def disconnect(self, tenant_id: str, workspace_id: str, session_id: str, connection_id: str, identity: Identity) -> bool:
        """Revokes connection and closes handles."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        closed = self.manager.disconnect(tenant_id, workspace_id, session_id, connection_id)
        if closed:
            log_security_event(
                "DATABASE_CONNECTION_CLOSED",
                {"user_id": identity.user_id, "connection_id": connection_id},
                severity="INFO"
            )
        return closed

    def health_check(self, tenant_id: str, workspace_id: str, session_id: str, connection_id: str, identity: Identity) -> Dict[str, Any]:
        """Runs health check query on active connection."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        ctx, _, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        self._check_expiration(ctx, identity)
        return self.manager.health_check(tenant_id, workspace_id, session_id, connection_id)

    def discover_schema(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity,
        limit_tables: int = 50
    ) -> Dict[str, Any]:
        """
        Discovers table schemas, column data types, primary keys, and row counts.
        Limits total tables inspected to prevent context window explosion.
        """
        self._validate_identity_ownership(identity, tenant_id, session_id)
        ctx, engine, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        self._check_expiration(ctx, identity)

        inspector = inspect(engine)
        all_tables = inspector.get_table_names()
        total_table_count = len(all_tables)
        target_tables = all_tables[:limit_tables]

        schema_inventory = []
        for tbl in target_tables:
            columns = []
            for col in inspector.get_columns(tbl):
                columns.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True)
                })

            pk_constraint = inspector.get_pk_constraint(tbl)
            primary_keys = pk_constraint.get("constrained_columns", []) if pk_constraint else []

            schema_inventory.append({
                "table_name": tbl,
                "column_count": len(columns),
                "columns": columns,
                "primary_keys": primary_keys
            })

        log_security_event(
            "DATABASE_SCHEMA_INSPECTED",
            {"user_id": identity.user_id, "connection_id": connection_id, "tables_discovered": len(schema_inventory)},
            severity="INFO"
        )

        return {
            "connection_id": connection_id,
            "database_type": ctx.database_type,
            "table_count": total_table_count,
            "tables": schema_inventory
        }

    def get_data_sample(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        table_name: str,
        identity: Identity,
        max_rows: int = 5
    ) -> Dict[str, Any]:
        """
        Retrieves limited sample rows from a table with automatic sensitive column value masking.
        """
        self._validate_identity_ownership(identity, tenant_id, session_id)
        ctx, engine, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        self._check_expiration(ctx, identity)

        sample_limit = min(max(1, max_rows), SAGE_DB_MAX_SAMPLE_ROWS)

        # Sanitize table name against SQL injection
        clean_tbl = re.sub(r"[^\w_]", "", table_name)

        query = text(f"SELECT * FROM {clean_tbl} LIMIT :limit")

        rows = []
        columns = []
        with engine.connect() as conn:
            result = conn.execute(query, {"limit": sample_limit})
            columns = list(result.keys())

            for row in result:
                row_dict = {}
                for idx, col in enumerate(columns):
                    val = row[idx]
                    # Apply sensitive column value masking
                    if SENSITIVE_COLUMN_PATTERNS.search(col):
                        row_dict[col] = "[REDACTED]"
                    else:
                        row_dict[col] = str(val) if val is not None else None
                rows.append(row_dict)

        log_security_event(
            "DATABASE_SAMPLE_REQUESTED",
            {"user_id": identity.user_id, "connection_id": connection_id, "table": clean_tbl, "rows_returned": len(rows)},
            severity="INFO"
        )

        return {
            "connection_id": connection_id,
            "table_name": clean_tbl,
            "row_count": len(rows),
            "columns": columns,
            "sample_rows": rows
        }

    def get_metadata(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity
    ) -> Dict[str, Any]:
        """
        Retrieves safe connection metadata without leaking secrets, internal IPs, or driver topologies.
        """
        self._validate_identity_ownership(identity, tenant_id, session_id)
        ctx, engine, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        self._check_expiration(ctx, identity)

        insp = inspect(engine)
        all_tables = insp.get_table_names()

        return {
            "connection_id": ctx.connection_id,
            "status": ctx.status.value,
            "database_type": ctx.database_type,
            "access_mode": ctx.access_mode.value,
            "data_mode": ctx.data_mode.value,
            "table_count": len(all_tables),
            "plant_id": ctx.plant_id,
            "safe_representation": ctx.safe_representation
        }

    def get_schema_context_for_llm(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity,
        limit_tables: int = 20
    ) -> str:
        """
        Generates minimal, safe schema representation for LLM prompt context.
        Completely excludes credentials, network hostnames, or system tables.
        """
        schema = self.discover_schema(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            connection_id=connection_id,
            identity=identity,
            limit_tables=limit_tables
        )
        lines = [f"Database Type: {schema['database_type']} (Total Tables: {schema['table_count']})"]
        for tbl in schema["tables"]:
            col_desc = ", ".join([f"{c['name']} ({c['type']})" for c in tbl["columns"]])
            lines.append(f"Table '{tbl['table_name']}': [{col_desc}]")
        return "\n".join(lines)

    # =========================================================================
    # CANONICAL API CONTRACT METHODS (/api/v3/database/*)
    # =========================================================================

    def create_canonical_connection(
        self,
        request: CreateConnectionRequest,
        identity: Identity,
        idempotency_key: Optional[str] = None
    ) -> DatabaseConnection:
        """
        Canonical connection creation conforming to Prompt 04 contract.
        Supports optional Idempotency-Key caching, out-of-band secrets,
        policy enforcement, and returns DatabaseConnection.
        """
        # 1. Idempotency Cache Check
        if idempotency_key:
            cache_key = f"{identity.tenant_id}:{idempotency_key}"
            if cache_key in self._idempotency_cache:
                ts, cached_conn = self._idempotency_cache[cache_key]
                if time.time() - ts < 300:  # 5-minute TTL
                    return cached_conn

        # 2. Build or extract connection URI
        db_type_str = request.database_type.value.upper()
        adapter = get_adapter(db_type_str)

        ssl_mode = request.ssl.mode if request.ssl else "REQUIRED"

        # Convert to internal DBConnectionRequest for validation
        internal_req = DBConnectionRequest(
            database_type=db_type_str,
            host=request.host,
            port=request.port,
            database=request.database,
            username=request.username,
            password=request.password,
            connection_string=request.connection_string,
            ssl_mode=ssl_mode,
            access_mode=AccessMode(request.access_mode.value),
            data_mode=DataMode(request.data_mode.value),
            plant_id=request.plant_id or "plant_001"
        )

        try:
            raw_uri, _ = self.validate_request(internal_req, identity)
        except DatabasePolicyBlockedError as pol_err:
            raise GatewayAPIException(403, GatewayErrorCode.DATABASE_POLICY_BLOCKED, str(pol_err))
        except ValueError as val_err:
            v_str = str(val_err)
            if "TLS REQUIRED" in v_str:
                raise GatewayAPIException(400, GatewayErrorCode.DATABASE_TLS_REQUIRED, v_str)
            elif "Unsupported" in v_str:
                raise GatewayAPIException(400, GatewayErrorCode.INVALID_DATABASE_TYPE, v_str)
            elif "not found" in v_str.lower():
                raise GatewayAPIException(404, GatewayErrorCode.DATABASE_NOT_FOUND, v_str)
            else:
                raise GatewayAPIException(400, GatewayErrorCode.INVALID_DATABASE_CONFIGURATION, v_str)

        # 3. Store secret out-of-band if provided
        if request.password:
            self.sec_provider.store_secret(request.password, label=f"{identity.user_id}_db_pass")

        # 4. Delegate to Connection Manager
        ctx = self.manager.create_connection(
            tenant_id=identity.tenant_id,
            workspace_id="workspace_default",
            session_id=identity.session_id,
            connection_string=raw_uri,
            access_mode=internal_req.access_mode,
            data_mode=internal_req.data_mode,
            plant_id=internal_req.plant_id
        )

        created_iso = datetime.datetime.fromtimestamp(ctx.created_at, tz=datetime.timezone.utc).isoformat()
        last_used_iso = datetime.datetime.fromtimestamp(ctx.last_used_at, tz=datetime.timezone.utc).isoformat()

        conn_resource = DatabaseConnection(
            connection_id=ctx.connection_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=ctx.session_id,
            plant_id=ctx.plant_id or "plant_001",
            database_type=request.database_type,
            database_name=ctx.database_name,
            status=ContractStatus.CONNECTED,
            access_mode=request.access_mode,
            data_mode=request.data_mode,
            capabilities=DatabaseConnectionCapabilities(
                read=True,
                write=(request.access_mode == ContractAccessMode.READ_WRITE or request.access_mode == ContractAccessMode.ADMIN),
                transactions=False,
                schema_inspection=True
            ),
            created_at=created_iso,
            last_used_at=last_used_iso
        )

        # Cache if idempotency key provided
        if idempotency_key:
            self._idempotency_cache[cache_key] = (time.time(), conn_resource)

        log_security_event(
            "DATABASE_CONNECTION_ESTABLISHED",
            {
                "user_id": identity.user_id,
                "tenant_id": identity.tenant_id,
                "session_id": identity.session_id,
                "connection_id": ctx.connection_id,
                "database_type": ctx.database_type
            },
            severity="INFO"
        )

        return conn_resource

    def test_canonical_connection(
        self,
        request: TestConnectionRequest,
        identity: Identity
    ) -> TestConnectionResult:
        """
        Validates whether a database can be reached without creating a persistent connection.
        """
        db_type_str = request.database_type.value.upper()
        ssl_mode = request.ssl.mode if request.ssl else "REQUIRED"

        internal_req = DBConnectionRequest(
            database_type=db_type_str,
            host=request.host,
            port=request.port,
            database=request.database,
            username=request.username,
            password=request.password,
            connection_string=request.connection_string,
            ssl_mode=ssl_mode
        )

        try:
            raw_uri, adapter = self.validate_request(internal_req, identity)
        except DatabasePolicyBlockedError as pol_err:
            raise GatewayAPIException(403, GatewayErrorCode.DATABASE_POLICY_BLOCKED, str(pol_err))
        except ValueError as val_err:
            v_str = str(val_err)
            if "TLS REQUIRED" in v_str:
                raise GatewayAPIException(400, GatewayErrorCode.DATABASE_TLS_REQUIRED, v_str)
            elif "Unsupported" in v_str:
                raise GatewayAPIException(400, GatewayErrorCode.INVALID_DATABASE_TYPE, v_str)
            else:
                raise GatewayAPIException(400, GatewayErrorCode.INVALID_DATABASE_CONFIGURATION, v_str)

        start_time = time.time()
        connect_args = {}
        if "sqlite" in raw_uri:
            connect_args["check_same_thread"] = False
        else:
            connect_args["connect_timeout"] = SAGE_DB_CONNECTION_TIMEOUT

        temp_engine = None
        try:
            temp_engine = create_engine(raw_uri, connect_args=connect_args)
            with temp_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            temp_engine.dispose()

            latency_ms = round((time.time() - start_time) * 1000, 2)
            return TestConnectionResult(
                reachable=True,
                authenticated=True,
                database_type=request.database_type,
                latency_ms=latency_ms
            )
        except Exception as err:
            if temp_engine:
                try:
                    temp_engine.dispose()
                except Exception:
                    pass
            code, safe_msg = normalize_db_error(err)
            status_code = 503
            if code == "DATABASE_AUTH_FAILED":
                status_code = 401
                err_code = GatewayErrorCode.DATABASE_AUTH_FAILED
            elif code == "DATABASE_TIMEOUT":
                status_code = 408
                err_code = GatewayErrorCode.DATABASE_TIMEOUT
            elif code == "DATABASE_TLS_FAILED":
                status_code = 400
                err_code = GatewayErrorCode.DATABASE_TLS_FAILED
            elif code == "DATABASE_NOT_FOUND":
                status_code = 404
                err_code = GatewayErrorCode.DATABASE_NOT_FOUND
            else:
                err_code = GatewayErrorCode.DATABASE_UNREACHABLE

            raise GatewayAPIException(status_code, err_code, safe_msg)

    def get_canonical_connection(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity
    ) -> DatabaseConnection:
        """Retrieves safe DatabaseConnection metadata with ownership and lifecycle verification."""
        self._validate_identity_ownership(identity, tenant_id, session_id)

        # Check revocation tombstone
        if (tenant_id, connection_id) in self._revoked_connections:
            raise GatewayAPIException(409, GatewayErrorCode.CONNECTION_REVOKED, f"Connection '{connection_id}' has been revoked.")

        try:
            ctx, _, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        except (KeyError, PermissionError):
            if any(c.connection_id == connection_id for c in self.manager.registry.contexts.values()):
                raise GatewayAPIException(403, GatewayErrorCode.AUTHORIZATION_DENIED, "Access Denied: Connection belongs to another tenant or session.")
            raise GatewayAPIException(404, GatewayErrorCode.CONNECTION_NOT_FOUND, f"Connection '{connection_id}' not found.")

        if ctx.status == ConnectionStatus.REVOKED:
            raise GatewayAPIException(409, GatewayErrorCode.CONNECTION_REVOKED, f"Connection '{connection_id}' has been revoked.")

        self._check_expiration(ctx, identity)

        created_iso = datetime.datetime.fromtimestamp(ctx.created_at, tz=datetime.timezone.utc).isoformat()
        last_used_iso = datetime.datetime.fromtimestamp(ctx.last_used_at, tz=datetime.timezone.utc).isoformat()

        # Map to contract enums safely
        try:
            contract_db_type = DatabaseType(ctx.database_type.upper())
        except ValueError:
            contract_db_type = DatabaseType.SQLITE

        status_str = ctx.status.value.upper()
        try:
            contract_status = ContractStatus(status_str)
        except ValueError:
            contract_status = ContractStatus.CONNECTED

        return DatabaseConnection(
            connection_id=ctx.connection_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=ctx.session_id,
            plant_id=ctx.plant_id or "plant_001",
            database_type=contract_db_type,
            database_name=ctx.database_name,
            status=contract_status,
            access_mode=ContractAccessMode(ctx.access_mode.value),
            data_mode=ContractDataMode(ctx.data_mode.value),
            capabilities=DatabaseConnectionCapabilities(
                read=True,
                write=(ctx.access_mode.value == "READ_WRITE" or ctx.access_mode.value == "ADMIN"),
                transactions=False,
                schema_inspection=True
            ),
            created_at=created_iso,
            last_used_at=last_used_iso
        )

    def list_canonical_connections(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        status: Optional[ContractStatus] = None,
        database_type: Optional[DatabaseType] = None,
        data_mode: Optional[ContractDataMode] = None,
        limit: int = 20,
        offset: int = 0,
        identity: Optional[Identity] = None
    ) -> tuple[List[DatabaseConnectionListItem], int]:
        """
        Lists scoped connections visible to authorized tenant/session with pagination and filters.
        """
        if identity and identity.tenant_id != tenant_id:
            raise GatewayAPIException(403, GatewayErrorCode.AUTHORIZATION_DENIED, "Cannot query another tenant's connections.")

        all_contexts = list(self.manager.registry.contexts.values())
        filtered = []

        safe_limit = min(max(1, limit), 100)
        safe_offset = max(0, offset)

        for ctx in all_contexts:
            # Tenant isolation
            if ctx.tenant_id != tenant_id:
                continue
            # Session isolation if identity provided
            if identity and ctx.session_id != identity.session_id:
                continue
            # Revocation check
            if (ctx.tenant_id, ctx.connection_id) in self._revoked_connections or ctx.status == ConnectionStatus.REVOKED:
                if status and status != ContractStatus.REVOKED:
                    continue
            if workspace_id and ctx.workspace_id != workspace_id:
                continue
            if plant_id and ctx.plant_id != plant_id:
                continue
            if status and ctx.status.value.upper() != status.value:
                continue
            if database_type and ctx.database_type.upper() != database_type.value:
                continue
            if data_mode and ctx.data_mode.value != data_mode.value:
                continue

            try:
                db_type_enum = DatabaseType(ctx.database_type.upper())
            except ValueError:
                db_type_enum = DatabaseType.SQLITE

            try:
                status_enum = ContractStatus(ctx.status.value.upper())
            except ValueError:
                status_enum = ContractStatus.CONNECTED

            filtered.append(DatabaseConnectionListItem(
                connection_id=ctx.connection_id,
                database_type=db_type_enum,
                status=status_enum,
                access_mode=ContractAccessMode(ctx.access_mode.value),
                data_mode=ContractDataMode(ctx.data_mode.value)
            ))

        total = len(filtered)
        paginated = filtered[safe_offset : safe_offset + safe_limit]
        return paginated, total

    def disconnect_canonical(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity
    ) -> DisconnectConnectionInfo:
        """Disconnects connection handle and disposes engine."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        if (tenant_id, connection_id) in self._revoked_connections:
            raise GatewayAPIException(409, GatewayErrorCode.CONNECTION_REVOKED, f"Connection '{connection_id}' has been revoked.")

        closed = self.manager.disconnect(tenant_id, workspace_id, session_id, connection_id)
        if not closed:
            raise GatewayAPIException(404, GatewayErrorCode.CONNECTION_NOT_FOUND, f"Connection '{connection_id}' not found.")

        log_security_event(
            "DATABASE_CONNECTION_CLOSED",
            {"user_id": identity.user_id, "connection_id": connection_id},
            severity="INFO"
        )
        return DisconnectConnectionInfo(
            connection_id=connection_id,
            status=ContractStatus.DISCONNECTED
        )

    def revoke_canonical(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity
    ) -> DisconnectConnectionInfo:
        """Revokes connection permanently for security/admin compliance."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        # Mark in revoked set
        self._revoked_connections.add((tenant_id, connection_id))

        # Close engine and unregister
        self.manager.disconnect(tenant_id, workspace_id, session_id, connection_id)

        log_security_event(
            "DATABASE_CONNECTION_REVOKED",
            {"user_id": identity.user_id, "tenant_id": tenant_id, "connection_id": connection_id},
            severity="WARNING"
        )
        return DisconnectConnectionInfo(
            connection_id=connection_id,
            status=ContractStatus.REVOKED
        )

    def health_check_canonical(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity
    ) -> HealthCheckInfo:
        """Executes ping on active connection and returns canonical HealthCheckInfo."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        if (tenant_id, connection_id) in self._revoked_connections:
            raise GatewayAPIException(409, GatewayErrorCode.CONNECTION_REVOKED, f"Connection '{connection_id}' has been revoked.")

        try:
            ctx, engine, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        except (KeyError, PermissionError):
            raise GatewayAPIException(404, GatewayErrorCode.CONNECTION_NOT_FOUND, f"Connection '{connection_id}' not found.")

        if ctx.status == ConnectionStatus.REVOKED:
            raise GatewayAPIException(409, GatewayErrorCode.CONNECTION_REVOKED, f"Connection '{connection_id}' has been revoked.")

        self._check_expiration(ctx, identity)

        start = time.time()
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            latency_ms = round((time.time() - start) * 1000, 2)
            checked_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return HealthCheckInfo(
                status=ContractStatus.HEALTHY,
                latency_ms=latency_ms,
                checked_at=checked_iso
            )
        except Exception:
            raise GatewayAPIException(503, GatewayErrorCode.DATABASE_UNREACHABLE, f"Database health check failed for '{connection_id}'.")

    def discover_schema_canonical(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        limit: int = 50
    ) -> SchemaMetadata:
        """Provides controlled schema metadata conforming to SchemaMetadata model."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        if (tenant_id, connection_id) in self._revoked_connections:
            raise GatewayAPIException(409, GatewayErrorCode.CONNECTION_REVOKED, f"Connection '{connection_id}' has been revoked.")

        try:
            ctx, engine, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        except (KeyError, PermissionError):
            raise GatewayAPIException(404, GatewayErrorCode.CONNECTION_NOT_FOUND, f"Connection '{connection_id}' not found.")

        self._check_expiration(ctx, identity)

        safe_limit = min(max(1, limit), 100)
        try:
            inspector = inspect(engine)
            all_tables = inspector.get_table_names(schema=schema)
        except Exception as e:
            raise GatewayAPIException(500, GatewayErrorCode.SCHEMA_DISCOVERY_FAILED, f"Schema discovery failed: {str(e)}")

        if table:
            target_tables = [t for t in all_tables if t == table]
        else:
            target_tables = all_tables[:safe_limit]

        tables_meta = []
        for tbl in target_tables:
            columns_meta = []
            for col in inspector.get_columns(tbl, schema=schema):
                columns_meta.append(ColumnMetadata(
                    name=col["name"],
                    type=str(col["type"]),
                    nullable=col.get("nullable", True)
                ))
            tables_meta.append(TableMetadata(name=tbl, columns=columns_meta))

        log_security_event(
            "DATABASE_SCHEMA_INSPECTED",
            {"user_id": identity.user_id, "connection_id": connection_id, "tables_discovered": len(tables_meta)},
            severity="INFO"
        )
        return SchemaMetadata(tables=tables_meta)

    def get_sample_data_canonical(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        identity: Identity,
        table: str,
        limit: int = 10,
        columns: Optional[List[str]] = None
    ) -> SampleDataInfo:
        """Retrieves bounded sample data with column filtering and sensitive masking."""
        self._validate_identity_ownership(identity, tenant_id, session_id)
        if (tenant_id, connection_id) in self._revoked_connections:
            raise GatewayAPIException(409, GatewayErrorCode.CONNECTION_REVOKED, f"Connection '{connection_id}' has been revoked.")

        try:
            ctx, engine, _, _ = self.manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        except (KeyError, PermissionError):
            raise GatewayAPIException(404, GatewayErrorCode.CONNECTION_NOT_FOUND, f"Connection '{connection_id}' not found.")

        self._check_expiration(ctx, identity)

        sample_limit = min(max(1, limit), 10)  # Max 10 rows
        clean_tbl = re.sub(r"[^\w_]", "", table)

        query = text(f"SELECT * FROM {clean_tbl} LIMIT :limit")
        rows = []
        try:
            with engine.connect() as conn:
                res = conn.execute(query, {"limit": sample_limit})
                all_cols = list(res.keys())

                # Filter columns if specified
                if columns:
                    target_cols = [c for c in columns if c in all_cols][:50]
                else:
                    target_cols = all_cols[:50]

                for row in res:
                    row_dict = {}
                    for col_name in target_cols:
                        val = getattr(row, col_name, None)
                        if val is None:
                            val = row._mapping.get(col_name) if hasattr(row, "_mapping") else None
                        if SENSITIVE_COLUMN_PATTERNS.search(col_name):
                            row_dict[col_name] = "[REDACTED]"
                        else:
                            row_dict[col_name] = str(val) if val is not None else None
                    rows.append(row_dict)

            return SampleDataInfo(
                table=clean_tbl,
                columns=target_cols,
                rows=rows
            )
        except Exception as e:
            raise GatewayAPIException(400, GatewayErrorCode.INVALID_REQUEST, f"Failed to sample table '{clean_tbl}': {str(e)}")


# Global Gateway Instance
db_gateway = DatabaseConnectionGateway()
