import sqlite3
import json
from typing import List, Optional
from datetime import datetime, UTC

from core.config import SAGE_EVENT_DELIVERY_DB_PATH
from data.schemas.event_delivery_contract import (
    Subscription,
    EventDelivery,
    DeadLetter,
    DeliveryStatus
)

class EventDeliveryRepository:
    def __init__(self, db_path: str = SAGE_EVENT_DELIVERY_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enforce foreign keys and reliable WAL mode
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            # Subscriptions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    subscriber_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    plant_id TEXT,
                    category TEXT,
                    event_type TEXT,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(subscriber_id, tenant_id, category, event_type, workspace_id, plant_id, source)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sub_tenant ON subscriptions(tenant_id);")

            # Deliveries (delivery state for idempotency and retries)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    event_fingerprint TEXT NOT NULL,
                    subscription_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    last_error TEXT,
                    next_retry_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(event_fingerprint, subscription_id),
                    FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_del_tenant ON deliveries(tenant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_del_status ON deliveries(status);")

            # Dead Letters (unrecoverable events)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letters (
                    dead_letter_id TEXT PRIMARY KEY,
                    delivery_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    subscription_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    failure_reason TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(delivery_id),
                    FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dl_tenant ON dead_letters(tenant_id);")
            conn.commit()

    # --- Subscriptions ---
    def register_subscription(self, sub: Subscription) -> Subscription:
        with self._get_conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO subscriptions (
                        subscription_id, subscriber_id, tenant_id, workspace_id, plant_id,
                        category, event_type, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sub.subscription_id, sub.subscriber_id, sub.tenant_id, sub.workspace_id, sub.plant_id,
                    sub.category, sub.event_type, sub.source, datetime.now(UTC).isoformat().replace("+00:00", "Z")
                ))
                conn.commit()
                return sub
            except sqlite3.IntegrityError:
                # If a duplicate subscription exists for this tenant/subscriber matching criteria, we return the existing one.
                row = conn.execute("""
                    SELECT * FROM subscriptions 
                    WHERE subscriber_id=? AND tenant_id=? 
                      AND IFNULL(category,'')=IFNULL(?,'') 
                      AND IFNULL(event_type,'')=IFNULL(?,'')
                      AND IFNULL(workspace_id,'')=IFNULL(?,'')
                      AND IFNULL(plant_id,'')=IFNULL(?,'')
                      AND IFNULL(source,'')=IFNULL(?,'')
                """, (sub.subscriber_id, sub.tenant_id, sub.category, sub.event_type, sub.workspace_id, sub.plant_id, sub.source)).fetchone()
                if row:
                    return Subscription(**dict(row))
                raise

    def get_subscriptions_for_tenant(self, tenant_id: str) -> List[Subscription]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM subscriptions WHERE tenant_id = ?", (tenant_id,)).fetchall()
            return [Subscription(**dict(row)) for row in rows]

    def remove_subscription(self, subscription_id: str, tenant_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM subscriptions WHERE subscription_id = ? AND tenant_id = ?", (subscription_id, tenant_id))
            conn.commit()
            return cur.rowcount > 0

    # --- Deliveries ---
    def record_delivery_attempt(self, delivery: EventDelivery) -> EventDelivery:
        """Upserts a delivery record (handles idempotency tracking)."""
        delivery.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO deliveries (
                    delivery_id, event_id, event_fingerprint, subscription_id, tenant_id,
                    status, attempts, max_attempts, last_error, next_retry_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_fingerprint, subscription_id) DO UPDATE SET
                    status=excluded.status,
                    attempts=excluded.attempts,
                    last_error=excluded.last_error,
                    next_retry_at=excluded.next_retry_at,
                    updated_at=excluded.updated_at
            """, (
                delivery.delivery_id, delivery.event_id, delivery.event_fingerprint, delivery.subscription_id,
                delivery.tenant_id, delivery.status.value, delivery.attempts, delivery.max_attempts,
                delivery.last_error, delivery.next_retry_at, delivery.created_at, delivery.updated_at
            ))
            conn.commit()
            return delivery

    def get_delivery(self, delivery_id: str, tenant_id: str) -> Optional[EventDelivery]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM deliveries WHERE delivery_id = ? AND tenant_id = ?", (delivery_id, tenant_id)).fetchone()
            if row:
                return EventDelivery(**dict(row))
            return None

    def list_deliveries(self, tenant_id: str, limit: int = 100) -> List[EventDelivery]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM deliveries WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?", (tenant_id, limit)).fetchall()
            return [EventDelivery(**dict(row)) for row in rows]

    # --- Dead Letters ---
    def record_dead_letter(self, dead_letter: DeadLetter) -> DeadLetter:
        with self._get_conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO dead_letters (
                        dead_letter_id, delivery_id, event_id, subscription_id, tenant_id,
                        failure_reason, attempt_count, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dead_letter.dead_letter_id, dead_letter.delivery_id, dead_letter.event_id, dead_letter.subscription_id,
                    dead_letter.tenant_id, dead_letter.failure_reason, dead_letter.attempt_count, dead_letter.recorded_at
                ))
                conn.commit()
            except sqlite3.IntegrityError:
                pass # Already dead lettered
            return dead_letter

    def list_dead_letters(self, tenant_id: str, limit: int = 100) -> List[DeadLetter]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM dead_letters WHERE tenant_id = ? ORDER BY recorded_at DESC LIMIT ?", (tenant_id, limit)).fetchall()
            return [DeadLetter(**dict(row)) for row in rows]
