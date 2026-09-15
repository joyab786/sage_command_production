# backend/services/db_service.py
"""
SageCommand V3 — Database Service & Backward Compatibility Adapter
Provides URI scheme validation, SQLite file initialization, and a backward-compatible
DynamicDBAdapter delegating to session-scoped DatabaseConnectionManager.
"""

import sqlite3
import os
from sqlalchemy import create_engine
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool

try:
    from core.config import DEFAULT_DB_PATH, SAGE_DB_CONNECTION_TIMEOUT
    from governance.redaction import sanitize_connection_string, parse_safe_connection_info, ConnectionInfo
    from governance.audit import log_security_event
    from data.database_context import AccessMode, DataMode
except ModuleNotFoundError:
    from backend.core.config import DEFAULT_DB_PATH, SAGE_DB_CONNECTION_TIMEOUT
    from backend.governance.redaction import sanitize_connection_string, parse_safe_connection_info, ConnectionInfo
    from backend.governance.audit import log_security_event
    from backend.data.database_context import AccessMode, DataMode

ALLOWED_DB_SCHEMES = {"sqlite", "postgresql", "mysql"}

def validate_db_connection_uri(connection_string: str) -> None:
    """
    Validates database connection URI:
    1. Checks URI scheme against whitelist (sqlite, postgresql, mysql).
    2. Rejects malformed or dangerous connection schemes.
    """
    if not connection_string:
        raise ValueError("Database connection string cannot be empty.")
        
    scheme = connection_string.split(":")[0].lower() if ":" in connection_string else ""
    # Strip drivers (e.g. postgresql+psycopg2 -> postgresql)
    base_scheme = scheme.split("+")[0]
    
    if base_scheme not in ALLOWED_DB_SCHEMES:
        log_security_event(
            "DATABASE_CONNECTION_FAILED",
            {"reason": f"Unsupported DB scheme '{scheme}'", "uri": sanitize_connection_string(connection_string)},
            severity="WARNING"
        )
        raise ValueError(
            f"Security Policy Violation: Database scheme '{scheme}' is not supported. Allowed schemes: {sorted(list(ALLOWED_DB_SCHEMES))}."
        )


def ensure_valid_sqlite(path: str = DEFAULT_DB_PATH):
    """
    Checks if the file at `path` is a valid SQLite database.
    If corrupted or empty, resets file to clean state.
    """
    if not os.path.exists(path):
        return
    
    try:
        conn = sqlite3.connect(path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
    except sqlite3.DatabaseError:
        print(f"[WARNING] Corrupted database detected at '{path}'. Resetting to clean state.")
        conn.close()
        try:
            os.remove(path)
        except OSError:
            pass


class DynamicDBAdapter:
    """
    Backward-Compatibility Adapter around DatabaseConnectionManager.
    Delegates dynamic properties (`engine`, `db`, `query_tool`) to default session connection context.
    [DEPRECATED]: Callers should interact directly with `db_manager.get_connection(...)`.
    """
    DEFAULT_TENANT = "tenant_default"
    DEFAULT_WORKSPACE = "workspace_default"
    DEFAULT_SESSION = "session_default"
    DEFAULT_CONN_ID = "sqlite_main"

    def __init__(self, manager=None):
        self._manager = manager

    @property
    def manager(self):
        if self._manager is None:
            try:
                from services.connection_manager import db_manager
                self._manager = db_manager
            except ModuleNotFoundError:
                from backend.services.connection_manager import db_manager
                self._manager = db_manager
        return self._manager

    def _ensure_default_connection(self):
        """Lazy initializes default connection in db_manager if not present."""
        try:
            _, engine, db, query_tool = self.manager.get_connection(
                self.DEFAULT_TENANT, self.DEFAULT_WORKSPACE, self.DEFAULT_SESSION, self.DEFAULT_CONN_ID
            )
            return engine, db, query_tool
        except (PermissionError, KeyError):
            # Create default connection in db_manager
            ensure_valid_sqlite(DEFAULT_DB_PATH)
            ctx = self.manager.create_connection(
                tenant_id=self.DEFAULT_TENANT,
                workspace_id=self.DEFAULT_WORKSPACE,
                session_id=self.DEFAULT_SESSION,
                connection_string=f"sqlite:///{DEFAULT_DB_PATH}",
                access_mode=AccessMode.READ_WRITE,
                data_mode=DataMode.REAL,
                connection_id=self.DEFAULT_CONN_ID
            )
            _, engine, db, query_tool = self.manager.get_connection(
                self.DEFAULT_TENANT, self.DEFAULT_WORKSPACE, self.DEFAULT_SESSION, self.DEFAULT_CONN_ID
            )
            return engine, db, query_tool

    @property
    def engine(self):
        try:
            engine, _, _ = self._ensure_default_connection()
            return engine
        except Exception:
            return None

    @property
    def db(self):
        try:
            _, db, _ = self._ensure_default_connection()
            return db
        except Exception:
            return None

    @property
    def query_tool(self):
        try:
            _, _, query_tool = self._ensure_default_connection()
            return query_tool
        except Exception:
            return None

    def update_engine_safely(self, new_engine, raw_uri: str = "") -> ConnectionInfo:
        """Adapter bridge updating engine on default session context via db_manager."""
        uri = raw_uri or (str(new_engine.url) if new_engine else f"sqlite:///{DEFAULT_DB_PATH}")
        ctx = self.manager.create_connection(
            tenant_id=self.DEFAULT_TENANT,
            workspace_id=self.DEFAULT_WORKSPACE,
            session_id=self.DEFAULT_SESSION,
            connection_string=uri,
            access_mode=AccessMode.READ_WRITE,
            data_mode=DataMode.REAL,
            connection_id=self.DEFAULT_CONN_ID
        )
        return parse_safe_connection_info(uri)

    def update_engine(self, new_engine):
        """Backward compatibility method."""
        return self.update_engine_safely(new_engine)


# Global adapter instance delegating to db_manager
DynamicDB = DynamicDBAdapter
dynamic_db = DynamicDBAdapter()
