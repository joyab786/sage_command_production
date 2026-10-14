import sqlite3
import json
import uuid
from typing import List, Optional
from datetime import datetime, UTC, timedelta

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
        conn = sqlite3.connect(self.db_path, timeout=10.0)
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

            # Deliveries (delivery state for idempotency, retries, and atomic claims)
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
                    claim_token TEXT,
                    lease_expires_at TEXT,
                    idempotency_key TEXT,
                    UNIQUE(event_fingerprint, subscription_id),
                    FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                )
            """)
            # Backwards compatibility migrations
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(deliveries);").fetchall()]
            if "claim_token" not in cols:
                conn.execute("ALTER TABLE deliveries ADD COLUMN claim_token TEXT;")
            if "lease_expires_at" not in cols:
                conn.execute("ALTER TABLE deliveries ADD COLUMN lease_expires_at TEXT;")
            if "idempotency_key" not in cols:
                conn.execute("ALTER TABLE deliveries ADD COLUMN idempotency_key TEXT;")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_del_tenant ON deliveries(tenant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_del_status ON deliveries(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_del_lease ON deliveries(status, lease_expires_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_del_claim ON deliveries(claim_token);")

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

    # --- Deliveries & Atomic Claims ---
    def record_delivery_attempt(self, delivery: EventDelivery) -> EventDelivery:
        """Upserts a delivery record (handles idempotency tracking, active leases, and prevents resetting success)."""
        delivery.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        if not delivery.idempotency_key:
            delivery.idempotency_key = delivery.delivery_id

        with self._get_conn() as conn:
            # Check existing record
            existing = conn.execute(
                "SELECT * FROM deliveries WHERE event_fingerprint = ? AND subscription_id = ?",
                (delivery.event_fingerprint, delivery.subscription_id)
            ).fetchone()
            if existing:
                if existing["tenant_id"] != delivery.tenant_id:
                    raise ValueError(f"Cross-tenant delivery update rejected: existing tenant '{existing['tenant_id']}' != incoming tenant '{delivery.tenant_id}'")
                if existing["status"].upper() == DeliveryStatus.SUCCESS.value:
                    # Never reset or downgrade a successful delivery record
                    delivery.status = DeliveryStatus.SUCCESS
                    delivery.attempts = existing["attempts"]
                    delivery.last_error = existing["last_error"]
                    delivery.next_retry_at = existing["next_retry_at"]
                    delivery.updated_at = existing["updated_at"]
                    delivery.claim_token = existing["claim_token"]
                    delivery.lease_expires_at = existing["lease_expires_at"]
                    delivery.idempotency_key = existing["idempotency_key"] or delivery.delivery_id
                    return delivery
                if existing["status"].upper() == DeliveryStatus.PROCESSING.value:
                    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                    if existing["lease_expires_at"] and existing["lease_expires_at"] > now_iso:
                        # Do not interrupt an active processing lease
                        delivery.status = DeliveryStatus.PROCESSING
                        delivery.attempts = existing["attempts"]
                        delivery.last_error = existing["last_error"]
                        delivery.next_retry_at = existing["next_retry_at"]
                        delivery.updated_at = existing["updated_at"]
                        delivery.claim_token = existing["claim_token"]
                        delivery.lease_expires_at = existing["lease_expires_at"]
                        delivery.idempotency_key = existing["idempotency_key"] or delivery.delivery_id
                        return delivery

            conn.execute("""
                INSERT INTO deliveries (
                    delivery_id, event_id, event_fingerprint, subscription_id, tenant_id,
                    status, attempts, max_attempts, last_error, next_retry_at, created_at, updated_at,
                    claim_token, lease_expires_at, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_fingerprint, subscription_id) DO UPDATE SET
                    status=CASE 
                        WHEN UPPER(deliveries.status) = 'SUCCESS' THEN deliveries.status 
                        WHEN UPPER(deliveries.status) = 'PROCESSING' AND deliveries.lease_expires_at > excluded.updated_at THEN deliveries.status
                        ELSE excluded.status 
                    END,
                    attempts=CASE 
                        WHEN UPPER(deliveries.status) = 'SUCCESS' THEN deliveries.attempts 
                        WHEN UPPER(deliveries.status) = 'PROCESSING' AND deliveries.lease_expires_at > excluded.updated_at THEN deliveries.attempts
                        ELSE excluded.attempts 
                    END,
                    last_error=CASE 
                        WHEN UPPER(deliveries.status) = 'SUCCESS' THEN deliveries.last_error 
                        ELSE excluded.last_error 
                    END,
                    next_retry_at=CASE 
                        WHEN UPPER(deliveries.status) = 'SUCCESS' THEN deliveries.next_retry_at 
                        ELSE excluded.next_retry_at 
                    END,
                    updated_at=CASE 
                        WHEN UPPER(deliveries.status) = 'SUCCESS' THEN deliveries.updated_at 
                        ELSE excluded.updated_at 
                    END,
                    claim_token=CASE 
                        WHEN UPPER(deliveries.status) = 'SUCCESS' THEN NULL 
                        WHEN UPPER(deliveries.status) = 'PROCESSING' AND deliveries.lease_expires_at > excluded.updated_at THEN deliveries.claim_token
                        ELSE excluded.claim_token 
                    END,
                    lease_expires_at=CASE 
                        WHEN UPPER(deliveries.status) = 'SUCCESS' THEN NULL 
                        WHEN UPPER(deliveries.status) = 'PROCESSING' AND deliveries.lease_expires_at > excluded.updated_at THEN deliveries.lease_expires_at
                        ELSE excluded.lease_expires_at 
                    END,
                    idempotency_key=CASE 
                        WHEN deliveries.idempotency_key IS NOT NULL THEN deliveries.idempotency_key
                        ELSE excluded.idempotency_key
                    END
                WHERE deliveries.tenant_id = excluded.tenant_id
            """, (
                delivery.delivery_id, delivery.event_id, delivery.event_fingerprint, delivery.subscription_id,
                delivery.tenant_id, delivery.status.value, delivery.attempts, delivery.max_attempts,
                delivery.last_error, delivery.next_retry_at, delivery.created_at, delivery.updated_at,
                delivery.claim_token, delivery.lease_expires_at, delivery.idempotency_key
            ))
            conn.commit()
            return delivery

    def claim_delivery(
        self,
        delivery_id: str,
        tenant_id: str,
        lease_seconds: int = 30,
        respect_backoff: bool = True,
        now_iso: Optional[str] = None
    ) -> Optional[EventDelivery]:
        """
        Atomically claims a pending or expired delivery for processing by a worker.
        Returns the claimed EventDelivery with its unique claim_token and lease_expires_at,
        or None if the delivery cannot be claimed.
        Strictly enforces tenant boundaries (raises ValueError on cross-tenant claim attempt).

        Acquires the SQLite write lock (via BEGIN IMMEDIATE) before determining the authoritative
        operation timestamp to eliminate time-of-check/time-of-use lock contention races.
        (Note: 'now_iso' is an optional injectable parameter reserved strictly for deterministic tests;
        production calls omit it so the post-lock timestamp is used.)
        """
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            if not now_iso:
                now_dt = datetime.now(UTC)
                effective_now_iso = now_dt.isoformat().replace("+00:00", "Z")
            else:
                effective_now_iso = now_iso
                now_dt = datetime.fromisoformat(effective_now_iso.replace("Z", "+00:00"))

            lease_expires_at = (now_dt + timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
            claim_token = f"claim_{uuid.uuid4().hex}"

            # 1. Tenant boundary validation
            existing = conn.execute("SELECT tenant_id, status FROM deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
            if existing and existing["tenant_id"] != tenant_id:
                conn.rollback()
                raise ValueError(
                    f"Cross-tenant delivery claim rejected: delivery belongs to '{existing['tenant_id']}', caller claims '{tenant_id}'"
                )

            # 2. Atomic claim update
            # Allowed if:
            # - status is PENDING (and if respect_backoff, next_retry_at is null or <= effective_now_iso)
            # OR
            # - status is PROCESSING and lease_expires_at <= effective_now_iso (expired lease recovery)
            # AND status != SUCCESS
            # AND NOT dead-lettered
            if respect_backoff:
                cur = conn.execute("""
                    UPDATE deliveries
                    SET status = 'PROCESSING',
                        claim_token = ?,
                        lease_expires_at = ?,
                        attempts = attempts + 1,
                        updated_at = ?
                    WHERE delivery_id = ?
                      AND tenant_id = ?
                      AND UPPER(status) != 'SUCCESS'
                      AND (
                          (UPPER(status) = 'PENDING' AND (next_retry_at IS NULL OR next_retry_at <= ?))
                          OR
                          (UPPER(status) = 'PROCESSING' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM dead_letters dl 
                          WHERE dl.delivery_id = deliveries.delivery_id 
                            AND dl.tenant_id = deliveries.tenant_id
                      )
                """, (
                    claim_token, lease_expires_at, effective_now_iso,
                    delivery_id, tenant_id,
                    effective_now_iso, effective_now_iso
                ))
            else:
                cur = conn.execute("""
                    UPDATE deliveries
                    SET status = 'PROCESSING',
                        claim_token = ?,
                        lease_expires_at = ?,
                        attempts = attempts + 1,
                        updated_at = ?
                    WHERE delivery_id = ?
                      AND tenant_id = ?
                      AND UPPER(status) != 'SUCCESS'
                      AND (
                          UPPER(status) = 'PENDING'
                          OR
                          (UPPER(status) = 'PROCESSING' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM dead_letters dl 
                          WHERE dl.delivery_id = deliveries.delivery_id 
                            AND dl.tenant_id = deliveries.tenant_id
                      )
                """, (
                    claim_token, lease_expires_at, effective_now_iso,
                    delivery_id, tenant_id,
                    effective_now_iso
                ))

            if cur.rowcount == 0:
                conn.rollback()
                return None

            conn.commit()

            row = conn.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ? AND tenant_id = ?",
                (delivery_id, tenant_id)
            ).fetchone()
            if row:
                return EventDelivery(**dict(row))
            return None
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def renew_delivery_lease(
        self,
        delivery_id: str,
        tenant_id: str,
        claim_token: str,
        extension_seconds: int = 30,
        now_iso: Optional[str] = None
    ) -> Optional[EventDelivery]:
        """
        Atomically extends the lease of an active in-flight delivery claim.
        Requires matching delivery_id, tenant_id, claim_token, and an unexpired lease.
        Rejects stale claim tokens, expired leases, SUCCESS deliveries, and dead letters.
        Strictly enforces tenant boundaries (raises ValueError on cross-tenant renewal).

        The authoritative operation timestamp is acquired AFTER obtaining the SQLite
        write lock (via BEGIN IMMEDIATE) to eliminate time-of-check / time-of-use races
        caused by write lock contention.
        (Note: 'now_iso' is an optional injectable parameter reserved strictly for deterministic tests;
        production calls omit it so the post-lock timestamp is used.)
        """
        conn = self._get_conn()
        try:
            # 1. Acquire SQLite write lock BEFORE determining authoritative timestamp
            conn.execute("BEGIN IMMEDIATE;")

            # 2. Determine authoritative timestamp AFTER write lock is held
            if not now_iso:
                now_dt = datetime.now(UTC)
                effective_now_iso = now_dt.isoformat().replace("+00:00", "Z")
            else:
                effective_now_iso = now_iso
                now_dt = datetime.fromisoformat(effective_now_iso.replace("Z", "+00:00"))

            new_lease_expires_at = (now_dt + timedelta(seconds=extension_seconds)).isoformat().replace("+00:00", "Z")

            # 3. Tenant boundary check
            existing = conn.execute(
                "SELECT tenant_id, status, claim_token, lease_expires_at FROM deliveries WHERE delivery_id = ?",
                (delivery_id,)
            ).fetchone()
            if not existing:
                conn.rollback()
                return None
            if existing["tenant_id"] != tenant_id:
                conn.rollback()
                raise ValueError(
                    f"Cross-tenant delivery renewal rejected: delivery belongs to '{existing['tenant_id']}', caller renewed as '{tenant_id}'"
                )

            # 4. Status and claim check
            if existing["status"].upper() != "PROCESSING":
                conn.rollback()
                return None
            if existing["claim_token"] != claim_token:
                conn.rollback()
                return None
            if existing["lease_expires_at"] and existing["lease_expires_at"] < effective_now_iso:
                # Already expired: cannot renew/resurrect
                conn.rollback()
                return None

            # 5. Atomic lease extension predicate
            cur = conn.execute("""
                UPDATE deliveries
                SET lease_expires_at = ?,
                    updated_at = ?
                WHERE delivery_id = ?
                  AND tenant_id = ?
                  AND claim_token = ?
                  AND UPPER(status) = 'PROCESSING'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at >= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM dead_letters dl 
                      WHERE dl.delivery_id = deliveries.delivery_id 
                        AND dl.tenant_id = deliveries.tenant_id
                  )
            """, (
                new_lease_expires_at, effective_now_iso,
                delivery_id, tenant_id, claim_token,
                effective_now_iso
            ))

            if cur.rowcount == 0:
                conn.rollback()
                return None

            conn.commit()

            row = conn.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ? AND tenant_id = ?",
                (delivery_id, tenant_id)
            ).fetchone()
            if row:
                return EventDelivery(**dict(row))
            return None
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def finalize_delivery(
        self,
        delivery_id: str,
        tenant_id: str,
        claim_token: str,
        success: bool,
        error_msg: Optional[str] = None,
        now_iso: Optional[str] = None
    ) -> Optional[EventDelivery]:
        """
        Finalizes an in-flight delivery attempt using the current claim token and lease.
        Only the holder of the active, unexpired claim_token may finalize the delivery.
        Rejects stale claim tokens, expired leases (even if not yet reclaimed),
        cross-tenant finalizations, and prevents downgrading SUCCESS.

        The authoritative operation timestamp is acquired AFTER obtaining the SQLite
        write lock (via BEGIN IMMEDIATE) to eliminate time-of-check / time-of-use races
        caused by write lock contention.
        (Note: 'now_iso' is an optional injectable parameter reserved strictly for deterministic tests;
        production calls omit it so the post-lock timestamp is used.)
        """
        conn = self._get_conn()
        try:
            # 1. Acquire SQLite write lock BEFORE determining authoritative timestamp
            conn.execute("BEGIN IMMEDIATE;")

            # 2. Determine authoritative timestamp AFTER write lock is held
            if not now_iso:
                now_dt = datetime.now(UTC)
                effective_now_iso = now_dt.isoformat().replace("+00:00", "Z")
            else:
                effective_now_iso = now_iso
                now_dt = datetime.fromisoformat(effective_now_iso.replace("Z", "+00:00"))

            # 3. Tenant boundary check
            existing = conn.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ?",
                (delivery_id,)
            ).fetchone()
            if not existing:
                conn.rollback()
                return None
            if existing["tenant_id"] != tenant_id:
                conn.rollback()
                raise ValueError(
                    f"Cross-tenant delivery finalization rejected: delivery belongs to '{existing['tenant_id']}', caller finalized as '{tenant_id}'"
                )

            # Check if delivery is already SUCCESS (cannot be downgraded or mutated by late worker)
            if existing["status"].upper() == "SUCCESS":
                conn.rollback()
                return None

            # Check claim token match
            if existing["claim_token"] != claim_token:
                # Stale token, expired lease superseded by another worker
                conn.rollback()
                return None

            # Check lease expiration in-memory check (fail fast if expired)
            if existing["lease_expires_at"] and existing["lease_expires_at"] < effective_now_iso:
                # Lease has expired; cannot finalize attempt
                conn.rollback()
                return None

            if existing["status"].upper() != "PROCESSING":
                conn.rollback()
                return None

            if success:
                cur = conn.execute("""
                    UPDATE deliveries
                    SET status = 'SUCCESS',
                        claim_token = NULL,
                        lease_expires_at = NULL,
                        last_error = NULL,
                        next_retry_at = NULL,
                        updated_at = ?
                    WHERE delivery_id = ?
                      AND tenant_id = ?
                      AND claim_token = ?
                      AND UPPER(status) = 'PROCESSING'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at >= ?
                """, (effective_now_iso, delivery_id, tenant_id, claim_token, effective_now_iso))
                if cur.rowcount == 0:
                    conn.rollback()
                    return None
                conn.commit()
            else:
                attempts = existing["attempts"]
                max_attempts = existing["max_attempts"]

                if attempts < max_attempts:
                    backoff_seconds = min(2 ** attempts, 60)
                    next_retry_at = (now_dt + timedelta(seconds=backoff_seconds)).isoformat().replace("+00:00", "Z")
                    cur = conn.execute("""
                        UPDATE deliveries
                        SET status = 'PENDING',
                            claim_token = NULL,
                            lease_expires_at = NULL,
                            last_error = ?,
                            next_retry_at = ?,
                            updated_at = ?
                        WHERE delivery_id = ?
                          AND tenant_id = ?
                          AND claim_token = ?
                          AND UPPER(status) = 'PROCESSING'
                          AND lease_expires_at IS NOT NULL
                          AND lease_expires_at >= ?
                    """, (error_msg or "Delivery attempt failed", next_retry_at, effective_now_iso, delivery_id, tenant_id, claim_token, effective_now_iso))
                    if cur.rowcount == 0:
                        conn.rollback()
                        return None
                    conn.commit()
                else:
                    # Retry limit reached -> Terminal dead letter
                    cur = conn.execute("""
                        UPDATE deliveries
                        SET status = 'FAILED',
                            claim_token = NULL,
                            lease_expires_at = NULL,
                            last_error = ?,
                            next_retry_at = NULL,
                            updated_at = ?
                        WHERE delivery_id = ?
                          AND tenant_id = ?
                          AND claim_token = ?
                          AND UPPER(status) = 'PROCESSING'
                          AND lease_expires_at IS NOT NULL
                          AND lease_expires_at >= ?
                    """, (error_msg or "Max retry attempts reached", effective_now_iso, delivery_id, tenant_id, claim_token, effective_now_iso))

                    if cur.rowcount == 0:
                        conn.rollback()
                        return None

                    dl = DeadLetter(
                        dead_letter_id=f"dl_{uuid.uuid4().hex}",
                        delivery_id=delivery_id,
                        event_id=existing["event_id"],
                        subscription_id=existing["subscription_id"],
                        tenant_id=tenant_id,
                        failure_reason=error_msg or "Max retries exhausted",
                        attempt_count=attempts,
                        recorded_at=effective_now_iso
                    )
                    conn.execute("""
                        INSERT OR IGNORE INTO dead_letters (
                            dead_letter_id, delivery_id, event_id, subscription_id, tenant_id,
                            failure_reason, attempt_count, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        dl.dead_letter_id, dl.delivery_id, dl.event_id, dl.subscription_id, dl.tenant_id,
                        dl.failure_reason, dl.attempt_count, dl.recorded_at
                    ))
                    conn.commit()

            row = conn.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ? AND tenant_id = ?",
                (delivery_id, tenant_id)
            ).fetchone()
            if row:
                return EventDelivery(**dict(row))
            return None
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()


    def get_delivery(self, delivery_id: str, tenant_id: str) -> Optional[EventDelivery]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM deliveries WHERE delivery_id = ? AND tenant_id = ?", (delivery_id, tenant_id)).fetchone()
            if row:
                return EventDelivery(**dict(row))
            return None

    def get_deliveries_for_event(self, event_fingerprint: str, tenant_id: str) -> List[EventDelivery]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM deliveries WHERE event_fingerprint = ? AND tenant_id = ? ORDER BY created_at ASC",
                (event_fingerprint, tenant_id)
            ).fetchall()
            return [EventDelivery(**dict(row)) for row in rows]

    def get_pending_deliveries(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 50,
        now_iso: Optional[str] = None,
        include_stale_leases: bool = True
    ) -> List[EventDelivery]:
        current_time_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with self._get_conn() as conn:
            if include_stale_leases:
                if now_iso:
                    query = """
                        SELECT * FROM deliveries 
                        WHERE (
                            (UPPER(status) = ? AND (next_retry_at IS NULL OR next_retry_at <= ?))
                            OR
                            (UPPER(status) = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM dead_letters dl 
                            WHERE dl.delivery_id = deliveries.delivery_id 
                              AND dl.tenant_id = deliveries.tenant_id
                        )
                    """
                    params = [DeliveryStatus.PENDING.value, now_iso, DeliveryStatus.PROCESSING.value, now_iso]
                else:
                    query = """
                        SELECT * FROM deliveries 
                        WHERE (
                            UPPER(status) = ?
                            OR
                            (UPPER(status) = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM dead_letters dl 
                            WHERE dl.delivery_id = deliveries.delivery_id 
                              AND dl.tenant_id = deliveries.tenant_id
                        )
                    """
                    params = [DeliveryStatus.PENDING.value, DeliveryStatus.PROCESSING.value, current_time_iso]
            else:
                query = """
                    SELECT * FROM deliveries 
                    WHERE UPPER(status) = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM dead_letters dl 
                        WHERE dl.delivery_id = deliveries.delivery_id 
                          AND dl.tenant_id = deliveries.tenant_id
                    )
                """
                params = [DeliveryStatus.PENDING.value]
                if now_iso:
                    query += " AND (next_retry_at IS NULL OR next_retry_at <= ?)"
                    params.append(now_iso)

            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            query += " ORDER BY created_at ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [EventDelivery(**dict(row)) for row in rows]

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

    def get_dead_letter(self, dead_letter_id: str, tenant_id: str) -> Optional[DeadLetter]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM dead_letters WHERE dead_letter_id = ? AND tenant_id = ?", (dead_letter_id, tenant_id)).fetchone()
            if row:
                return DeadLetter(**dict(row))
            return None

    def get_dead_letter_by_delivery_id(self, delivery_id: str, tenant_id: str) -> Optional[DeadLetter]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM dead_letters WHERE delivery_id = ? AND tenant_id = ?", (delivery_id, tenant_id)).fetchone()
            if row:
                return DeadLetter(**dict(row))
            return None

    def redrive_dead_letter(self, dead_letter_id: str, tenant_id: str) -> Optional[EventDelivery]:
        """
        Administratively recovers a terminally exhausted dead letter.
        Removes the dead letter record and re-arms the associated delivery to PENDING
        with reset attempt counter, cleared leases, strictly within tenant boundary.
        """
        with self._get_conn() as conn:
            dl_row = conn.execute(
                "SELECT * FROM dead_letters WHERE dead_letter_id = ? AND tenant_id = ?",
                (dead_letter_id, tenant_id)
            ).fetchone()
            if not dl_row:
                return None
                
            delivery_id = dl_row["delivery_id"]
            
            deliv_row = conn.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ? AND tenant_id = ?",
                (delivery_id, tenant_id)
            ).fetchone()
            if not deliv_row:
                return None
                
            delivery = EventDelivery(**dict(deliv_row))
            if delivery.status == DeliveryStatus.SUCCESS:
                return delivery
                
            conn.execute(
                "DELETE FROM dead_letters WHERE dead_letter_id = ? AND tenant_id = ?",
                (dead_letter_id, tenant_id)
            )
            
            now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            conn.execute("""
                UPDATE deliveries
                SET status = ?, attempts = 0, last_error = NULL, next_retry_at = NULL, claim_token = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE delivery_id = ? AND tenant_id = ?
            """, (DeliveryStatus.PENDING.value, now_iso, delivery_id, tenant_id))
            conn.commit()
            
            delivery.status = DeliveryStatus.PENDING
            delivery.attempts = 0
            delivery.last_error = None
            delivery.next_retry_at = None
            delivery.claim_token = None
            delivery.lease_expires_at = None
            delivery.updated_at = now_iso
            return delivery
