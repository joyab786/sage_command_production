# backend/services/connection_registry.py
"""
SageCommand V3 — Connection Registry Service
Thread-safe server-side registry mapping database connection metadata by
Tenant -> Workspace -> Session hierarchy. Zero raw passwords or credentials stored.
"""

import threading
from typing import Dict, List, Optional
try:
    from data.database_context import DatabaseContext, ConnectionStatus
except ModuleNotFoundError:
    from backend.data.database_context import DatabaseContext, ConnectionStatus

class ConnectionRegistry:
    """Thread-safe server-side registry storing active DatabaseContext metadata."""

    def __init__(self):
        self._lock = threading.RLock()
        # Map: scoped_key -> DatabaseContext
        self._registry: Dict[str, DatabaseContext] = {}

    def _make_key(self, tenant_id: str, workspace_id: str, session_id: str, connection_id: str) -> str:
        return f"{tenant_id}:{workspace_id}:{session_id}:{connection_id}"

    def register(self, context: DatabaseContext) -> None:
        """Registers a new DatabaseContext under its scoped composite key."""
        with self._lock:
            key = context.get_scoped_key()
            self._registry[key] = context

    def lookup(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str
    ) -> Optional[DatabaseContext]:
        """Look up a DatabaseContext by explicit tenant, workspace, session, and connection IDs."""
        with self._lock:
            key = self._make_key(tenant_id, workspace_id, session_id, connection_id)
            ctx = self._registry.get(key)
            if ctx:
                ctx.touch()
            return ctx

    def list_for_session(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str
    ) -> List[DatabaseContext]:
        """Lists all registered active connections belonging to a specific session."""
        prefix = f"{tenant_id}:{workspace_id}:{session_id}:"
        with self._lock:
            return [ctx for k, ctx in self._registry.items() if k.startswith(prefix)]

    def list_for_tenant(self, tenant_id: str) -> List[DatabaseContext]:
        """Lists all registered active connections belonging to a specific tenant."""
        with self._lock:
            return [ctx for ctx in self._registry.values() if ctx.tenant_id == tenant_id]

    @property
    def contexts(self) -> Dict[str, DatabaseContext]:
        """Thread-safe snapshot dictionary of all registered contexts."""
        with self._lock:
            return dict(self._registry)

    def update_status(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str,
        status: ConnectionStatus
    ) -> bool:
        """Updates the status of a registered connection."""
        with self._lock:
            ctx = self.lookup(tenant_id, workspace_id, session_id, connection_id)
            if ctx:
                ctx.status = status
                return True
            return False

    def remove(
        self,
        tenant_id: str,
        workspace_id: str,
        session_id: str,
        connection_id: str
    ) -> Optional[DatabaseContext]:
        """Removes and returns a registered connection context from the registry."""
        with self._lock:
            key = self._make_key(tenant_id, workspace_id, session_id, connection_id)
            return self._registry.pop(key, None)

    def clear_session(self, tenant_id: str, workspace_id: str, session_id: str) -> int:
        """Removes all connection contexts associated with a session."""
        prefix = f"{tenant_id}:{workspace_id}:{session_id}:"
        with self._lock:
            keys_to_remove = [k for k in self._registry.keys() if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._registry[k]
            return len(keys_to_remove)

    def clear(self) -> None:
        """Clears all registered connections."""
        with self._lock:
            self._registry.clear()


# Singleton global registry instance
connection_registry = ConnectionRegistry()

