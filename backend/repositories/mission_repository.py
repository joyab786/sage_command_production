# backend/repositories/mission_repository.py
"""
SageCommand V3 — Governed Mission Architecture Foundation Repository (Prompt 35)

A MISSION IS A GOVERNED OPERATIONAL OBJECTIVE AND WORK PLAN ONLY — NEVER CONSTITUTES
DIRECT EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Thread-safe, tenant-isolated SQLite WAL repository for industrial missions,
immutable revision history snapshots, append-only audit ledger, and idempotency checks.
Guarantees parameterized SQL queries, strict tenant and workspace boundaries,
and atomic mutations for all lifecycle transitions and audit records.
"""

import json
import sqlite3
import threading
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone

try:
    from core.config import (
        SAGE_MISSION_DB_PATH,
        SAGE_MISSION_MAX_LIST_RESULTS,
        SAGE_MISSION_DEFAULT_LIST_LIMIT,
    )
    from data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
        ConstraintType,
        MissionScope,
        MissionConstraint,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        MissionRevisionRecord,
        MissionAuditRecord,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_MISSION_DB_PATH,
        SAGE_MISSION_MAX_LIST_RESULTS,
        SAGE_MISSION_DEFAULT_LIST_LIMIT,
    )
    from backend.data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
        ConstraintType,
        MissionScope,
        MissionConstraint,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        MissionRevisionRecord,
        MissionAuditRecord,
    )

logger = logging.getLogger("mission_repository")


class MissionRepositoryError(Exception):
    """Base exception for mission repository operations."""
    pass


class MissionNotFoundError(MissionRepositoryError):
    """Raised when requested mission cannot be found within authorized scope."""
    pass


class MissionConcurrencyError(MissionRepositoryError):
    """Raised when concurrent modification conflict occurs."""
    pass


class MissionIdempotencyConflictError(MissionRepositoryError):
    """Raised when an idempotency key is reused with differing request payload."""
    pass


class MissionRepository:
    """
    Thread-safe SQLite WAL repository for governed mission persistence.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SAGE_MISSION_DB_PATH
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
            CREATE TABLE IF NOT EXISTS missions (
                mission_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                plant_id TEXT NOT NULL,
                session_id TEXT,
                schema_version TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                mission_type TEXT NOT NULL,
                objective TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                success_criteria_json TEXT NOT NULL,
                planned_steps_json TEXT NOT NULL,
                evidence_requirements_json TEXT NOT NULL,
                related_resources_json TEXT NOT NULL,
                data_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                validation_errors_json TEXT NOT NULL,
                validation_warnings_json TEXT NOT NULL,
                review_notes TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                PRIMARY KEY (tenant_id, workspace_id, mission_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_revisions (
                mission_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                plant_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                change_reason TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, mission_id, revision)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_audit_ledger (
                audit_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                plant_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                result TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_role TEXT,
                request_id TEXT,
                trace_id TEXT,
                details_json TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_idempotency_records (
                idempotency_key TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, idempotency_key)
            )
        """)

        # Indexes for scoped querying
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_missions_tenant_ws_status
            ON missions (tenant_id, workspace_id, status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_missions_tenant_ws_plant
            ON missions (tenant_id, workspace_id, plant_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_missions_tenant_ws_type
            ON missions (tenant_id, workspace_id, mission_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mission_revisions_lookup
            ON mission_revisions (tenant_id, workspace_id, mission_id, revision)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mission_audit_lookup
            ON mission_audit_ledger (tenant_id, workspace_id, mission_id)
        """)
        conn.commit()

    def _row_to_mission(self, row: sqlite3.Row) -> Mission:
        """Hydrates a Mission model from a database row."""
        scope = MissionScope(
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            session_id=row["session_id"],
        )

        constraints = [
            MissionConstraint(**item)
            for item in json.loads(row["constraints_json"])
        ]
        success_criteria = [
            MissionSuccessCriterion(**item)
            for item in json.loads(row["success_criteria_json"])
        ]
        planned_steps = [
            MissionPlannedStep(**item)
            for item in json.loads(row["planned_steps_json"])
        ]
        evidence_requirements = [
            MissionEvidenceRequirement(**item)
            for item in json.loads(row["evidence_requirements_json"])
        ]
        related_resources = json.loads(row["related_resources_json"])
        provenance = MissionProvenance(**json.loads(row["provenance_json"]))
        validation_errors = json.loads(row["validation_errors_json"])
        validation_warnings = json.loads(row["validation_warnings_json"])

        return Mission(
            mission_id=row["mission_id"],
            schema_version=row["schema_version"],
            revision=row["revision"],
            title=row["title"],
            description=row["description"],
            mission_type=MissionType(row["mission_type"]),
            objective=row["objective"],
            scope=scope,
            constraints=constraints,
            success_criteria=success_criteria,
            planned_steps=planned_steps,
            evidence_requirements=evidence_requirements,
            related_resources=related_resources,
            data_mode=DataMode(row["data_mode"]),
            status=MissionStatus(row["status"]),
            provenance=provenance,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row["created_by"],
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
            review_notes=row["review_notes"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
        )

    # -------------------------------------------------------------------------
    # IDEMPOTENCY
    # -------------------------------------------------------------------------

    def check_idempotency(
        self,
        tenant_id: str,
        workspace_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[str]:
        """
        Checks if an idempotency key exists.
        Returns mission_id if exact match, or raises MissionIdempotencyConflictError if payload differs.
        """
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT mission_id, request_hash
                    FROM mission_idempotency_records
                    WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?
                    """,
                    (tenant_id, workspace_id, idempotency_key),
                ).fetchone()

                if row is None:
                    return None

                if row["request_hash"] != request_hash:
                    raise MissionIdempotencyConflictError(
                        f"Idempotency key '{idempotency_key}' reused with conflicting request payload."
                    )

                return row["mission_id"]

    # -------------------------------------------------------------------------
    # CRUD & LIFECYCLE PERSISTENCE
    # -------------------------------------------------------------------------

    def create_mission(
        self,
        mission: Mission,
        change_reason: str,
        audit_event: Optional[MissionAuditRecord] = None,
        idempotency_key: Optional[str] = None,
        request_hash: Optional[str] = None,
    ) -> Mission:
        """
        Atomically creates a new mission, stores revision 1, registers idempotency key,
        and logs the audit event in a single transaction.
        """
        with self._lock:
            with self._get_connection() as conn:
                try:
                    # Check idempotency within lock
                    if idempotency_key and request_hash:
                        existing = conn.execute(
                            """
                            SELECT mission_id, request_hash
                            FROM mission_idempotency_records
                            WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?
                            """,
                            (mission.scope.tenant_id, mission.scope.workspace_id, idempotency_key),
                        ).fetchone()

                        if existing:
                            if existing["request_hash"] != request_hash:
                                raise MissionIdempotencyConflictError(
                                    f"Idempotency key '{idempotency_key}' reused with conflicting payload."
                                )
                            # Fetch and return existing mission
                            existing_mission_row = conn.execute(
                                """
                                SELECT * FROM missions
                                WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ?
                                """,
                                (mission.scope.tenant_id, mission.scope.workspace_id, existing["mission_id"]),
                            ).fetchone()
                            if existing_mission_row:
                                return self._row_to_mission(existing_mission_row)

                    # Insert mission
                    constraints_json = json.dumps([c.model_dump() for c in mission.constraints])
                    criteria_json = json.dumps([sc.model_dump() for sc in mission.success_criteria])
                    steps_json = json.dumps([ps.model_dump() for ps in mission.planned_steps])
                    evidence_json = json.dumps([er.model_dump() for er in mission.evidence_requirements])
                    related_json = json.dumps(mission.related_resources)
                    provenance_json = json.dumps(mission.provenance.model_dump())
                    errors_json = json.dumps(mission.validation_errors)
                    warnings_json = json.dumps(mission.validation_warnings)

                    conn.execute(
                        """
                        INSERT INTO missions (
                            mission_id, tenant_id, workspace_id, plant_id, session_id,
                            schema_version, revision, title, description, mission_type,
                            objective, constraints_json, success_criteria_json, planned_steps_json,
                            evidence_requirements_json, related_resources_json, data_mode,
                            status, provenance_json, created_at, updated_at, created_by,
                            validation_errors_json, validation_warnings_json,
                            review_notes, reviewed_by, reviewed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            mission.mission_id,
                            mission.scope.tenant_id,
                            mission.scope.workspace_id,
                            mission.scope.plant_id,
                            mission.scope.session_id,
                            mission.schema_version,
                            mission.revision,
                            mission.title,
                            mission.description,
                            mission.mission_type.value,
                            mission.objective,
                            constraints_json,
                            criteria_json,
                            steps_json,
                            evidence_json,
                            related_json,
                            mission.data_mode.value,
                            mission.status.value,
                            provenance_json,
                            mission.created_at,
                            mission.updated_at,
                            mission.created_by,
                            errors_json,
                            warnings_json,
                            mission.review_notes,
                            mission.reviewed_by,
                            mission.reviewed_at,
                        ),
                    )

                    # Snapshot initial revision
                    snapshot_json = mission.model_dump_json()
                    conn.execute(
                        """
                        INSERT INTO mission_revisions (
                            mission_id, revision, tenant_id, workspace_id, plant_id,
                            snapshot_json, change_reason, changed_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            mission.mission_id,
                            mission.revision,
                            mission.scope.tenant_id,
                            mission.scope.workspace_id,
                            mission.scope.plant_id,
                            snapshot_json,
                            change_reason,
                            mission.created_by,
                            mission.created_at,
                        ),
                    )

                    # Register idempotency key
                    if idempotency_key and request_hash:
                        conn.execute(
                            """
                            INSERT INTO mission_idempotency_records (
                                idempotency_key, tenant_id, workspace_id, mission_id, request_hash, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                idempotency_key,
                                mission.scope.tenant_id,
                                mission.scope.workspace_id,
                                mission.mission_id,
                                request_hash,
                                mission.created_at,
                            ),
                        )

                    # Append audit ledger record
                    if audit_event:
                        conn.execute(
                            """
                            INSERT INTO mission_audit_ledger (
                                audit_id, mission_id, revision, tenant_id, workspace_id, plant_id,
                                event_type, result, actor_id, actor_role, request_id, trace_id,
                                details_json, timestamp
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                audit_event.audit_id,
                                audit_event.mission_id,
                                audit_event.revision,
                                audit_event.tenant_id,
                                audit_event.workspace_id,
                                audit_event.plant_id,
                                audit_event.event_type,
                                audit_event.result,
                                audit_event.actor_id,
                                audit_event.actor_role,
                                audit_event.request_id,
                                audit_event.trace_id,
                                json.dumps(audit_event.details),
                                audit_event.timestamp,
                            ),
                        )

                    conn.commit()
                    return mission
                except Exception as e:
                    conn.rollback()
                    if isinstance(e, MissionRepositoryError):
                        raise
                    raise MissionRepositoryError(f"Failed to create mission: {str(e)}") from e

    def get_mission(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
    ) -> Optional[Mission]:
        """Retrieves a mission by composite primary key (tenant_id, workspace_id, mission_id)."""
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM missions
                    WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ?
                    """,
                    (tenant_id, workspace_id, mission_id),
                ).fetchone()

                if row is None:
                    return None

                return self._row_to_mission(row)

    def list_missions(
        self,
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str] = None,
        status: Optional[MissionStatus] = None,
        mission_type: Optional[MissionType] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Mission], int]:
        """Lists missions matching tenant, workspace, and optional filters with total count."""
        limit = min(max(1, limit), SAGE_MISSION_MAX_LIST_RESULTS)
        offset = max(0, offset)

        clauses = ["tenant_id = ?", "workspace_id = ?"]
        params: List[Any] = [tenant_id, workspace_id]

        if plant_id:
            clauses.append("plant_id = ?")
            params.append(plant_id)

        if status:
            clauses.append("status = ?")
            params.append(status.value)

        if mission_type:
            clauses.append("mission_type = ?")
            params.append(mission_type.value)

        where_sql = " AND ".join(clauses)

        with self._lock:
            with self._get_connection() as conn:
                count_row = conn.execute(
                    f"SELECT COUNT(*) as total FROM missions WHERE {where_sql}",
                    tuple(params),
                ).fetchone()
                total = count_row["total"] if count_row else 0

                query_params = list(params) + [limit, offset]
                rows = conn.execute(
                    f"""
                    SELECT * FROM missions
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    tuple(query_params),
                ).fetchall()

                missions = [self._row_to_mission(r) for r in rows]
                return missions, total

    def update_mission(
        self,
        mission: Mission,
        expected_revision: int,
        change_reason: str,
        changed_by: str,
        audit_event: Optional[MissionAuditRecord] = None,
    ) -> Mission:
        """
        Atomically updates a mission using optimistic concurrency on expected_revision.
        Increments revision, snapshots new revision, and appends audit event.
        """
        with self._lock:
            with self._get_connection() as conn:
                try:
                    # Verify current mission and revision
                    current_row = conn.execute(
                        """
                        SELECT revision, status FROM missions
                        WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ?
                        """,
                        (mission.scope.tenant_id, mission.scope.workspace_id, mission.mission_id),
                    ).fetchone()

                    if current_row is None:
                        raise MissionNotFoundError(
                            f"Mission '{mission.mission_id}' not found in authorized scope."
                        )

                    current_rev = current_row["revision"]
                    if current_rev != expected_revision:
                        raise MissionConcurrencyError(
                            f"Mission '{mission.mission_id}' revision conflict: expected {expected_revision}, found {current_rev}."
                        )

                    new_revision = current_rev + 1
                    mission.revision = new_revision
                    mission.updated_at = datetime.now(timezone.utc).isoformat()

                    constraints_json = json.dumps([c.model_dump() for c in mission.constraints])
                    criteria_json = json.dumps([sc.model_dump() for sc in mission.success_criteria])
                    steps_json = json.dumps([ps.model_dump() for ps in mission.planned_steps])
                    evidence_json = json.dumps([er.model_dump() for er in mission.evidence_requirements])
                    related_json = json.dumps(mission.related_resources)
                    provenance_json = json.dumps(mission.provenance.model_dump())
                    errors_json = json.dumps(mission.validation_errors)
                    warnings_json = json.dumps(mission.validation_warnings)

                    conn.execute(
                        """
                        UPDATE missions SET
                            revision = ?,
                            title = ?,
                            description = ?,
                            mission_type = ?,
                            objective = ?,
                            constraints_json = ?,
                            success_criteria_json = ?,
                            planned_steps_json = ?,
                            evidence_requirements_json = ?,
                            related_resources_json = ?,
                            status = ?,
                            provenance_json = ?,
                            updated_at = ?,
                            validation_errors_json = ?,
                            validation_warnings_json = ?,
                            review_notes = ?,
                            reviewed_by = ?,
                            reviewed_at = ?
                        WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ? AND revision = ?
                        """,
                        (
                            new_revision,
                            mission.title,
                            mission.description,
                            mission.mission_type.value,
                            mission.objective,
                            constraints_json,
                            criteria_json,
                            steps_json,
                            evidence_json,
                            related_json,
                            mission.status.value,
                            provenance_json,
                            mission.updated_at,
                            errors_json,
                            warnings_json,
                            mission.review_notes,
                            mission.reviewed_by,
                            mission.reviewed_at,
                            mission.scope.tenant_id,
                            mission.scope.workspace_id,
                            mission.mission_id,
                            current_rev,
                        ),
                    )

                    # Snapshot updated revision
                    snapshot_json = mission.model_dump_json()
                    conn.execute(
                        """
                        INSERT INTO mission_revisions (
                            mission_id, revision, tenant_id, workspace_id, plant_id,
                            snapshot_json, change_reason, changed_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            mission.mission_id,
                            new_revision,
                            mission.scope.tenant_id,
                            mission.scope.workspace_id,
                            mission.scope.plant_id,
                            snapshot_json,
                            change_reason,
                            changed_by,
                            mission.updated_at,
                        ),
                    )

                    # Record audit event
                    if audit_event:
                        audit_event.revision = new_revision
                        conn.execute(
                            """
                            INSERT INTO mission_audit_ledger (
                                audit_id, mission_id, revision, tenant_id, workspace_id, plant_id,
                                event_type, result, actor_id, actor_role, request_id, trace_id,
                                details_json, timestamp
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                audit_event.audit_id,
                                audit_event.mission_id,
                                audit_event.revision,
                                audit_event.tenant_id,
                                audit_event.workspace_id,
                                audit_event.plant_id,
                                audit_event.event_type,
                                audit_event.result,
                                audit_event.actor_id,
                                audit_event.actor_role,
                                audit_event.request_id,
                                audit_event.trace_id,
                                json.dumps(audit_event.details),
                                audit_event.timestamp,
                            ),
                        )

                    conn.commit()
                    return mission
                except Exception as e:
                    conn.rollback()
                    if isinstance(e, MissionRepositoryError):
                        raise
                    raise MissionRepositoryError(f"Failed to update mission: {str(e)}") from e

    def get_revisions(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
    ) -> List[MissionRevisionRecord]:
        """Fetches all revision snapshots for a mission in ascending revision order."""
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM mission_revisions
                    WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ?
                    ORDER BY revision ASC
                    """,
                    (tenant_id, workspace_id, mission_id),
                ).fetchall()

                return [
                    MissionRevisionRecord(
                        mission_id=r["mission_id"],
                        revision=r["revision"],
                        tenant_id=r["tenant_id"],
                        workspace_id=r["workspace_id"],
                        plant_id=r["plant_id"],
                        snapshot_json=r["snapshot_json"],
                        change_reason=r["change_reason"],
                        changed_by=r["changed_by"],
                        created_at=r["created_at"],
                    )
                    for r in rows
                ]

    def get_audit_ledger(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
        limit: int = 50,
    ) -> List[MissionAuditRecord]:
        """Fetches audit events for a mission in descending timestamp order."""
        limit = min(max(1, limit), 200)
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM mission_audit_ledger
                    WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (tenant_id, workspace_id, mission_id, limit),
                ).fetchall()

                return [
                    MissionAuditRecord(
                        audit_id=r["audit_id"],
                        mission_id=r["mission_id"],
                        revision=r["revision"],
                        tenant_id=r["tenant_id"],
                        workspace_id=r["workspace_id"],
                        plant_id=r["plant_id"],
                        event_type=r["event_type"],
                        result=r["result"],
                        actor_id=r["actor_id"],
                        actor_role=r["actor_role"],
                        request_id=r["request_id"],
                        trace_id=r["trace_id"],
                        details=json.loads(r["details_json"]),
                        timestamp=r["timestamp"],
                    )
                    for r in rows
                ]

    def record_audit(self, audit_event: MissionAuditRecord) -> None:
        """Records a standalone audit event (e.g. access denied)."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO mission_audit_ledger (
                        audit_id, mission_id, revision, tenant_id, workspace_id, plant_id,
                        event_type, result, actor_id, actor_role, request_id, trace_id,
                        details_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_event.audit_id,
                        audit_event.mission_id,
                        audit_event.revision,
                        audit_event.tenant_id,
                        audit_event.workspace_id,
                        audit_event.plant_id,
                        audit_event.event_type,
                        audit_event.result,
                        audit_event.actor_id,
                        audit_event.actor_role,
                        audit_event.request_id,
                        audit_event.trace_id,
                        json.dumps(audit_event.details),
                        audit_event.timestamp,
                    ),
                )
                conn.commit()
