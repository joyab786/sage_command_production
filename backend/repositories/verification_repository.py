# backend/repositories/verification_repository.py
"""
SageCommand V3 — Continuous Verification Engine Foundation Repository (Prompt 36)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Thread-safe, tenant-isolated SQLite WAL repository for mission verification runs,
traceable verification findings, append-only verification audit ledger, and idempotency records.
Guarantees parameterized SQL queries, strict tenant and workspace boundaries,
and atomic mutations for all verification runs and audit entries.
"""

import json
import sqlite3
import threading
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone

try:
    from core.config import (
        SAGE_VERIFICATION_DB_PATH,
        SAGE_VERIFICATION_MAX_RUNS_LIST,
        SAGE_VERIFICATION_DEFAULT_RUNS_LIMIT,
    )
    from data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        VerificationAuditRecord,
        VerificationRunSummary,
        VerificationProvenance,
        TriggerType,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_VERIFICATION_DB_PATH,
        SAGE_VERIFICATION_MAX_RUNS_LIST,
        SAGE_VERIFICATION_DEFAULT_RUNS_LIMIT,
    )
    from backend.data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        VerificationAuditRecord,
        VerificationRunSummary,
        VerificationProvenance,
        TriggerType,
    )

logger = logging.getLogger("verification_repository")


class VerificationRepositoryError(Exception):
    """Base exception for verification repository operations."""
    pass


class VerificationNotFoundError(VerificationRepositoryError):
    """Raised when requested verification cannot be found within authorized scope."""
    pass


class VerificationConcurrencyError(VerificationRepositoryError):
    """Raised when concurrent modification conflict occurs."""
    pass


class VerificationIdempotencyConflictError(VerificationRepositoryError):
    """Raised when an idempotency key is reused with differing request payload."""
    pass


class VerificationRepository:
    """
    Thread-safe SQLite WAL repository for continuous verification persistence.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SAGE_VERIFICATION_DB_PATH
        self._lock = threading.RLock()
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
            CREATE TABLE IF NOT EXISTS verification_runs (
                verification_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                mission_revision INTEGER NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                plant_id TEXT NOT NULL,
                session_id TEXT,
                schema_version TEXT NOT NULL,
                verification_scope TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                rule_set_version TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                target_count INTEGER NOT NULL DEFAULT 0,
                verified_count INTEGER NOT NULL DEFAULT 0,
                unverified_count INTEGER NOT NULL DEFAULT 0,
                indeterminate_count INTEGER NOT NULL DEFAULT 0,
                blocked_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                provenance_json TEXT NOT NULL,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, verification_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_findings (
                finding_id TEXT NOT NULL,
                verification_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                mission_revision INTEGER NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                plant_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence_references_json TEXT NOT NULL,
                evidence_assessments_json TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                explanation TEXT NOT NULL,
                limitations_json TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, finding_id),
                FOREIGN KEY (tenant_id, workspace_id, verification_id)
                    REFERENCES verification_runs (tenant_id, workspace_id, verification_id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_audit_ledger (
                audit_id TEXT PRIMARY KEY,
                verification_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                mission_revision INTEGER NOT NULL,
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
                checksum TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_idempotency_records (
                idempotency_key TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                verification_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, idempotency_key)
            )
        """)

        # Indexes for scoped querying
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vruns_mission_lookup
            ON verification_runs (tenant_id, workspace_id, mission_id, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vruns_status
            ON verification_runs (tenant_id, workspace_id, status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vfindings_run_lookup
            ON verification_findings (tenant_id, workspace_id, verification_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vaudit_run_lookup
            ON verification_audit_ledger (tenant_id, workspace_id, verification_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vaudit_mission_lookup
            ON verification_audit_ledger (tenant_id, workspace_id, mission_id)
        """)
        conn.commit()

    def check_idempotency(
        self,
        tenant_id: str,
        workspace_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[str]:
        """
        Validates idempotency key under tenant and workspace scope.
        Returns existing verification_id if hash matches,
        raises VerificationIdempotencyConflictError if hash differs,
        or returns None if unused.
        """
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT verification_id, request_hash
                FROM verification_idempotency_records
                WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?
                """,
                (tenant_id, workspace_id, idempotency_key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            if row["request_hash"] != request_hash:
                raise VerificationIdempotencyConflictError(
                    f"Idempotency key '{idempotency_key}' reused with conflicting request payload."
                )
            return row["verification_id"]

    def save_run_atomic(
        self,
        run: VerificationRun,
        audit_record: Optional[VerificationAuditRecord] = None,
        idempotency_hash: Optional[str] = None,
    ) -> VerificationRun:
        """
        Persists a verification run, its findings, audit record, and optional idempotency key
        atomically inside a single database transaction.
        """
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                # 1. Idempotency record if key provided
                if run.idempotency_key and idempotency_hash:
                    cursor.execute(
                        """
                        SELECT verification_id, request_hash
                        FROM verification_idempotency_records
                        WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?
                        """,
                        (run.tenant_id, run.workspace_id, run.idempotency_key),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        if existing["request_hash"] != idempotency_hash:
                            raise VerificationIdempotencyConflictError(
                                f"Idempotency key '{run.idempotency_key}' reused with conflicting request payload."
                            )
                        # Identical replay: return existing run
                        return self.get_run(
                            run.tenant_id, run.workspace_id, run.mission_id, existing["verification_id"]
                        ) or run

                    cursor.execute(
                        """
                        INSERT INTO verification_idempotency_records (
                            idempotency_key, tenant_id, workspace_id, verification_id,
                            mission_id, request_hash, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run.idempotency_key,
                            run.tenant_id,
                            run.workspace_id,
                            run.verification_id,
                            run.mission_id,
                            idempotency_hash,
                            run.created_at,
                        ),
                    )

                # 2. Insert verification run
                cursor.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_id, mission_id, mission_revision, tenant_id, workspace_id,
                        plant_id, session_id, schema_version, verification_scope, status,
                        trigger_type, requested_by, rule_set_version, started_at, completed_at,
                        target_count, verified_count, unverified_count, indeterminate_count,
                        blocked_count, failed_count, summary, provenance_json, idempotency_key,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.verification_id,
                        run.mission_id,
                        run.mission_revision,
                        run.tenant_id,
                        run.workspace_id,
                        run.plant_id,
                        run.session_id,
                        run.schema_version,
                        run.verification_scope,
                        run.status.value,
                        run.trigger_type.value,
                        run.requested_by,
                        run.rule_set_version,
                        run.started_at,
                        run.completed_at,
                        run.target_count,
                        run.verified_count,
                        run.unverified_count,
                        run.indeterminate_count,
                        run.blocked_count,
                        run.failed_count,
                        run.summary,
                        json.dumps(run.provenance.model_dump(), separators=(",", ":")),
                        run.idempotency_key,
                        run.created_at,
                    ),
                )

                # 3. Insert findings
                for f in run.findings:
                    cursor.execute(
                        """
                        INSERT INTO verification_findings (
                            finding_id, verification_id, mission_id, mission_revision,
                            tenant_id, workspace_id, plant_id, target_type, target_id,
                            status, evidence_references_json, evidence_assessments_json,
                            rule_id, rule_version, explanation, limitations_json, evaluated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f.finding_id,
                            run.verification_id,
                            run.mission_id,
                            run.mission_revision,
                            run.tenant_id,
                            run.workspace_id,
                            run.plant_id,
                            f.target_type.value,
                            f.target_id,
                            f.status.value,
                            json.dumps(f.evidence_references, separators=(",", ":")),
                            json.dumps([ea.model_dump() for ea in f.evidence_assessments], separators=(",", ":")),
                            f.rule_id,
                            f.rule_version,
                            f.explanation,
                            json.dumps(f.limitations, separators=(",", ":")),
                            f.evaluated_at,
                        ),
                    )

                # 4. Insert audit record if provided
                if audit_record:
                    cursor.execute(
                        """
                        INSERT INTO verification_audit_ledger (
                            audit_id, verification_id, mission_id, mission_revision,
                            tenant_id, workspace_id, plant_id, event_type, result,
                            actor_id, actor_role, request_id, trace_id, details_json,
                            checksum, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            audit_record.audit_id,
                            audit_record.verification_id,
                            audit_record.mission_id,
                            audit_record.mission_revision,
                            audit_record.tenant_id,
                            audit_record.workspace_id,
                            audit_record.plant_id,
                            audit_record.event_type,
                            audit_record.result,
                            audit_record.actor_id,
                            audit_record.actor_role,
                            audit_record.request_id,
                            audit_record.trace_id,
                            json.dumps(audit_record.details, separators=(",", ":")),
                            audit_record.checksum,
                            audit_record.timestamp,
                        ),
                    )

                conn.commit()
                return run
            except sqlite3.IntegrityError as e:
                conn.rollback()
                logger.error("SQLite integrity error saving verification run: %s", e)
                raise VerificationConcurrencyError(f"Persistence error for verification run: {e}") from e
            except Exception:
                conn.rollback()
                raise

    def get_run(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
        verification_id: str,
    ) -> Optional[VerificationRun]:
        """
        Retrieves a verification run by ID scoped to tenant, workspace, and mission.
        Returns None if not found or unauthorized.
        """
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM verification_runs
                WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ? AND verification_id = ?
                """,
                (tenant_id, workspace_id, mission_id, verification_id),
            )
            row = cursor.fetchone()
            if not row:
                return None

            findings = self.get_findings(tenant_id, workspace_id, mission_id, verification_id)
            prov_data = json.loads(row["provenance_json"])

            return VerificationRun(
                verification_id=row["verification_id"],
                schema_version=row["schema_version"],
                mission_id=row["mission_id"],
                mission_revision=row["mission_revision"],
                verification_scope=row["verification_scope"],
                status=VerificationStatus(row["status"]),
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                requested_by=row["requested_by"],
                tenant_id=row["tenant_id"],
                workspace_id=row["workspace_id"],
                plant_id=row["plant_id"],
                session_id=row["session_id"],
                trigger_type=TriggerType(row["trigger_type"]),
                rule_set_version=row["rule_set_version"],
                summary=row["summary"],
                target_count=row["target_count"],
                verified_count=row["verified_count"],
                unverified_count=row["unverified_count"],
                indeterminate_count=row["indeterminate_count"],
                blocked_count=row["blocked_count"],
                failed_count=row["failed_count"],
                findings=findings,
                provenance=VerificationProvenance.model_validate(prov_data),
                idempotency_key=row["idempotency_key"],
                created_at=row["created_at"],
            )

    def list_runs(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
        limit: int = 20,
        offset: int = 0,
        plant_id: Optional[str] = None,
    ) -> Tuple[List[VerificationRunSummary], int]:
        """
        Lists summaries of verification runs scoped to tenant, workspace, and mission.
        """
        safe_limit = min(max(1, limit), SAGE_VERIFICATION_MAX_RUNS_LIST)
        safe_offset = max(0, offset)

        query = """
            SELECT verification_id, mission_id, mission_revision, verification_scope,
                   status, trigger_type, started_at, completed_at, target_count,
                   verified_count, unverified_count, indeterminate_count, blocked_count,
                   failed_count, summary
            FROM verification_runs
            WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ?
        """
        params: List[Any] = [tenant_id, workspace_id, mission_id]

        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)

        count_query = f"SELECT COUNT(*) as total FROM ({query})"
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        exec_params = list(params)
        exec_params.extend([safe_limit, safe_offset])

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(count_query, params)
            count_row = cursor.fetchone()
            total = count_row["total"] if count_row else 0

            cursor.execute(query, exec_params)
            rows = cursor.fetchall()

            summaries: List[VerificationRunSummary] = []
            for r in rows:
                summaries.append(
                    VerificationRunSummary(
                        verification_id=r["verification_id"],
                        mission_id=r["mission_id"],
                        mission_revision=r["mission_revision"],
                        verification_scope=r["verification_scope"],
                        status=VerificationStatus(r["status"]),
                        trigger_type=TriggerType(r["trigger_type"]),
                        started_at=r["started_at"],
                        completed_at=r["completed_at"],
                        target_count=r["target_count"],
                        verified_count=r["verified_count"],
                        unverified_count=r["unverified_count"],
                        indeterminate_count=r["indeterminate_count"],
                        blocked_count=r["blocked_count"],
                        failed_count=r["failed_count"],
                        summary=r["summary"],
                    )
                )
            return summaries, total

    def get_findings(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
        verification_id: str,
    ) -> List[VerificationFinding]:
        """
        Retrieves all findings for a verification run, enforcing strict tenant and workspace isolation.
        """
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM verification_findings
                WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ? AND verification_id = ?
                ORDER BY finding_id ASC
                """,
                (tenant_id, workspace_id, mission_id, verification_id),
            )
            rows = cursor.fetchall()
            findings: List[VerificationFinding] = []
            for r in rows:
                ev_refs = json.loads(r["evidence_references_json"])
                ev_assessments = json.loads(r["evidence_assessments_json"])
                limitations = json.loads(r["limitations_json"])

                findings.append(
                    VerificationFinding(
                        finding_id=r["finding_id"],
                        target_type=VerificationTargetType(r["target_type"]),
                        target_id=r["target_id"],
                        status=VerificationStatus(r["status"]),
                        evidence_references=ev_refs,
                        evidence_assessments=ev_assessments,
                        rule_id=r["rule_id"],
                        rule_version=r["rule_version"],
                        explanation=r["explanation"],
                        limitations=limitations,
                        evaluated_at=r["evaluated_at"],
                    )
                )
            return findings

    def cancel_run_atomic(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
        verification_id: str,
        cancelled_by: str,
        reason: str,
        audit_record: VerificationAuditRecord,
    ) -> Optional[VerificationRun]:
        """
        Transitions a verification run to CANCELLED atomically, recording completion timestamp
        and appending an audit record.
        """
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status FROM verification_runs
                WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ? AND verification_id = ?
                """,
                (tenant_id, workspace_id, mission_id, verification_id),
            )
            row = cursor.fetchone()
            if not row:
                return None

            curr_status = row["status"]
            if curr_status in (VerificationStatus.VERIFIED.value, VerificationStatus.FAILED.value, VerificationStatus.CANCELLED.value):
                # Terminal status cannot be cancelled
                raise VerificationRepositoryError(f"Verification run '{verification_id}' is in terminal state '{curr_status}' and cannot be cancelled.")

            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                UPDATE verification_runs
                SET status = ?, completed_at = ?, summary = ?
                WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ? AND verification_id = ?
                """,
                (
                    VerificationStatus.CANCELLED.value,
                    now_iso,
                    f"Cancelled by {cancelled_by}: {reason}",
                    tenant_id,
                    workspace_id,
                    mission_id,
                    verification_id,
                ),
            )

            cursor.execute(
                """
                INSERT INTO verification_audit_ledger (
                    audit_id, verification_id, mission_id, mission_revision,
                    tenant_id, workspace_id, plant_id, event_type, result,
                    actor_id, actor_role, request_id, trace_id, details_json,
                    checksum, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_record.audit_id,
                    audit_record.verification_id,
                    audit_record.mission_id,
                    audit_record.mission_revision,
                    audit_record.tenant_id,
                    audit_record.workspace_id,
                    audit_record.plant_id,
                    audit_record.event_type,
                    audit_record.result,
                    audit_record.actor_id,
                    audit_record.actor_role,
                    audit_record.request_id,
                    audit_record.trace_id,
                    json.dumps(audit_record.details, separators=(",", ":")),
                    audit_record.checksum,
                    audit_record.timestamp,
                ),
            )

            conn.commit()

        return self.get_run(tenant_id, workspace_id, mission_id, verification_id)

    def get_audit_records(
        self,
        tenant_id: str,
        workspace_id: str,
        mission_id: str,
        verification_id: Optional[str] = None,
    ) -> List[VerificationAuditRecord]:
        """
        Retrieves audit trail entries for a mission or specific verification run.
        """
        query = """
            SELECT * FROM verification_audit_ledger
            WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ?
        """
        params: List[Any] = [tenant_id, workspace_id, mission_id]
        if verification_id:
            query += " AND verification_id = ?"
            params.append(verification_id)
        query += " ORDER BY timestamp ASC"

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            records: List[VerificationAuditRecord] = []
            for r in rows:
                details = json.loads(r["details_json"]) if r["details_json"] else {}
                records.append(
                    VerificationAuditRecord(
                        audit_id=r["audit_id"],
                        verification_id=r["verification_id"],
                        mission_id=r["mission_id"],
                        mission_revision=r["mission_revision"],
                        tenant_id=r["tenant_id"],
                        workspace_id=r["workspace_id"],
                        plant_id=r["plant_id"],
                        event_type=r["event_type"],
                        result=r["result"],
                        actor_id=r["actor_id"],
                        actor_role=r["actor_role"],
                        request_id=r["request_id"],
                        trace_id=r["trace_id"],
                        details=details,
                        checksum=r["checksum"],
                        timestamp=r["timestamp"],
                    )
                )
            return records


# Canonical singleton repository instance
verification_repository = VerificationRepository()
