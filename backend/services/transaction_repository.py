# backend/services/transaction_repository.py
"""
SageCommand V3 — Transaction Repository Architecture
Provides abstract and SQLite persistent storage for Transactions and Transaction Plans.
Enforces multi-tenant isolation, thread safety, and deterministic idempotency retrieval.
"""

import abc
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

try:
    from core.config import SAGE_TRANSACTIONS_DB_PATH, SAGE_TRANSACTION_MAX_PAYLOAD_SIZE
    from governance.audit import log_security_event
    from governance.redaction import sanitize_payload
    from data.schemas.transaction_contract import (
        Transaction,
        TransactionPlan,
        TransactionStatus,
        TransactionType,
        RollbackCapability
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_TRANSACTIONS_DB_PATH, SAGE_TRANSACTION_MAX_PAYLOAD_SIZE
    from backend.governance.audit import log_security_event
    from backend.governance.redaction import sanitize_payload
    from backend.data.schemas.transaction_contract import (
        Transaction,
        TransactionPlan,
        TransactionStatus,
        TransactionType,
        RollbackCapability
    )


class TransactionRepository(abc.ABC):
    """Abstract interface defining transaction persistence operations."""

    @abc.abstractmethod
    def save(self, transaction: Transaction) -> Transaction:
        """Persists or updates a transaction."""
        pass

    @abc.abstractmethod
    def get_by_id(self, transaction_id: str, tenant_id: str) -> Optional[Transaction]:
        """Retrieves a transaction strictly bounded by tenant isolation."""
        pass

    @abc.abstractmethod
    def get_by_idempotency_key(self, idempotency_key: str, tenant_id: str) -> Optional[Transaction]:
        """Retrieves an existing transaction by idempotency key within tenant scope."""
        pass

    @abc.abstractmethod
    def list_transactions(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Transaction]:
        """Queries transactions matching tenant and optional filter criteria."""
        pass

    @abc.abstractmethod
    def update_status(
        self,
        transaction_id: str,
        tenant_id: str,
        status: TransactionStatus,
        failure_reason: Optional[str] = None,
        failure_code: Optional[str] = None
    ) -> bool:
        """Updates the status and failure details of a transaction."""
        pass


class SQLiteTransactionRepository(TransactionRepository):
    """
    Thread-safe SQLite implementation of TransactionRepository.
    Stores transactions in the `transactions_v3` table.
    """

    def __init__(self, db_path: str = SAGE_TRANSACTIONS_DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._is_memory = (db_path == ":memory:")
        self._shared_conn: Optional[sqlite3.Connection] = None
        if self._is_memory:
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory and self._shared_conn:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS transactions_v3 (
                        transaction_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        plant_id TEXT,
                        action_id TEXT NOT NULL,
                        action_version TEXT NOT NULL,
                        status TEXT NOT NULL,
                        transaction_type TEXT NOT NULL,
                        data_mode TEXT NOT NULL,
                        access_mode TEXT NOT NULL,
                        idempotency_key TEXT,
                        transaction_plan_hash TEXT NOT NULL,
                        plan_json TEXT NOT NULL,
                        failure_reason TEXT,
                        failure_code TEXT,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_tenant_id ON transactions_v3(tenant_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_action_id ON transactions_v3(action_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_idempotency ON transactions_v3(tenant_id, idempotency_key);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions_v3(status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_created_at ON transactions_v3(created_at);")
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

    def save(self, transaction: Transaction) -> Transaction:
        with self._lock:
            conn = self._get_connection()
            try:
                plan_json = transaction.plan.model_dump_json()
                if len(plan_json.encode("utf-8")) > SAGE_TRANSACTION_MAX_PAYLOAD_SIZE:
                    raise ValueError(f"Transaction plan payload exceeds max limit {SAGE_TRANSACTION_MAX_PAYLOAD_SIZE}")

                now_iso = datetime.now(timezone.utc).isoformat()
                transaction.updated_at = now_iso

                conn.execute("""
                    INSERT INTO transactions_v3 (
                        transaction_id, tenant_id, workspace_id, session_id, plant_id,
                        action_id, action_version, status, transaction_type, data_mode,
                        access_mode, idempotency_key, transaction_plan_hash, plan_json,
                        failure_reason, failure_code, created_at, expires_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(transaction_id) DO UPDATE SET
                        status = excluded.status,
                        plan_json = excluded.plan_json,
                        failure_reason = excluded.failure_reason,
                        failure_code = excluded.failure_code,
                        updated_at = excluded.updated_at;
                """, (
                    transaction.transaction_id,
                    transaction.tenant_id,
                    transaction.workspace_id,
                    transaction.session_id,
                    transaction.plant_id,
                    transaction.action_id,
                    transaction.action_version,
                    transaction.status.value if hasattr(transaction.status, "value") else str(transaction.status),
                    transaction.transaction_type.value if hasattr(transaction.transaction_type, "value") else str(transaction.transaction_type),
                    transaction.data_mode,
                    transaction.access_mode,
                    transaction.idempotency_key,
                    transaction.plan.transaction_plan_hash or transaction.plan.compute_hash(),
                    plan_json,
                    transaction.failure_reason,
                    transaction.failure_code,
                    transaction.created_at,
                    transaction.expires_at,
                    transaction.updated_at
                ))
                conn.commit()
                return transaction
            finally:
                if not self._is_memory:
                    conn.close()

    def get_by_id(self, transaction_id: str, tenant_id: str) -> Optional[Transaction]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("""
                    SELECT transaction_id, tenant_id, workspace_id, session_id, plant_id,
                           action_id, action_version, status, transaction_type, data_mode,
                           access_mode, idempotency_key, transaction_plan_hash, plan_json,
                           failure_reason, failure_code, created_at, expires_at, updated_at
                    FROM transactions_v3
                    WHERE transaction_id = ? AND tenant_id = ?;
                """, (transaction_id, tenant_id))
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_transaction(row)
            finally:
                if not self._is_memory:
                    conn.close()

    def get_by_idempotency_key(self, idempotency_key: str, tenant_id: str) -> Optional[Transaction]:
        if not idempotency_key:
            return None
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("""
                    SELECT transaction_id, tenant_id, workspace_id, session_id, plant_id,
                           action_id, action_version, status, transaction_type, data_mode,
                           access_mode, idempotency_key, transaction_plan_hash, plan_json,
                           failure_reason, failure_code, created_at, expires_at, updated_at
                    FROM transactions_v3
                    WHERE idempotency_key = ? AND tenant_id = ?;
                """, (idempotency_key, tenant_id))
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_transaction(row)
            finally:
                if not self._is_memory:
                    conn.close()

    def list_transactions(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Transaction]:
        with self._lock:
            conn = self._get_connection()
            try:
                query = """
                    SELECT transaction_id, tenant_id, workspace_id, session_id, plant_id,
                           action_id, action_version, status, transaction_type, data_mode,
                           access_mode, idempotency_key, transaction_plan_hash, plan_json,
                           failure_reason, failure_code, created_at, expires_at, updated_at
                    FROM transactions_v3
                    WHERE tenant_id = ?
                """
                params: List[Any] = [tenant_id]

                if workspace_id:
                    query += " AND workspace_id = ?"
                    params.append(workspace_id)
                if status:
                    query += " AND status = ?"
                    params.append(status)

                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
                params.extend([max(1, min(limit, 200)), max(0, offset)])

                cursor = conn.execute(query, params)
                return [self._row_to_transaction(row) for row in cursor.fetchall()]
            finally:
                if not self._is_memory:
                    conn.close()

    def update_status(
        self,
        transaction_id: str,
        tenant_id: str,
        status: TransactionStatus,
        failure_reason: Optional[str] = None,
        failure_code: Optional[str] = None
    ) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute("""
                    UPDATE transactions_v3
                    SET status = ?, failure_reason = ?, failure_code = ?, updated_at = ?
                    WHERE transaction_id = ? AND tenant_id = ?;
                """, (
                    status.value if hasattr(status, "value") else str(status),
                    failure_reason,
                    failure_code,
                    now_iso,
                    transaction_id,
                    tenant_id
                ))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    def clear(self) -> None:
        """Clears all records from transactions_v3 table. Intended for testing."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM transactions_v3;")
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

    def _row_to_transaction(self, row: tuple) -> Transaction:
        (
            tx_id, tenant_id, workspace_id, session_id, plant_id,
            action_id, action_version, status, tx_type, data_mode,
            access_mode, idempotency_key, plan_hash, plan_json,
            failure_reason, failure_code, created_at, expires_at, updated_at
        ) = row

        plan = TransactionPlan.model_validate_json(plan_json)

        return Transaction(
            transaction_id=tx_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            plant_id=plant_id,
            action_id=action_id,
            action_version=action_version,
            status=TransactionStatus(status),
            transaction_type=TransactionType(tx_type) if tx_type in TransactionType.__members__ else TransactionType.DATABASE,
            data_mode=data_mode,
            access_mode=access_mode,
            plan=plan,
            failure_reason=failure_reason,
            failure_code=failure_code,
            idempotency_key=idempotency_key,
            created_at=created_at,
            expires_at=expires_at,
            updated_at=updated_at,
            rollback_supported=plan.rollback_plan.capability if plan.rollback_plan else RollbackCapability.UNKNOWN
        )


# Canonical singleton repository instance
transaction_repository = SQLiteTransactionRepository()
