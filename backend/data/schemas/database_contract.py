# backend/data/schemas/database_contract.py
"""
SageCommand V3 — Database Connection Gateway Canonical API Contract
Defines centralized Enums, Resource representations, Request/Response payloads,
and normalized Error models conforming to Prompt 04 Canonical API Contract.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# =====================================================================
# 1. CENTRALIZED ENUMS
# =====================================================================

class DatabaseType(str, Enum):
    """Officially supported database adapter engines."""
    POSTGRESQL = "POSTGRESQL"
    MYSQL = "MYSQL"
    SQLSERVER = "SQLSERVER"
    SQLITE = "SQLITE"


class ConnectionStatus(str, Enum):
    """Lifecycle status of a database connection."""
    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    HEALTHY = "HEALTHY"
    IDLE = "IDLE"

    CONNECTION_FAILED = "CONNECTION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    TIMEOUT = "TIMEOUT"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    UNHEALTHY = "UNHEALTHY"
    EXPIRED = "EXPIRED"
    DISCONNECTED = "DISCONNECTED"
    REVOKED = "REVOKED"


class AccessMode(str, Enum):
    """Database execution and permission boundaries."""
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"
    ADMIN = "ADMIN"
    SIMULATION = "SIMULATION"


class DataMode(str, Enum):
    """Data source operational provenance."""
    REAL = "REAL"
    SIMULATION = "SIMULATION"
    HYBRID = "HYBRID"


class GatewayErrorCode(str, Enum):
    """Canonical error codes for Database Connection Gateway."""
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"

    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_DATABASE_TYPE = "INVALID_DATABASE_TYPE"
    INVALID_DATABASE_CONFIGURATION = "INVALID_DATABASE_CONFIGURATION"

    DATABASE_POLICY_BLOCKED = "DATABASE_POLICY_BLOCKED"
    DATABASE_HOST_BLOCKED = "DATABASE_HOST_BLOCKED"
    DATABASE_PORT_BLOCKED = "DATABASE_PORT_BLOCKED"
    DATABASE_NETWORK_BLOCKED = "DATABASE_NETWORK_BLOCKED"

    DATABASE_TLS_REQUIRED = "DATABASE_TLS_REQUIRED"
    DATABASE_TLS_FAILED = "DATABASE_TLS_FAILED"

    DATABASE_CONNECTION_FAILED = "DATABASE_CONNECTION_FAILED"
    DATABASE_AUTH_FAILED = "DATABASE_AUTH_FAILED"
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"
    DATABASE_UNREACHABLE = "DATABASE_UNREACHABLE"
    DATABASE_NOT_FOUND = "DATABASE_NOT_FOUND"
    DATABASE_PERMISSION_DENIED = "DATABASE_PERMISSION_DENIED"

    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    CONNECTION_REVOKED = "CONNECTION_REVOKED"
    CONNECTION_EXPIRED = "CONNECTION_EXPIRED"
    CONNECTION_NOT_ACCESSIBLE = "CONNECTION_NOT_ACCESSIBLE"

    SCHEMA_DISCOVERY_FAILED = "SCHEMA_DISCOVERY_FAILED"
    SAMPLE_DATA_BLOCKED = "SAMPLE_DATA_BLOCKED"
    SAMPLE_DATA_TOO_LARGE = "SAMPLE_DATA_TOO_LARGE"

    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


# =====================================================================
# 2. CORE RESOURCE REPRESENTATIONS
# =====================================================================

class DatabaseConnectionCapabilities(BaseModel):
    """Capability boundaries of an established connection."""
    read: bool = Field(default=True, description="Permit read operations")
    write: bool = Field(default=False, description="Permit write operations (governed by Action API)")
    transactions: bool = Field(default=False, description="Transaction management support")
    schema_inspection: bool = Field(default=True, description="Permit bounded schema inspection")


class DatabaseConnection(BaseModel):
    """
    Canonical safe representation of a Database Connection resource.
    Guarantees zero leakage of credentials, passwords, or raw connection strings.
    """
    model_config = ConfigDict(extra="ignore")

    connection_id: str = Field(..., description="Unique connection handle (e.g. conn_01JABC)")
    tenant_id: str = Field(..., description="Scoped tenant identifier")
    workspace_id: str = Field(..., description="Scoped workspace identifier")
    session_id: str = Field(..., description="Scoped user session identifier")
    plant_id: str = Field(default="plant_001", description="Industrial plant identifier")

    database_type: DatabaseType = Field(..., description="Engine type (POSTGRESQL, MYSQL, SQLSERVER, SQLITE)")
    database_name: str = Field(..., description="Target database name")

    status: ConnectionStatus = Field(default=ConnectionStatus.CONNECTED, description="Current connection status")
    access_mode: AccessMode = Field(default=AccessMode.READ_ONLY, description="Access permissions mode")
    data_mode: DataMode = Field(default=DataMode.REAL, description="Real vs Simulation provenance")

    capabilities: DatabaseConnectionCapabilities = Field(
        default_factory=DatabaseConnectionCapabilities,
        description="Declared capability matrix"
    )

    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    last_used_at: str = Field(..., description="ISO 8601 last activity timestamp")


class DatabaseConnectionListItem(BaseModel):
    """Lightweight summary representation for connection listing."""
    connection_id: str
    database_type: DatabaseType
    status: ConnectionStatus
    access_mode: AccessMode
    data_mode: DataMode


# =====================================================================
# 3. ERROR CONTRACT
# =====================================================================

class ErrorDetail(BaseModel):
    code: GatewayErrorCode
    message: str


class ErrorResponse(BaseModel):
    """Canonical error response envelope."""
    success: bool = Field(default=False)
    request_id: str = Field(..., description="Correlation request identifier")
    error: ErrorDetail


# =====================================================================
# 4. REQUEST & RESPONSE PAYLOADS
# =====================================================================

class SSLConfig(BaseModel):
    """SSL/TLS negotiation policy."""
    mode: str = Field(default="REQUIRED", description="TLS requirement: REQUIRED, PREFERRED, DISABLED")


class CreateConnectionRequest(BaseModel):
    """Request payload to establish and register a new database connection."""
    database_type: DatabaseType = Field(..., description="Engine type")
    host: Optional[str] = Field(default=None, description="Destination host or IP")
    port: Optional[int] = Field(default=None, description="Destination database port")
    database: Optional[str] = Field(default=None, description="Database name")
    username: Optional[str] = Field(default=None, description="Database username")
    password: Optional[str] = Field(default=None, exclude=True, description="Database secret (never logged or returned)")
    ssl: Optional[SSLConfig] = Field(default_factory=SSLConfig, description="TLS configuration")

    access_mode: AccessMode = Field(default=AccessMode.READ_ONLY, description="Access permissions")
    data_mode: DataMode = Field(default=DataMode.REAL, description="Data provenance")
    plant_id: Optional[str] = Field(default="plant_001", description="Associated plant identifier")
    connection_string: Optional[str] = Field(default=None, description="Optional raw URI (validated safely)")


class CreateConnectionResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str = Field(..., description="Correlation request ID")
    connection: DatabaseConnection


class TestConnectionRequest(BaseModel):
    """Payload to test transient reachability without persistent registration."""
    database_type: DatabaseType = Field(..., description="Engine type")
    host: Optional[str] = Field(default=None, description="Destination host or IP")
    port: Optional[int] = Field(default=None, description="Destination port")
    database: Optional[str] = Field(default=None, description="Database name")
    username: Optional[str] = Field(default=None, description="Database username")
    password: Optional[str] = Field(default=None, exclude=True, description="Database secret")
    ssl: Optional[SSLConfig] = Field(default_factory=SSLConfig, description="TLS configuration")
    connection_string: Optional[str] = Field(default=None, description="Optional raw URI")


class TestConnectionResult(BaseModel):
    reachable: bool = Field(..., description="Whether destination host is reachable")
    authenticated: bool = Field(..., description="Whether authentication succeeded")
    database_type: DatabaseType = Field(..., description="Target database engine")
    latency_ms: float = Field(..., description="Network round-trip latency in milliseconds")


class TestConnectionResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    result: TestConnectionResult


class GetConnectionResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    connection: DatabaseConnection


class ListConnectionsResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    connections: List[DatabaseConnectionListItem]
    total: int


class HealthCheckInfo(BaseModel):
    status: ConnectionStatus
    latency_ms: float
    checked_at: str


class HealthCheckResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    health: HealthCheckInfo


class ColumnMetadata(BaseModel):
    name: str
    type: str
    nullable: bool = True


class TableMetadata(BaseModel):
    name: str
    columns: List[ColumnMetadata]


class SchemaMetadata(BaseModel):
    tables: List[TableMetadata]


class SchemaDiscoveryResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    schema_data: SchemaMetadata = Field(..., alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class SampleDataRequest(BaseModel):
    table: str = Field(..., description="Table name to sample")
    limit: int = Field(default=10, ge=1, le=10, description="Max sample rows (1-10)")
    columns: Optional[List[str]] = Field(default=None, description="Subset of columns to sample")


class SampleDataInfo(BaseModel):
    table: str
    columns: List[str]
    rows: List[Dict[str, Any]]


class SampleDataResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    sample: SampleDataInfo


class DisconnectConnectionInfo(BaseModel):
    connection_id: str
    status: ConnectionStatus


class DisconnectResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    connection: DisconnectConnectionInfo


class RevokeResponse(BaseModel):
    success: bool = Field(default=True)
    request_id: str
    connection: DisconnectConnectionInfo
