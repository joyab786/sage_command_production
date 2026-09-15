# backend/gateway/db_adapters.py
"""
SageCommand V3 — Database Adapter Architecture
Provides driver abstractions, connection URI synthesis, and explicit capability declarations
for supported database engines: PostgreSQL, MySQL, SQLServer, and SQLite.
"""

import abc
import time
import urllib.parse
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine


class SupportedDBType(str, Enum):
    POSTGRESQL = "POSTGRESQL"
    MYSQL = "MYSQL"
    SQLSERVER = "SQLSERVER"
    SQLITE = "SQLITE"


class DatabaseCapabilities(BaseModel):
    read: bool = True
    write: bool = False
    transactions: bool = True
    schema_inspection: bool = True
    max_sample_rows: int = 100


class DatabaseAdapter(abc.ABC):
    """Abstract database adapter interface defining standard connectivity and inspection operations."""

    @property
    @abc.abstractmethod
    def database_type(self) -> SupportedDBType:
        pass

    @property
    @abc.abstractmethod
    def default_port(self) -> Optional[int]:
        pass

    @abc.abstractmethod
    def build_connection_uri(
        self,
        host: str,
        port: Optional[int],
        database: str,
        username: Optional[str],
        password: Optional[str],
        ssl_mode: str = "REQUIRED",
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """Constructs safe driver connection URI."""
        pass

    @abc.abstractmethod
    def get_capabilities(self, access_mode: str = "READ_ONLY") -> DatabaseCapabilities:
        """Returns capabilities granted under caller access mode."""
        pass

    def validate_uri(self, uri: str) -> bool:
        """Validates URI scheme and query parameters."""
        parsed = urllib.parse.urlparse(uri)
        if not parsed.scheme:
            raise ValueError("Invalid connection URI: Scheme missing.")
        return True

    def connect(self, uri: str, timeout: int = 10) -> Engine:
        """Creates an isolated SQLAlchemy engine for this adapter."""
        connect_args = {}
        if self.database_type != SupportedDBType.SQLITE:
            connect_args["connect_timeout"] = timeout
        else:
            connect_args["check_same_thread"] = False
        return create_engine(uri, connect_args=connect_args, pool_recycle=3600)

    def health_check(self, engine: Engine) -> Dict[str, Any]:
        """Runs a minimal health check query (SELECT 1)."""
        start = time.time()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = round((time.time() - start) * 1000, 2)
        return {"status": "HEALTHY", "latency_ms": latency_ms}

    def get_schema(self, engine: Engine, limit_tables: int = 50) -> Dict[str, Any]:
        """Discovers tables, columns, primary keys, and types within safe limit boundaries."""
        insp = inspect(engine)
        all_tables = insp.get_table_names()
        target_tables = all_tables[:limit_tables]

        inventory = []
        for tbl in target_tables:
            cols = []
            for col in insp.get_columns(tbl):
                cols.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True)
                })
            pk = insp.get_pk_constraint(tbl)
            primary_keys = pk.get("constrained_columns", []) if pk else []
            inventory.append({
                "table_name": tbl,
                "column_count": len(cols),
                "columns": cols,
                "primary_keys": primary_keys
            })

        return {
            "database_type": self.database_type.value,
            "table_count": len(all_tables),
            "tables": inventory
        }

    def get_metadata(self, engine: Engine) -> Dict[str, Any]:
        """Retrieves safe metadata without exposing secrets or network internals."""
        insp = inspect(engine)
        all_tables = insp.get_table_names()
        return {
            "database_type": self.database_type.value,
            "table_count": len(all_tables),
            "driver": engine.dialect.name
        }

    def close(self, engine: Engine):
        """Safely disposes the engine pool."""
        if engine:
            engine.dispose()


class PostgreSQLAdapter(DatabaseAdapter):
    @property
    def database_type(self) -> SupportedDBType:
        return SupportedDBType.POSTGRESQL

    @property
    def default_port(self) -> int:
        return 5432

    def build_connection_uri(
        self,
        host: str,
        port: Optional[int],
        database: str,
        username: Optional[str],
        password: Optional[str],
        ssl_mode: str = "REQUIRED",
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        target_port = port or self.default_port
        user_part = ""
        if username:
            escaped_user = urllib.parse.quote_plus(username)
            if password:
                escaped_pass = urllib.parse.quote_plus(password)
                user_part = f"{escaped_user}:{escaped_pass}@"
            else:
                user_part = f"{escaped_user}@"

        query_params = []
        if ssl_mode.upper() == "REQUIRED":
            query_params.append("sslmode=require")
        elif ssl_mode.upper() == "DISABLED":
            query_params.append("sslmode=disable")

        query_str = f"?{'&'.join(query_params)}" if query_params else ""
        return f"postgresql://{user_part}{host}:{target_port}/{database}{query_str}"

    def get_capabilities(self, access_mode: str = "READ_ONLY") -> DatabaseCapabilities:
        is_rw = access_mode.upper() in ("READ_WRITE", "ADMIN")
        return DatabaseCapabilities(
            read=True,
            write=is_rw,
            transactions=True,
            schema_inspection=True
        )


class MySQLAdapter(DatabaseAdapter):
    @property
    def database_type(self) -> SupportedDBType:
        return SupportedDBType.MYSQL

    @property
    def default_port(self) -> int:
        return 3306

    def build_connection_uri(
        self,
        host: str,
        port: Optional[int],
        database: str,
        username: Optional[str],
        password: Optional[str],
        ssl_mode: str = "REQUIRED",
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        target_port = port or self.default_port
        user_part = ""
        if username:
            escaped_user = urllib.parse.quote_plus(username)
            if password:
                escaped_pass = urllib.parse.quote_plus(password)
                user_part = f"{escaped_user}:{escaped_pass}@"
            else:
                user_part = f"{escaped_user}@"

        query_params = []
        if ssl_mode.upper() == "REQUIRED":
            query_params.append("ssl_disabled=False")
        elif ssl_mode.upper() == "DISABLED":
            query_params.append("ssl_disabled=True")

        query_str = f"?{'&'.join(query_params)}" if query_params else ""
        return f"mysql+pymysql://{user_part}{host}:{target_port}/{database}{query_str}"

    def get_capabilities(self, access_mode: str = "READ_ONLY") -> DatabaseCapabilities:
        is_rw = access_mode.upper() in ("READ_WRITE", "ADMIN")
        return DatabaseCapabilities(
            read=True,
            write=is_rw,
            transactions=True,
            schema_inspection=True
        )


class SQLServerAdapter(DatabaseAdapter):
    @property
    def database_type(self) -> SupportedDBType:
        return SupportedDBType.SQLSERVER

    @property
    def default_port(self) -> int:
        return 1433

    def build_connection_uri(
        self,
        host: str,
        port: Optional[int],
        database: str,
        username: Optional[str],
        password: Optional[str],
        ssl_mode: str = "REQUIRED",
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        target_port = port or self.default_port
        user_part = ""
        if username:
            escaped_user = urllib.parse.quote_plus(username)
            if password:
                escaped_pass = urllib.parse.quote_plus(password)
                user_part = f"{escaped_user}:{escaped_pass}@"
            else:
                user_part = f"{escaped_user}@"

        query_params = ["driver=ODBC+Driver+17+for+SQL+Server"]
        if ssl_mode.upper() == "REQUIRED":
            query_params.append("Encrypt=yes")

        query_str = f"?{'&'.join(query_params)}"
        return f"mssql+pyodbc://{user_part}{host}:{target_port}/{database}{query_str}"

    def get_capabilities(self, access_mode: str = "READ_ONLY") -> DatabaseCapabilities:
        is_rw = access_mode.upper() in ("READ_WRITE", "ADMIN")
        return DatabaseCapabilities(
            read=True,
            write=is_rw,
            transactions=True,
            schema_inspection=True
        )


class SQLiteAdapter(DatabaseAdapter):
    @property
    def database_type(self) -> SupportedDBType:
        return SupportedDBType.SQLITE

    @property
    def default_port(self) -> Optional[int]:
        return None

    def build_connection_uri(
        self,
        host: str,
        port: Optional[int],
        database: str,
        username: Optional[str],
        password: Optional[str],
        ssl_mode: str = "DISABLED",
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        db_path = database or host
        if db_path.startswith("sqlite:///"):
            return db_path
        return f"sqlite:///{db_path}"

    def get_capabilities(self, access_mode: str = "READ_ONLY") -> DatabaseCapabilities:
        is_rw = access_mode.upper() in ("READ_WRITE", "ADMIN")
        return DatabaseCapabilities(
            read=True,
            write=is_rw,
            transactions=True,
            schema_inspection=True
        )


ADAPTER_REGISTRY: Dict[SupportedDBType, DatabaseAdapter] = {
    SupportedDBType.POSTGRESQL: PostgreSQLAdapter(),
    SupportedDBType.MYSQL: MySQLAdapter(),
    SupportedDBType.SQLSERVER: SQLServerAdapter(),
    SupportedDBType.SQLITE: SQLiteAdapter()
}


def get_adapter(database_type: str) -> DatabaseAdapter:
    """
    Retrieves concrete adapter for supported database type.
    Raises ValueError with code UNSUPPORTED_DATABASE_TYPE if unsupported.
    """
    if not database_type:
        raise ValueError("UNSUPPORTED_DATABASE_TYPE: Database type cannot be empty.")

    db_type_upper = database_type.upper().strip()
    # Map common aliases
    if db_type_upper in ("POSTGRES", "POSTGRESQL", "PG"):
        db_type_upper = "POSTGRESQL"
    elif db_type_upper in ("SQLITE3", "SQLITE"):
        db_type_upper = "SQLITE"
    elif db_type_upper in ("MSSQL", "SQLSERVER"):
        db_type_upper = "SQLSERVER"
    elif db_type_upper in ("MYSQL", "MARIADB"):
        db_type_upper = "MYSQL"

    try:
        enum_type = SupportedDBType(db_type_upper)
        return ADAPTER_REGISTRY[enum_type]
    except (ValueError, KeyError):
        raise ValueError(f"UNSUPPORTED_DATABASE_TYPE: Engine '{database_type}' is not supported by SageCommand Gateway.")
