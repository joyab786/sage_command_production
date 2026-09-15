# backend/data/database_context.py
"""
SageCommand V3 — Database Context & Domain Models
Defines session-scoped database contexts, access modes, connection status,
workspace, and tenant domain models. Zero plain-text credentials stored.
"""

import uuid
import time
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class AccessMode(str, Enum):
    """Database execution access permissions."""
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"
    ADMIN = "ADMIN"
    SIMULATION = "SIMULATION"

class DataMode(str, Enum):
    """Data source provenance operational mode."""
    REAL = "REAL"
    SIMULATION = "SIMULATION"
    HYBRID = "HYBRID"

class ConnectionStatus(str, Enum):
    """Lifecycle state of a database connection."""
    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    HEALTHY = "HEALTHY"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    DISCONNECTED = "DISCONNECTED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    TIMEOUT = "TIMEOUT"
    EXPIRED = "EXPIRED"
    UNHEALTHY = "UNHEALTHY"
    REVOKED = "REVOKED"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"

class DatabaseContext(BaseModel):
    """
    Session-Scoped Database Context Container.
    Explicitly ties a database connection to Tenant -> Workspace -> Session hierarchy.
    """
    connection_id: str = Field(default_factory=lambda: f"conn_{uuid.uuid4().hex[:8]}")
    tenant_id: str = Field(default="tenant_default")
    workspace_id: str = Field(default="workspace_default")
    session_id: str = Field(default="session_default")
    plant_id: Optional[str] = Field(default="plant_mumbai")
    database_type: str = Field(default="sqlite")
    database_name: str = Field(default="dynamic_datacore.sqlite")
    access_mode: AccessMode = Field(default=AccessMode.READ_ONLY)
    data_mode: DataMode = Field(default=DataMode.REAL)
    status: ConnectionStatus = Field(default=ConnectionStatus.CONNECTED)
    created_at: float = Field(default_factory=time.time)
    last_used_at: float = Field(default_factory=time.time)
    safe_representation: str = Field(default="sqlite:///dynamic_datacore.sqlite")

    def touch(self):
        """Updates last_used_at timestamp on active connection query."""
        self.last_used_at = time.time()

    def get_scoped_key(self) -> str:
        """Returns the composite lookup key for connection isolation."""
        return f"{self.tenant_id}:{self.workspace_id}:{self.session_id}:{self.connection_id}"

class Workspace(BaseModel):
    """Operational plant workspace context."""
    workspace_id: str = Field(default="workspace_default")
    tenant_id: str = Field(default="tenant_default")
    name: str = Field(default="Mumbai Industrial Plant")
    plant_id: str = Field(default="plant_mumbai")
    active_connection_ids: List[str] = Field(default_factory=list)

class Tenant(BaseModel):
    """Multi-tenant organization boundary."""
    tenant_id: str = Field(default="tenant_default")
    name: str = Field(default="Default Enterprise Organization")
    workspace_ids: List[str] = Field(default_factory=lambda: ["workspace_default"])
