# backend/services/connection_manager.py
"""
SageCommand V3 — Database Connection Manager Service
Session-aware database manager controlling engine creation pools, connection acquisition,
health checks, access mode authorization, and lifecycle cleanup. Zero global mutable DB state.
"""

import threading
import time
from typing import Dict, Tuple, Optional, Any, List
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool

try:
    from core.config import SAGE_DB_CONNECTION_TIMEOUT, SAGE_DB_POOL_SIZE
    from data.database_context import DatabaseContext, AccessMode, DataMode, ConnectionStatus
    from services.connection_registry import connection_registry, ConnectionRegistry
    from services.db_service import validate_db_connection_uri
    from governance.redaction import parse_safe_connection_info, sanitize_connection_string
    from governance.audit import log_security_event
except ModuleNotFoundError:
    from backend.core.config import SAGE_DB_CONNECTION_TIMEOUT, SAGE_DB_POOL_SIZE
    from backend.data.database_context import DatabaseContext, AccessMode, DataMode, ConnectionStatus
    from backend.services.connection_registry import connection_registry, ConnectionRegistry
    from backend.services.db_service import validate_db_connection_uri
    from backend.governance.redaction import parse_safe_connection_info, sanitize_connection_string
    from backend.governance.audit import log_security_event


class DatabaseConnectionManager:
    """
    Session-Scoped Database Connection Manager.
    Manages SQLAlchemy engine pools and connection handles per Tenant -> Workspace -> Session context.
    """

    def __init__(self, registry: ConnectionRegistry = connection_registry):
        self.registry = registry
        self._lock = threading.RLock()
        # Map: scoped_key -> Tuple[Engine, SQLDatabase, QuerySQLDatabaseTool]
        self._engine_pool: Dict[str, Tuple[Engine, Optional[SQLDatabase], Optional[QuerySQLDatabaseTool]]] = {}

    def _make_key(self, tenant_id: str, workspace_id: str, session_id: str, connection_id: str) -> str:
        return f"{tenant_id}:{workspace_id}:{session_id}:{connection_id}"

    def create_connection(
        self,
        tenant_id: str = "tenant_default",
        workspace_id: str = "workspace_default",
        session_id: str = "session_default",
        connection_string: str = "sqlite:///dynamic_datacore.sqlite",
        access_mode: AccessMode = AccessMode.READ_ONLY,
        data_mode: DataMode = DataMode.REAL,
        plant_id: str = "plant_mumbai",
        connection_id: Optional[str] = None
    ) -> DatabaseContext:
        """
        Validates URI scheme, initializes isolated SQLAlchemy engine, creates DatabaseContext,
        registers connection in ConnectionRegistry, and stores engine handles in pool.
        """
        # 1. Enforce URI scheme whitelist
        validate_db_connection_uri(connection_string)

        safe_info = parse_safe_connection_info(connection_string)
        target_conn_id = connection_id or safe_info.connection_id

        # 2. Build SQLAlchemy Engine with pool boundaries
        connect_args = {}
        if "sqlite" in connection_string:
            connect_args["check_same_thread"] = False
        else:
            connect_args["connect_timeout"] = SAGE_DB_CONNECTION_TIMEOUT

        engine = create_engine(
            connection_string,
            connect_args=connect_args,
            pool_recycle=3600
        )

        # Build SQLDatabase wrapper & query tool
        sql_db = None
        query_tool = None
        try:
            sql_db = SQLDatabase(engine)
            query_tool = QuerySQLDatabaseTool(db=sql_db)
            status = ConnectionStatus.CONNECTED
        except Exception as conn_err:
            log_security_event(
                "DB_CONNECTION_FAILED",
                {"tenant_id": tenant_id, "workspace_id": workspace_id, "error": sanitize_connection_string(str(conn_err))},
                severity="WARNING"
            )
            status = ConnectionStatus.CONNECTION_FAILED

        safe_uri = sanitize_connection_string(connection_string)

        # Create DatabaseContext model
        ctx = DatabaseContext(
            connection_id=target_conn_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            plant_id=plant_id,
            database_type=safe_info.database_type,
            database_name=safe_info.database,
            access_mode=access_mode,
            data_mode=data_mode,
            status=status,
            safe_representation=safe_uri
        )

        scoped_key = self._make_key(tenant_id, workspace_id, session_id, target_conn_id)

        with self._lock:
            self.registry.register(ctx)
            self._engine_pool[scoped_key] = (engine, sql_db, query_tool)

        log_security_event(
            "DB_CONNECTION_CREATED",
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "connection_id": target_conn_id,
                "database_type": safe_info.database_type,
                "access_mode": access_mode.value,
                "data_mode": data_mode.value
            },
            severity="INFO"
        )
        return ctx

    def get_connection(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str
    ) -> Tuple[DatabaseContext, Optional[Engine], Optional[SQLDatabase], Optional[QuerySQLDatabaseTool]]:
        """
        Retrieves connection context and engine handles with strict tenant/workspace/session isolation validation.
        """
        with self._lock:
            ctx = self.registry.lookup(tenant_id, workspace_id, session_id, connection_id)
            if not ctx:
                log_security_event(
                    "DB_ACCESS_DENIED",
                    {"reason": "Connection context not found in registry", "tenant_id": tenant_id, "session_id": session_id, "connection_id": connection_id},
                    severity="WARNING"
                )
                raise PermissionError(f"Access Denied: Connection '{connection_id}' not found or not owned by session '{session_id}'.")

            if ctx.tenant_id != tenant_id or ctx.workspace_id != workspace_id or ctx.session_id != session_id:
                log_security_event(
                    "DB_ACCESS_DENIED",
                    {"reason": "Tenant/Workspace/Session boundary mismatch", "requested": f"{tenant_id}:{workspace_id}:{session_id}", "actual": f"{ctx.tenant_id}:{ctx.workspace_id}:{ctx.session_id}"},
                    severity="WARNING"
                )
                raise PermissionError("Access Denied: Cross-tenant or cross-workspace database access prohibited.")

            scoped_key = self._make_key(tenant_id, workspace_id, session_id, connection_id)
            handles = self._engine_pool.get(scoped_key)
            if not handles:
                raise PermissionError(f"Database engine for connection '{connection_id}' is not loaded or has been closed.")

            return ctx, handles[0], handles[1], handles[2]

    def validate_access(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        required_mode: AccessMode
    ) -> bool:
        """
        Validates that connection exists, belongs to caller session, and satisfies required AccessMode.
        """
        ctx, _, _, _ = self.get_connection(tenant_id, workspace_id, session_id, connection_id)
        if required_mode == AccessMode.READ_WRITE and ctx.access_mode not in (AccessMode.READ_WRITE, AccessMode.ADMIN):
            log_security_event(
                "DB_QUERY_BLOCKED",
                {"reason": "Write attempt on read-only connection", "connection_id": connection_id, "access_mode": ctx.access_mode.value},
                severity="WARNING"
            )
            raise PermissionError(f"Access Violation: Connection '{connection_id}' is configured as '{ctx.access_mode.value}'. Write operation rejected.")

        if required_mode == AccessMode.SIMULATION and ctx.data_mode != DataMode.SIMULATION:
            log_security_event(
                "DB_QUERY_BLOCKED",
                {"reason": "Simulation write attempt on real production database", "connection_id": connection_id, "data_mode": ctx.data_mode.value},
                severity="WARNING"
            )
            raise PermissionError(f"Simulation Safety Violation: Simulation context cannot modify REAL database '{connection_id}'.")

        return True

    def health_check(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str
    ) -> Dict[str, Any]:
        """Runs a ping query on the engine connection and updates status."""
        ctx, engine, _, _ = self.get_connection(tenant_id, workspace_id, session_id, connection_id)
        start_time = time.time()
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            latency_ms = round((time.time() - start_time) * 1000, 2)
            self.registry.update_status(tenant_id, workspace_id, session_id, connection_id, ConnectionStatus.HEALTHY)
            log_security_event(
                "DB_HEALTH_CHECK",
                {"tenant_id": tenant_id, "connection_id": connection_id, "status": "HEALTHY", "latency_ms": latency_ms},
                severity="INFO"
            )
            return {"status": "HEALTHY", "latency_ms": latency_ms, "connection_id": connection_id}
        except Exception as err:
            self.registry.update_status(tenant_id, workspace_id, session_id, connection_id, ConnectionStatus.UNHEALTHY)
            log_security_event(
                "DB_HEALTH_CHECK",
                {"tenant_id": tenant_id, "connection_id": connection_id, "status": "UNHEALTHY", "error": sanitize_connection_string(str(err))},
                severity="WARNING"
            )
            return {"status": "UNHEALTHY", "error": sanitize_connection_string(str(err)), "connection_id": connection_id}

    def disconnect(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str
    ) -> bool:
        """Safely closes engine pool connection and removes context from registry."""
        scoped_key = self._make_key(tenant_id, workspace_id, session_id, connection_id)
        with self._lock:
            handles = self._engine_pool.pop(scoped_key, None)
            if handles and handles[0]:
                try:
                    handles[0].dispose()
                except Exception:
                    pass
            
            ctx = self.registry.remove(tenant_id, workspace_id, session_id, connection_id)
            if ctx or handles:
                log_security_event(
                    "DB_CONNECTION_CLOSED",
                    {"tenant_id": tenant_id, "workspace_id": workspace_id, "session_id": session_id, "connection_id": connection_id},
                    severity="INFO"
                )
                return True
            return False

    def close_all(self):
        """Disposes and cleans up all active engine pools and registered contexts."""
        with self._lock:
            for key, handles in list(self._engine_pool.items()):
                if handles and handles[0]:
                    try:
                        handles[0].dispose()
                    except Exception:
                        pass
            self._engine_pool.clear()
            self.registry.clear()


# Global DatabaseConnectionManager Instance
db_manager = DatabaseConnectionManager()
