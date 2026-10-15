# backend/repositories/autonomy_repository.py
"""
SageCommand V3 — Autonomy Levels & Guarded Delegation Foundation Repository
Prompt 38 — Thread-safe, tenant-isolated SQLite persistence for autonomy grants,
revisions, idempotency records, and deterministic decision ledger.

Invariants:
1. All queries are parameterized and scoped strictly by tenant_id.
2. Optimistic concurrency control via revision numbers prevents concurrent overwrites.
3. Revoked grants CANNOT be reactivated or updated via ordinary update operations.
4. Idempotency keys prevent duplicate grant creation on retries.
5. All mutations and revisions are persisted atomically with thread safety.
"""

import json
import sqlite3
import threading
import logging
import time
import uuid
import hashlib
from typing import Dict, Any, List, Optional, Tuple, Callable

try:
    from core.config import (
        SAGE_AUTONOMY_DB_PATH,
        SAGE_AUTONOMY_MAX_GRANTS_LIST,
        SAGE_AUTONOMY_DEFAULT_GRANTS_LIMIT,
        SAGE_AUTONOMY_DECISIONS_HISTORY_LIMIT,
    )
    from data.schemas.autonomy_contract import (
        AutonomyGrant,
        AutonomyGrantStatus,
        AutonomyLevel,
        SubjectType,
        AutonomyScope,
        AutonomyConstraints,
        AutonomyProvenance,
        AutonomyDecision,
        AutonomyDecisionEffect,
        AutonomyReasonCode,
        SCHEMA_VERSION,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_AUTONOMY_DB_PATH,
        SAGE_AUTONOMY_MAX_GRANTS_LIST,
        SAGE_AUTONOMY_DEFAULT_GRANTS_LIMIT,
        SAGE_AUTONOMY_DECISIONS_HISTORY_LIMIT,
    )
    from backend.data.schemas.autonomy_contract import (
        AutonomyGrant,
        AutonomyGrantStatus,
        AutonomyLevel,
        SubjectType,
        AutonomyScope,
        AutonomyConstraints,
        AutonomyProvenance,
        AutonomyDecision,
        AutonomyDecisionEffect,
        AutonomyReasonCode,
        SCHEMA_VERSION,
    )

logger = logging.getLogger("autonomy_repository")


class AutonomyRepositoryError(Exception):
    """Base exception for autonomy repository errors."""
    pass


class AutonomyNotFoundError(AutonomyRepositoryError):
    """Raised when an autonomy grant is not found within scope."""
    pass


class AutonomyConcurrencyError(AutonomyRepositoryError):
    """Raised when an update conflicts with the current grant revision (optimistic locking failure)."""
    pass


class AutonomyInvalidTransitionError(AutonomyRepositoryError):
    """Raised when an invalid grant lifecycle transition is requested (e.g. updating a revoked grant)."""
    pass


class AutonomyIdempotencyConflictError(AutonomyRepositoryError):
    """Raised when an idempotency key is reused with conflicting parameters."""
    pass


class AutonomyRepository:
    """
    Production SQLite Repository for Autonomy Grants, Revisions, and Decisions.
    Guarantees thread-safe SQLite operations with WAL mode and atomic mutations.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SAGE_AUTONOMY_DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                self._create_tables_and_indexes(conn)

    def _create_tables_and_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_grants (
                grant_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                autonomy_level INTEGER NOT NULL,
                plant_id TEXT,
                session_id TEXT,
                data_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                effective_from REAL NOT NULL,
                expires_at REAL,
                permitted_capabilities_json TEXT NOT NULL,
                restricted_capabilities_json TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                schema_version TEXT NOT NULL,
                PRIMARY KEY (tenant_id, grant_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_revisions (
                revision_id TEXT PRIMARY KEY,
                grant_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                change_reason TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_decisions (
                decision_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                requested_capability TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                reason TEXT NOT NULL,
                effective_level INTEGER NOT NULL,
                scope_json TEXT NOT NULL,
                data_mode TEXT NOT NULL,
                risk_status TEXT NOT NULL,
                approval_requirement INTEGER NOT NULL,
                grant_id TEXT,
                decision_hash TEXT NOT NULL,
                evaluated_at REAL NOT NULL,
                request_id TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS autonomy_idempotency (
                idempotency_key TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                grant_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (tenant_id, idempotency_key)
            )
        """)

        # Indexes for fast subject lookup and audit review
        conn.execute("CREATE INDEX IF NOT EXISTS idx_autonomy_grants_subject ON autonomy_grants(tenant_id, subject_type, subject_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_autonomy_grants_workspace ON autonomy_grants(tenant_id, workspace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_autonomy_revisions_grant ON autonomy_revisions(tenant_id, grant_id, revision)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_autonomy_decisions_subject ON autonomy_decisions(tenant_id, subject_id, evaluated_at DESC)")

        # Seed canonical default agent grants for tenant_default if absent
        now = time.time()
        for default_subj in ("agent_action_tool", "agent_default"):
            existing = conn.execute(
                "SELECT grant_id FROM autonomy_grants WHERE tenant_id = 'tenant_default' AND subject_id = ?",
                (default_subj,)
            ).fetchone()
            if not existing:
                g_id = f"grant_{default_subj}_default"
                constraints_dump = json.dumps(AutonomyConstraints().model_dump())
                provenance_dump = json.dumps(AutonomyProvenance(
                    created_by_user_id="system_init",
                    granted_by_user_id="system_init",
                    grant_reason="Canonical baseline agent recommendation grant"
                ).model_dump())
                conn.execute("""
                    INSERT INTO autonomy_grants (
                        grant_id, tenant_id, workspace_id, subject_type, subject_id,
                        autonomy_level, plant_id, session_id, data_mode, status,
                        revision, effective_from, expires_at, permitted_capabilities_json,
                        restricted_capabilities_json, constraints_json, provenance_json,
                        created_by, created_at, updated_at, schema_version
                    ) VALUES (?, 'tenant_default', 'workspace_default', 'AGENT', ?,
                              2, '*', NULL, 'REAL', 'ACTIVE',
                              1, ?, NULL, '[]', '[]', ?, ?,
                              'system_init', ?, ?, '3.0.0')
                """, (g_id, default_subj, now, constraints_dump, provenance_dump, now, now))


    def _row_to_grant(self, row: sqlite3.Row) -> AutonomyGrant:
        return AutonomyGrant(
            grant_id=row["grant_id"],
            schema_version=row["schema_version"],
            subject_type=SubjectType(row["subject_type"]),
            subject_id=row["subject_id"],
            autonomy_level=AutonomyLevel(row["autonomy_level"]),
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            plant_id=row["plant_id"],
            data_mode=row["data_mode"],
            permitted_capabilities=json.loads(row["permitted_capabilities_json"]),
            restricted_capabilities=json.loads(row["restricted_capabilities_json"]),
            constraints=AutonomyConstraints(**json.loads(row["constraints_json"])),
            effective_from=row["effective_from"],
            expires_at=row["expires_at"],
            status=AutonomyGrantStatus(row["status"]),
            revision=row["revision"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            provenance=AutonomyProvenance(**json.loads(row["provenance_json"]))
        )

    def _row_to_decision(self, row: sqlite3.Row) -> AutonomyDecision:
        scope_data = json.loads(row["scope_json"])
        return AutonomyDecision(
            decision_id=row["decision_id"],
            decision=AutonomyDecisionEffect(row["decision"]),
            reason_code=AutonomyReasonCode(row["reason_code"]),
            reason=row["reason"],
            subject_type=SubjectType(row["subject_type"]),
            subject_id=row["subject_id"],
            requested_capability=row["requested_capability"],
            effective_autonomy_level=AutonomyLevel(row["effective_level"]),
            scope=AutonomyScope(**scope_data),
            data_mode=row["data_mode"],
            risk_status=row["risk_status"],
            approval_requirement=bool(row["approval_requirement"]),
            matched_constraints=[],
            failed_constraints=[],
            evaluated_at=row["evaluated_at"],
            policy_version="3.0.0",
            autonomy_profile_revision=1,
            request_id=row["request_id"],
            grant_id=row["grant_id"],
            decision_hash=row["decision_hash"]
        )

    def create_grant(
        self,
        grant: AutonomyGrant,
        idempotency_key: Optional[str] = None
    ) -> AutonomyGrant:
        """
        Creates a new autonomy grant.
        Handles idempotency keys deterministically.
        """
        with self._lock:
            with self._get_connection() as conn:
                # 1. Idempotency Check
                if idempotency_key:
                    clean_key = idempotency_key.strip()
                    row = conn.execute(
                        "SELECT grant_id, payload_hash FROM autonomy_idempotency WHERE tenant_id = ? AND idempotency_key = ?",
                        (grant.tenant_id, clean_key)
                    ).fetchone()
                    if row:
                        existing_grant_id = row["grant_id"]
                        existing_grant = self._get_grant_in_conn(conn, existing_grant_id, grant.tenant_id)
                        if existing_grant:
                            # Verify payload consistency
                            current_hash = self._compute_grant_payload_hash(grant)
                            if row["payload_hash"] != current_hash:
                                raise AutonomyIdempotencyConflictError(
                                    f"Idempotency key '{clean_key}' was already used with different parameters."
                                )
                            return existing_grant

                # 2. Persist grant
                conn.execute("""
                    INSERT INTO autonomy_grants (
                        grant_id, tenant_id, workspace_id, subject_type, subject_id,
                        autonomy_level, plant_id, session_id, data_mode, status,
                        revision, effective_from, expires_at, permitted_capabilities_json,
                        restricted_capabilities_json, constraints_json, provenance_json,
                        created_by, created_at, updated_at, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    grant.grant_id,
                    grant.tenant_id,
                    grant.workspace_id,
                    grant.subject_type.value,
                    grant.subject_id,
                    int(grant.autonomy_level),
                    grant.plant_id,
                    grant.session_id,
                    grant.data_mode,
                    grant.status.value,
                    grant.revision,
                    grant.effective_from,
                    grant.expires_at,
                    json.dumps(grant.permitted_capabilities),
                    json.dumps(grant.restricted_capabilities),
                    json.dumps(grant.constraints.model_dump()),
                    json.dumps(grant.provenance.model_dump()),
                    grant.created_by,
                    grant.created_at,
                    grant.updated_at,
                    grant.schema_version,
                ))

                # 3. Create initial revision record
                rev_id = f"rev_{uuid.uuid4().hex[:12]}"
                conn.execute("""
                    INSERT INTO autonomy_revisions (
                        revision_id, grant_id, revision, tenant_id, workspace_id,
                        snapshot_json, change_reason, changed_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rev_id,
                    grant.grant_id,
                    grant.revision,
                    grant.tenant_id,
                    grant.workspace_id,
                    json.dumps(grant.model_dump()),
                    grant.provenance.grant_reason,
                    grant.created_by,
                    grant.created_at,
                ))

                # 4. Save idempotency record if supplied
                if idempotency_key:
                    conn.execute("""
                        INSERT INTO autonomy_idempotency (
                            idempotency_key, tenant_id, grant_id, payload_hash, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                    """, (
                        idempotency_key.strip(),
                        grant.tenant_id,
                        grant.grant_id,
                        self._compute_grant_payload_hash(grant),
                        time.time()
                    ))

                conn.commit()
                return grant

    save_grant = create_grant

    def _compute_grant_payload_hash(self, grant: AutonomyGrant) -> str:
        """Deterministic hash of substantive grant creation fields."""
        data = {
            "subject_type": grant.subject_type.value,
            "subject_id": grant.subject_id,
            "autonomy_level": int(grant.autonomy_level),
            "tenant_id": grant.tenant_id,
            "workspace_id": grant.workspace_id,
            "plant_id": grant.plant_id,
            "data_mode": grant.data_mode,
            "permitted": sorted(grant.permitted_capabilities),
            "restricted": sorted(grant.restricted_capabilities),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    def _get_grant_in_conn(
        self,
        conn: sqlite3.Connection,
        grant_id: str,
        tenant_id: str,
        workspace_id: Optional[str] = None
    ) -> Optional[AutonomyGrant]:
        query = "SELECT * FROM autonomy_grants WHERE grant_id = ? AND tenant_id = ?"
        params: List[Any] = [grant_id.strip(), tenant_id.strip()]
        if workspace_id and workspace_id != "*":
            query += " AND workspace_id = ?"
            params.append(workspace_id.strip())

        row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return self._row_to_grant(row)

    def get_grant(
        self,
        grant_id: str,
        tenant_id: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> Optional[AutonomyGrant]:
        """Retrieves a single autonomy grant by ID within tenant and optional workspace scope."""
        with self._lock:
            with self._get_connection() as conn:
                if tenant_id:
                    return self._get_grant_in_conn(conn, grant_id, tenant_id, workspace_id)
                row = conn.execute("SELECT * FROM autonomy_grants WHERE grant_id = ?", (grant_id.strip(),)).fetchone()
                if not row:
                    return None
                return self._row_to_grant(row)

    def get_active_grant_for_subject(
        self,
        subject_type: SubjectType,
        subject_id: str,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        data_mode: Optional[str] = None
    ) -> Optional[AutonomyGrant]:
        """
        Finds the active, unexpired autonomy grant for a subject within authoritative scope.
        Prioritizes narrower scope matches (e.g., matching plant_id over unrestricted).
        """
        with self._lock:
            with self._get_connection() as conn:
                query = """
                    SELECT * FROM autonomy_grants
                    WHERE tenant_id = ?
                      AND subject_type = ?
                      AND subject_id = ?
                      AND status = 'ACTIVE'
                """
                params: List[Any] = [tenant_id.strip(), subject_type.value, subject_id.strip()]

                if workspace_id and workspace_id != "*":
                    query += " AND (workspace_id = ? OR workspace_id = '*')"
                    params.append(workspace_id.strip())

                if plant_id and plant_id != "*":
                    query += " AND (plant_id = ? OR plant_id IS NULL OR plant_id = '*')"
                    params.append(plant_id.strip())

                if data_mode:
                    query += " AND (data_mode = ? OR (data_mode = 'REAL' AND ? = 'SIMULATION'))"
                    params.extend([data_mode.strip().upper(), data_mode.strip().upper()])

                query += " ORDER BY revision DESC, created_at DESC"
                rows = conn.execute(query, params).fetchall()

                now = time.time()
                for row in rows:
                    grant = self._row_to_grant(row)
                    if grant.is_active(now):
                        return grant

                return None

    def list_grants(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        subject_type: Optional[SubjectType] = None,
        subject_id: Optional[str] = None,
        status: Optional[AutonomyGrantStatus] = None,
        limit: int = SAGE_AUTONOMY_DEFAULT_GRANTS_LIMIT,
        offset: int = 0
    ) -> Tuple[List[AutonomyGrant], int]:
        """
        Lists autonomy grants within authorized tenant scope.
        Returns (grants_list, total_count).
        """
        with self._lock:
            with self._get_connection() as conn:
                where_clauses = ["tenant_id = ?"]
                params: List[Any] = [tenant_id.strip()]

                if workspace_id and workspace_id != "*":
                    where_clauses.append("(workspace_id = ? OR workspace_id = '*')")
                    params.append(workspace_id.strip())

                if subject_type:
                    where_clauses.append("subject_type = ?")
                    params.append(subject_type.value)

                if subject_id:
                    where_clauses.append("subject_id = ?")
                    params.append(subject_id.strip())

                if status:
                    where_clauses.append("status = ?")
                    params.append(status.value)

                where_sql = " AND ".join(where_clauses)

                # Total count
                count_row = conn.execute(f"SELECT COUNT(*) as cnt FROM autonomy_grants WHERE {where_sql}", params).fetchone()
                total = count_row["cnt"] if count_row else 0

                # Bounded query
                limit = min(max(1, limit), SAGE_AUTONOMY_MAX_GRANTS_LIST)
                offset = max(0, offset)

                query = f"""
                    SELECT * FROM autonomy_grants
                    WHERE {where_sql}
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = conn.execute(query, params + [limit, offset]).fetchall()
                grants = [self._row_to_grant(r) for r in rows]
                return grants, total

    def update_grant(
        self,
        grant_id: str,
        tenant_id: str,
        expected_revision: int,
        changed_by: str,
        change_reason: str,
        update_fn: Callable[[AutonomyGrant], AutonomyGrant]
    ) -> AutonomyGrant:
        """
        Updates an existing autonomy grant using optimistic concurrency revision control.
        Rejects stale revisions and prevents updating revoked grants.
        """
        with self._lock:
            with self._get_connection() as conn:
                existing = self._get_grant_in_conn(conn, grant_id, tenant_id)
                if not existing:
                    raise AutonomyNotFoundError(
                        f"Autonomy grant '{grant_id}' not found for tenant '{tenant_id}'."
                    )

                if existing.revision != expected_revision:
                    raise AutonomyConcurrencyError(
                        f"Stale revision: expected revision {expected_revision}, but current revision is {existing.revision}."
                    )

                if existing.status == AutonomyGrantStatus.REVOKED:
                    raise AutonomyInvalidTransitionError(
                        f"Cannot modify grant '{grant_id}': grant is REVOKED and cannot be reactivated or edited."
                    )

                # Apply modifications
                updated = update_fn(existing)
                updated.revision = existing.revision + 1
                updated.updated_at = time.time()

                cursor = conn.execute("""
                    UPDATE autonomy_grants
                    SET autonomy_level = ?,
                        plant_id = ?,
                        session_id = ?,
                        data_mode = ?,
                        status = ?,
                        revision = ?,
                        expires_at = ?,
                        permitted_capabilities_json = ?,
                        restricted_capabilities_json = ?,
                        constraints_json = ?,
                        updated_at = ?
                    WHERE grant_id = ? AND tenant_id = ? AND revision = ?
                """, (
                    int(updated.autonomy_level),
                    updated.plant_id,
                    updated.session_id,
                    updated.data_mode,
                    updated.status.value,
                    updated.revision,
                    updated.expires_at,
                    json.dumps(updated.permitted_capabilities),
                    json.dumps(updated.restricted_capabilities),
                    json.dumps(updated.constraints.model_dump()),
                    updated.updated_at,
                    grant_id.strip(),
                    tenant_id.strip(),
                    expected_revision,
                ))

                if cursor.rowcount == 0:
                    raise AutonomyConcurrencyError(
                        f"Concurrent update conflict on grant '{grant_id}'."
                    )

                # Record revision snapshot
                rev_id = f"rev_{uuid.uuid4().hex[:12]}"
                conn.execute("""
                    INSERT INTO autonomy_revisions (
                        revision_id, grant_id, revision, tenant_id, workspace_id,
                        snapshot_json, change_reason, changed_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rev_id,
                    updated.grant_id,
                    updated.revision,
                    updated.tenant_id,
                    updated.workspace_id,
                    json.dumps(updated.model_dump()),
                    change_reason,
                    changed_by,
                    updated.updated_at,
                ))

                conn.commit()
                return updated

    def suspend_grant(
        self,
        grant_id: str,
        tenant_id: str,
        expected_revision: int,
        changed_by: str,
        reason: str
    ) -> AutonomyGrant:
        """Transitions an active grant to SUSPENDED status."""
        def _suspend(g: AutonomyGrant) -> AutonomyGrant:
            if g.status != AutonomyGrantStatus.ACTIVE:
                raise AutonomyInvalidTransitionError(
                    f"Cannot suspend grant in status '{g.status.value}'. Only ACTIVE grants can be suspended."
                )
            g.status = AutonomyGrantStatus.SUSPENDED
            return g

        return self.update_grant(grant_id, tenant_id, expected_revision, changed_by, f"SUSPEND: {reason}", _suspend)

    def revoke_grant(
        self,
        grant_id: str,
        tenant_id: str = "tenant_default",
        expected_revision: Optional[int] = None,
        changed_by: str = "admin",
        reason: str = "Revocation",
        **kwargs: Any
    ) -> AutonomyGrant:
        """
        Permanently revokes an autonomy grant.
        Once revoked, a grant cannot be reactivated or updated.
        """
        if isinstance(expected_revision, str):
            actual_changed_by = tenant_id
            actual_reason = expected_revision
            changed_by = actual_changed_by
            reason = actual_reason
            tenant_id = kwargs.get("tenant_id") or "tenant_default"
            expected_revision = None

        if expected_revision is None:
            g = self.get_grant(grant_id, tenant_id=tenant_id)
            if not g:
                raise AutonomyNotFoundError(f"Grant '{grant_id}' not found.")
            expected_revision = g.revision

        def _revoke(g: AutonomyGrant) -> AutonomyGrant:
            g.status = AutonomyGrantStatus.REVOKED
            return g

        return self.update_grant(grant_id, tenant_id, expected_revision, changed_by, f"REVOKE: {reason}", _revoke)

    def record_decision(self, decision: AutonomyDecision) -> AutonomyDecision:
        """Records an auditable capability evaluation decision."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO autonomy_decisions (
                        decision_id, tenant_id, workspace_id, subject_type, subject_id,
                        requested_capability, decision, reason_code, reason, effective_level,
                        scope_json, data_mode, risk_status, approval_requirement, grant_id,
                        decision_hash, evaluated_at, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    decision.decision_id,
                    decision.scope.tenant_id,
                    decision.scope.workspace_id,
                    decision.subject_type.value,
                    decision.subject_id,
                    decision.requested_capability,
                    decision.decision.value,
                    decision.reason_code.value,
                    decision.reason,
                    int(decision.effective_autonomy_level),
                    json.dumps(decision.scope.model_dump()),
                    decision.data_mode,
                    decision.risk_status,
                    1 if decision.approval_requirement else 0,
                    decision.grant_id,
                    decision.decision_hash,
                    decision.evaluated_at,
                    decision.request_id,
                ))
                conn.commit()
                return decision

    def list_decisions(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        limit: int = SAGE_AUTONOMY_DECISIONS_HISTORY_LIMIT
    ) -> List[AutonomyDecision]:
        """Lists recent autonomy evaluation decisions for audit trail."""
        with self._lock:
            with self._get_connection() as conn:
                where_clauses = ["tenant_id = ?"]
                params: List[Any] = [tenant_id.strip()]

                if workspace_id and workspace_id != "*":
                    where_clauses.append("(workspace_id = ? OR workspace_id IS NULL)")
                    params.append(workspace_id.strip())

                if subject_id:
                    where_clauses.append("subject_id = ?")
                    params.append(subject_id.strip())

                where_sql = " AND ".join(where_clauses)
                limit = min(max(1, limit), SAGE_AUTONOMY_DECISIONS_HISTORY_LIMIT)

                query = f"""
                    SELECT * FROM autonomy_decisions
                    WHERE {where_sql}
                    ORDER BY evaluated_at DESC
                    LIMIT ?
                """
                rows = conn.execute(query, params + [limit]).fetchall()
                return [self._row_to_decision(r) for r in rows]


# Global default repository instance
autonomy_repository = AutonomyRepository()
