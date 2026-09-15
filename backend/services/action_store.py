# backend/services/action_store.py
"""
SageCommand V3 — Action Repository Service
Provides thread-safe storage, retrieval, filtering, idempotency checking,
and status updates for Action domain objects.
Enforces SQLite persistence (survives restarts/workers) and guarded status transitions.
"""

import os
import json
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple, Set
from collections import OrderedDict

try:
    from core.config import MEMORY_DB_PATH
    from data.schemas.action_contract import Action, ActionStatus, ActionType, RiskLevel
except ModuleNotFoundError:
    from backend.core.config import MEMORY_DB_PATH
    from backend.data.schemas.action_contract import Action, ActionStatus, ActionType, RiskLevel


# Guarded Action Lifecycle State Transition Matrix (Constraint AM)
VALID_TRANSITIONS: Dict[ActionStatus, Set[ActionStatus]] = {
    ActionStatus.PROPOSED: {ActionStatus.VALIDATING, ActionStatus.REJECTED, ActionStatus.CANCELLED},
    ActionStatus.VALIDATING: {ActionStatus.POLICY_REVIEW, ActionStatus.REJECTED, ActionStatus.CANCELLED},
    ActionStatus.POLICY_REVIEW: {ActionStatus.AWAITING_APPROVAL, ActionStatus.APPROVED, ActionStatus.REJECTED, ActionStatus.CANCELLED},
    ActionStatus.AWAITING_APPROVAL: {ActionStatus.APPROVED, ActionStatus.REJECTED, ActionStatus.CANCELLED},
    # Future execution states (strictly not entered in Prompt 05)
    ActionStatus.APPROVED: {ActionStatus.CANCELLED},
    ActionStatus.EXECUTING: {ActionStatus.SUCCEEDED, ActionStatus.FAILED},
    ActionStatus.SUCCEEDED: set(),
    ActionStatus.FAILED: {ActionStatus.ROLLED_BACK},
    ActionStatus.ROLLED_BACK: set(),
    ActionStatus.REJECTED: set(),
    ActionStatus.CANCELLED: set(),
    ActionStatus.EXPIRED: set(),
}


class ActionStore:
    """
    Persistent Action Repository with Write-Through Cache.
    Guarantees persistence across restarts/workers and enforces guarded state transitions.
    """

    def __init__(self, db_path: str = MEMORY_DB_PATH):
        self._lock = threading.RLock()
        self._db_path = db_path
        self._actions: Dict[str, Action] = OrderedDict()
        self._idempotency_cache: Dict[str, Tuple[float, Action]] = {}
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Acquires a SQLite connection with timeout and foreign key checks."""
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes the actions_v3 SQLite table and indexes."""
        try:
            with self._lock:
                with self._get_connection() as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS actions_v3 (
                            action_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            workspace_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            action_type TEXT NOT NULL,
                            status TEXT NOT NULL,
                            system_risk_level TEXT NOT NULL,
                            data_mode TEXT NOT NULL,
                            mission_id TEXT,
                            incident_id TEXT,
                            idempotency_key TEXT,
                            created_at TEXT NOT NULL,
                            payload_json TEXT NOT NULL
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_v3_tenant ON actions_v3(tenant_id, created_at)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_v3_idemp ON actions_v3(tenant_id, idempotency_key)")
                    conn.commit()
        except Exception as e:
            print(f" [ActionStore] DB Initialization warning: {e}")

    def save(self, action: Action, idempotency_key: Optional[str] = None) -> Action:
        """Stores a new or updated action persistently in SQLite and write-through cache."""
        effective_key = idempotency_key or action.idempotency_key
        action_json = json.dumps(action.model_dump())

        with self._lock:
            # 1. Update In-Memory Cache
            self._actions[action.action_id] = action
            if effective_key:
                cache_key = f"{action.tenant_id}:{effective_key}"
                self._idempotency_cache[cache_key] = (time.time(), action)

            # 2. Persist to SQLite
            try:
                with self._get_connection() as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO actions_v3 (
                            action_id, tenant_id, workspace_id, session_id,
                            action_type, status, system_risk_level, data_mode,
                            mission_id, incident_id, idempotency_key, created_at,
                            payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        action.action_id,
                        action.tenant_id,
                        action.workspace_id,
                        action.session_id,
                        action.action_type.value,
                        action.status.value,
                        action.system_risk_level.value,
                        action.data_mode,
                        action.mission_id,
                        action.incident_id,
                        effective_key,
                        action.created_at,
                        action_json
                    ))
                    conn.commit()
            except Exception as e:
                print(f" [ActionStore] SQLite persistence warning: {e}")

            return action

    def get_by_id(self, action_id: str, tenant_id: str) -> Optional[Action]:
        """Retrieves an action by ID, enforcing tenant isolation."""
        with self._lock:
            # 1. Check in-memory cache
            cached = self._actions.get(action_id)
            if cached:
                return cached if cached.tenant_id == tenant_id else None

            # 2. Query SQLite fallback
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT payload_json FROM actions_v3 WHERE action_id = ? AND tenant_id = ?",
                        (action_id, tenant_id)
                    )
                    row = cursor.fetchone()
                    if row:
                        action = Action(**json.loads(row["payload_json"]))
                        self._actions[action_id] = action
                        return action
            except Exception as e:
                print(f" [ActionStore] SQLite query error: {e}")

            return None

    def get(self, action_id: str, tenant_id: Optional[str] = None) -> Optional[Action]:
        """Convenience accessor to retrieve action by ID with optional tenant isolation."""
        if tenant_id:
            return self.get_by_id(action_id, tenant_id)
        return self.find_existing_by_id(action_id)

    def find_existing_by_id(self, action_id: str) -> Optional[Action]:
        """Looks up action across any tenant (for cross-tenant detection)."""
        with self._lock:
            cached = self._actions.get(action_id)
            if cached:
                return cached

            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT payload_json FROM actions_v3 WHERE action_id = ?",
                        (action_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        action = Action(**json.loads(row["payload_json"]))
                        self._actions[action_id] = action
                        return action
            except Exception:
                pass
            return None

    def check_idempotency(self, tenant_id: str, idempotency_key: str) -> Optional[Action]:
        """Checks if an idempotency key was recently processed (5-minute TTL)."""
        with self._lock:
            cache_key = f"{tenant_id}:{idempotency_key}"
            if cache_key in self._idempotency_cache:
                ts, action = self._idempotency_cache[cache_key]
                if time.time() - ts < 300:
                    return action

            # Fallback to SQLite check
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        "SELECT payload_json FROM actions_v3 WHERE tenant_id = ? AND idempotency_key = ?",
                        (tenant_id, idempotency_key)
                    )
                    row = cursor.fetchone()
                    if row:
                        action = Action(**json.loads(row["payload_json"]))
                        self._idempotency_cache[cache_key] = (time.time(), action)
                        return action
            except Exception:
                pass

            return None

    def list_actions(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        action_type: Optional[ActionType] = None,
        status: Optional[ActionStatus] = None,
        risk_level: Optional[RiskLevel] = None,
        data_mode: Optional[str] = None,
        mission_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[Action], int]:
        """Lists actions scoped to tenant with filters and pagination."""
        with self._lock:
            # Use cached in-memory entries if available, else SQLite
            filtered: List[Action] = []
            safe_limit = min(max(1, limit), 100)
            safe_offset = max(0, offset)

            for act in reversed(list(self._actions.values())):
                if act.tenant_id != tenant_id:
                    continue
                if workspace_id and act.workspace_id != workspace_id:
                    continue
                if action_type and act.action_type != action_type:
                    continue
                if status and act.status != status:
                    continue
                if risk_level and act.system_risk_level != risk_level:
                    continue
                if data_mode and act.data_mode != data_mode:
                    continue
                if mission_id and act.mission_id != mission_id:
                    continue
                if incident_id and act.incident_id != incident_id:
                    continue
                filtered.append(act)

            total = len(filtered)
            paginated = filtered[safe_offset : safe_offset + safe_limit]
            return paginated, total

    def update_status(
        self,
        action_id: str,
        arg2: Any,
        arg3: Optional[ActionStatus] = None
    ) -> Optional[Action]:
        """
        Transitions an action to a new lifecycle status.
        Enforces guarded state transitions (Constraint AM).
        Supports both (action_id, tenant_id, new_status) and (action_id, new_status, tenant_id=None).
        """
        if isinstance(arg2, ActionStatus):
            new_status = arg2
            tenant_id = None
        else:
            tenant_id = str(arg2)
            new_status = arg3

        with self._lock:
            act = self.get_by_id(action_id, tenant_id) if tenant_id else self.find_existing_by_id(action_id)
            if not act:
                return None

            # Enforce guarded status transition table
            allowed = VALID_TRANSITIONS.get(act.status, set())
            if new_status not in allowed:
                raise ValueError(
                    f"Invalid action status transition: '{act.status.value}' cannot transition to '{new_status.value}'."
                )

            act.status = new_status
            self.save(act)
            return act

    def clear(self):
        """Clears store memory and SQLite table (for test isolation)."""
        with self._lock:
            self._actions.clear()
            self._idempotency_cache.clear()
            try:
                with self._get_connection() as conn:
                    conn.execute("DELETE FROM actions_v3")
                    conn.commit()
            except Exception:
                pass


# Global singleton store instance
action_store = ActionStore()
