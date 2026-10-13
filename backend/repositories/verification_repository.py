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
import uuid
from collections import defaultdict
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
        compute_diagnostic_run_fields,
    )
    from data.schemas.closed_loop_contract import (
        VerificationFeedbackRecord,
        EligibilityStatus,
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
        compute_diagnostic_run_fields,
    )
    from backend.data.schemas.closed_loop_contract import (
        VerificationFeedbackRecord,
        EligibilityStatus,
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
                is_diagnostic INTEGER NOT NULL DEFAULT 0,
                diagnostic_status TEXT,
                diagnostic_outcome TEXT,
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

        # Feedback Records (Closed-Loop Learning foundation - Prompt 37)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_feedback_records (
                feedback_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                plant_id TEXT NOT NULL,
                trigger_event_id TEXT NOT NULL,
                trigger_event_fingerprint TEXT NOT NULL,
                eligibility_status TEXT NOT NULL,
                eligibility_reason TEXT NOT NULL,
                mission_id TEXT,
                mission_revision INTEGER,
                verification_id TEXT,
                verification_status TEXT,
                is_diagnostic INTEGER NOT NULL DEFAULT 0,
                diagnostic_status TEXT,
                diagnostic_outcome TEXT,
                feedback_event_id TEXT,
                feedback_event_fingerprint TEXT,
                idempotency_key TEXT,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, feedback_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vfb_mission_lookup
            ON verification_feedback_records (tenant_id, workspace_id, mission_id, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vfb_event
            ON verification_feedback_records (tenant_id, trigger_event_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vfb_run
            ON verification_feedback_records (tenant_id, verification_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vfb_idem
            ON verification_feedback_records (tenant_id, workspace_id, idempotency_key)
        """)

        # Backward compatibility migration for existing SQLite schemas
        for col_name, col_type in [
            ("is_diagnostic", "INTEGER NOT NULL DEFAULT 0"),
            ("diagnostic_status", "TEXT"),
            ("diagnostic_outcome", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE verification_runs ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Prompt 36F: Non-destructive, idempotent migration of legacy diagnostic runs
        self._migrate_legacy_diagnostic_runs(conn)

        conn.commit()

    def _migrate_legacy_diagnostic_runs(self, conn: sqlite3.Connection) -> int:
        """
        Prompt 36F — Legacy Diagnostic Run Migration:
        Identifies historical diagnostic verification runs created prior to Prompt 36E
        and normalizes their machine-readable status contract:
        - Sets is_diagnostic = 1
        - Normalizes run-level status = NOT_VERIFIED if previously VERIFIED
        - Populates diagnostic_status and diagnostic_outcome deterministically from finding statuses
        - Preserves finding-level statuses and actual rule_id ('RULE_EVIDENCE_EXISTS_V1')
        - Appends an audit ledger event in verification_audit_ledger idempotently
        - Preserves authoritative verification runs untouched
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tenant_id, workspace_id, plant_id, mission_id, mission_revision,
                   verification_id, status, summary, target_count, verified_count,
                   is_diagnostic, diagnostic_status, diagnostic_outcome, provenance_json
            FROM verification_runs
        """)
        runs = cursor.fetchall()
        corrected_count = 0

        authoritative_rules = {
            "RULE_EVIDENCE_VALIDATED_V1",
            "RULE_EVIDENCE_FRESH_V1",
            "RULE_REQUIRED_EVIDENCE_PRESENT_V1",
            "RULE_REQUIRED_EVIDENCE_VALIDATED_V1",
            "RULE_EVIDENCE_SCOPE_MATCH_V1",
            "RULE_REQUIRED_FIELDS_PRESENT_V1",
            "RULE_SOURCE_CONSISTENCY_V1",
        }

        for r in runs:
            v_id = r["verification_id"]
            t_id = r["tenant_id"]
            w_id = r["workspace_id"]
            p_id = r["plant_id"]
            m_id = r["mission_id"]
            m_rev = r["mission_revision"]
            curr_status = r["status"]
            curr_summary = r["summary"] or ""
            target_count = r["target_count"]
            curr_is_diag = bool(r["is_diagnostic"]) if r["is_diagnostic"] is not None else False
            curr_diag_status = r["diagnostic_status"]
            curr_diag_outcome = r["diagnostic_outcome"]

            # If the run is already marked diagnostic and complies with the safety contract
            # (status is not VERIFIED, diagnostic_status and outcome are populated), skip it idempotently.
            if (
                curr_is_diag
                and curr_status != VerificationStatus.VERIFIED.value
                and curr_diag_status is not None
                and curr_diag_outcome is not None
            ):
                continue

            cursor.execute("""
                SELECT rule_id, status
                FROM verification_findings
                WHERE tenant_id = ? AND workspace_id = ? AND verification_id = ?
            """, (t_id, w_id, v_id))
            findings_rows = cursor.fetchall()

            rule_ids = set(fr["rule_id"] for fr in findings_rows if fr["rule_id"])
            finding_statuses = [VerificationStatus(fr["status"]) for fr in findings_rows if fr["status"]]

            is_diag = False
            is_ambiguous = False

            if "RULE_EVIDENCE_EXISTS_V1" in rule_ids:
                is_diag = True
                if len(rule_ids) > 1:
                    is_ambiguous = True
            elif not findings_rows:
                if "DIAGNOSTIC ONLY" in curr_summary or "EVIDENCE_EXISTS" in curr_summary:
                    is_diag = True
                    is_ambiguous = True
                elif curr_status == VerificationStatus.VERIFIED.value:
                    # Ambiguous legacy run: claimed VERIFIED without findings
                    is_diag = True
                    is_ambiguous = True
            else:
                if rule_ids.issubset(authoritative_rules):
                    is_diag = False
                else:
                    if curr_status == VerificationStatus.VERIFIED.value:
                        is_diag = True
                        is_ambiguous = True

            if not is_diag:
                continue

            if is_ambiguous and not finding_statuses:
                new_run_status = VerificationStatus.NOT_VERIFIED
                new_diag_status = VerificationStatus.INDETERMINATE
                new_diag_outcome = "AMBIGUOUS_NO_FINDINGS"
            elif is_ambiguous and "RULE_EVIDENCE_EXISTS_V1" in rule_ids:
                new_run_status = VerificationStatus.NOT_VERIFIED
                new_diag_status = VerificationStatus.INDETERMINATE
                new_diag_outcome = "INCONSISTENT_RULES"
            elif is_ambiguous:
                new_run_status = VerificationStatus.NOT_VERIFIED
                new_diag_status = VerificationStatus.INDETERMINATE
                new_diag_outcome = "UNRECOGNIZED_RULES"
            else:
                run_st, diag_st, diag_out = compute_diagnostic_run_fields(finding_statuses, target_count)
                new_run_status = run_st
                new_diag_status = diag_st
                new_diag_outcome = diag_out

            needs_update = (
                not curr_is_diag
                or curr_status != new_run_status.value
                or curr_diag_status != new_diag_status.value
                or curr_diag_outcome != new_diag_outcome
            )

            if needs_update:
                updated_summary = curr_summary
                if "DIAGNOSTIC ONLY" not in updated_summary:
                    if updated_summary:
                        updated_summary += " | DIAGNOSTIC ONLY: Evidence existence check does not certify authoritative mission completion."
                    else:
                        updated_summary = "DIAGNOSTIC ONLY: Evidence existence check does not certify authoritative mission completion."

                updated_prov_json = r["provenance_json"]
                try:
                    prov_dict = json.loads(updated_prov_json)
                    prov_limits = prov_dict.get("limitations", [])
                    diag_caveat = "Diagnostic evaluation only (EVIDENCE_EXISTS): does not certify authoritative mission completion, freshness, or multi-source consistency."
                    if not any("Diagnostic evaluation only" in lim for lim in prov_limits):
                        prov_limits.append(diag_caveat)
                        prov_dict["limitations"] = prov_limits[:30]
                        updated_prov_json = json.dumps(prov_dict, separators=(",", ":"))
                except Exception:
                    pass

                cursor.execute("""
                    UPDATE verification_runs
                    SET is_diagnostic = 1,
                        status = ?,
                        diagnostic_status = ?,
                        diagnostic_outcome = ?,
                        summary = ?,
                        provenance_json = ?
                    WHERE tenant_id = ? AND workspace_id = ? AND verification_id = ?
                """, (
                    new_run_status.value,
                    new_diag_status.value,
                    new_diag_outcome,
                    updated_summary,
                    updated_prov_json,
                    t_id, w_id, v_id
                ))

                cursor.execute("""
                    SELECT audit_id FROM verification_audit_ledger
                    WHERE tenant_id = ? AND workspace_id = ? AND verification_id = ?
                      AND event_type = 'MIGRATION_DIAGNOSTIC_STATUS_CORRECTION'
                """, (t_id, w_id, v_id))
                existing_audit = cursor.fetchone()

                if not existing_audit:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    audit_rec = VerificationAuditRecord(
                        audit_id=f"vfaud_mig_{uuid.uuid4().hex[:12]}",
                        verification_id=v_id,
                        mission_id=m_id,
                        mission_revision=m_rev,
                        tenant_id=t_id,
                        workspace_id=w_id,
                        plant_id=p_id,
                        event_type="MIGRATION_DIAGNOSTIC_STATUS_CORRECTION",
                        result="NORMALIZED",
                        actor_id="system_migration_p36f",
                        actor_role="SYSTEM_MIGRATION",
                        request_id=None,
                        trace_id=None,
                        details={
                            "previous_status": curr_status,
                            "new_status": new_run_status.value,
                            "is_diagnostic": True,
                            "diagnostic_status": new_diag_status.value,
                            "diagnostic_outcome": new_diag_outcome,
                            "reason": "Prompt 36F legacy diagnostic status normalization",
                        },
                        timestamp=now_iso,
                    )
                    cursor.execute("""
                        INSERT INTO verification_audit_ledger (
                            audit_id, verification_id, mission_id, mission_revision,
                            tenant_id, workspace_id, plant_id, event_type, result,
                            actor_id, actor_role, request_id, trace_id, details_json,
                            checksum, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        audit_rec.audit_id,
                        audit_rec.verification_id,
                        audit_rec.mission_id,
                        audit_rec.mission_revision,
                        audit_rec.tenant_id,
                        audit_rec.workspace_id,
                        audit_rec.plant_id,
                        audit_rec.event_type,
                        audit_rec.result,
                        audit_rec.actor_id,
                        audit_rec.actor_role,
                        audit_rec.request_id,
                        audit_rec.trace_id,
                        json.dumps(audit_rec.details, separators=(",", ":")),
                        audit_rec.checksum,
                        audit_rec.timestamp,
                    ))

                corrected_count += 1

        return corrected_count

    def migrate_legacy_diagnostic_runs(self) -> int:
        """
        Public method to idempotently trigger legacy diagnostic runs migration.
        Returns the number of runs updated.
        """
        with self._lock, self._get_connection() as conn:
            count = self._migrate_legacy_diagnostic_runs(conn)
            conn.commit()
            return count

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
                        blocked_count, failed_count, summary, is_diagnostic, diagnostic_status,
                        diagnostic_outcome, provenance_json, idempotency_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        1 if run.is_diagnostic else 0,
                        run.diagnostic_status.value if run.diagnostic_status else None,
                        run.diagnostic_outcome,
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

    @staticmethod
    def _normalize_diagnostic_run_fields(
        is_diagnostic: bool,
        status: VerificationStatus,
        diagnostic_status: Optional[VerificationStatus],
        diagnostic_outcome: Optional[str],
        finding_statuses: List[VerificationStatus],
        finding_rules: Set[str],
        summary: str,
        target_count: int,
    ) -> Tuple[bool, VerificationStatus, Optional[VerificationStatus], Optional[str]]:
        """
        Prompt 36H — Findings-Driven Diagnostic Reconciliation & Fail-Closed Read Integrity:
        For every diagnostic verification run, the authoritative diagnostic result is derived
        deterministically from actual persisted findings. Existing summary metadata or stored
        fields MUST NEVER override contradictory findings.

        1. Determine diagnostic classification:
           - is_diagnostic flag is True
           - OR findings evaluate RULE_EVIDENCE_EXISTS_V1
           - OR summary carries diagnostic markers ('DIAGNOSTIC ONLY' or 'EVIDENCE_EXISTS')
           - OR stored diagnostic_status or diagnostic_outcome is present
        2. Non-diagnostic (authoritative) runs:
           - Preserves status (including VERIFIED)
           - Keeps diagnostic fields None
        3. Diagnostic runs:
           - Zero findings: fails closed to (NOT_VERIFIED, INDETERMINATE, 'NO_TARGETS' if target_count == 0 else 'AMBIGUOUS_NO_FINDINGS')
           - Mixed or unrecognized rule sets (e.g. RULE_EVIDENCE_EXISTS_V1 mixed with authoritative rules):
             fails closed to (NOT_VERIFIED, INDETERMINATE, 'INCONSISTENT_RULES')
           - Consistent diagnostic evaluation (only RULE_EVIDENCE_EXISTS_V1):
             recomputes via compute_diagnostic_run_fields(finding_statuses, target_count)
           - Permanent invariant: diagnostic run-level status can NEVER be VERIFIED.
        """
        is_diag = is_diagnostic
        # A legacy run is diagnostic if its findings use diagnostic rules or its summary has diagnostic markers
        # or it carries diagnostic metadata
        if not is_diag:
            if (
                "RULE_EVIDENCE_EXISTS_V1" in finding_rules
                or "DIAGNOSTIC ONLY" in summary
                or "EVIDENCE_EXISTS" in summary
                or diagnostic_status is not None
                or diagnostic_outcome is not None
            ):
                is_diag = True

        if not is_diag:
            return False, status, None, None

        # Identified diagnostic run: ALWAYS reconcile against persisted findings.
        # Stored diagnostic_status or diagnostic_outcome must NEVER override actual findings.
        if not finding_statuses:
            run_st, diag_st, diag_out = compute_diagnostic_run_fields([], target_count)
            return True, run_st, diag_st, diag_out

        # Mixed or unrecognized rule sets fail closed as ambiguous/inconsistent
        if finding_rules != {"RULE_EVIDENCE_EXISTS_V1"}:
            return True, VerificationStatus.NOT_VERIFIED, VerificationStatus.INDETERMINATE, "INCONSISTENT_RULES"

        # Canonical diagnostic aggregation for consistent diagnostic evaluation
        run_st, diag_st, diag_out = compute_diagnostic_run_fields(finding_statuses, target_count)
        if run_st == VerificationStatus.VERIFIED:
            run_st = VerificationStatus.NOT_VERIFIED
        return True, run_st, diag_st, diag_out

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

            finding_statuses = [f.status for f in findings]
            finding_rules = {f.rule_id for f in findings}
            diag_stat_raw = row["diagnostic_status"] if "diagnostic_status" in row.keys() else None
            diag_stat = VerificationStatus(diag_stat_raw) if diag_stat_raw else None
            diag_out = row["diagnostic_outcome"] if "diagnostic_outcome" in row.keys() else None
            status_val = VerificationStatus(row["status"])
            summary_val = row["summary"] or ""
            is_diag_raw = bool(row["is_diagnostic"]) if "is_diagnostic" in row.keys() and row["is_diagnostic"] is not None else False

            is_diag, status_val, diag_stat, diag_out = self._normalize_diagnostic_run_fields(
                is_diagnostic=is_diag_raw,
                status=status_val,
                diagnostic_status=diag_stat,
                diagnostic_outcome=diag_out,
                finding_statuses=finding_statuses,
                finding_rules=finding_rules,
                summary=summary_val,
                target_count=row["target_count"],
            )

            return VerificationRun(
                verification_id=row["verification_id"],
                schema_version=row["schema_version"],
                mission_id=row["mission_id"],
                mission_revision=row["mission_revision"],
                verification_scope=row["verification_scope"],
                status=status_val,
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
                is_diagnostic=is_diag,
                diagnostic_status=diag_stat,
                diagnostic_outcome=diag_out,
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
                   failed_count, summary, is_diagnostic, diagnostic_status, diagnostic_outcome
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

            # Batch retrieve findings scoped to tenant, workspace, and returned verification IDs
            v_ids = [r["verification_id"] for r in rows]
            findings_by_vid: Dict[str, List[sqlite3.Row]] = defaultdict(list)
            if v_ids:
                placeholders = ",".join("?" for _ in v_ids)
                cursor.execute(f"""
                    SELECT verification_id, rule_id, status
                    FROM verification_findings
                    WHERE tenant_id = ? AND workspace_id = ? AND mission_id = ? AND verification_id IN ({placeholders})
                    ORDER BY finding_id ASC
                """, [tenant_id, workspace_id, mission_id, *v_ids])
                for fr in cursor.fetchall():
                    findings_by_vid[fr["verification_id"]].append(fr)

            summaries: List[VerificationRunSummary] = []
            for r in rows:
                v_findings = findings_by_vid.get(r["verification_id"], [])
                finding_statuses = [VerificationStatus(fr["status"]) for fr in v_findings if fr["status"]]
                finding_rules = {fr["rule_id"] for fr in v_findings if fr["rule_id"]}

                diag_stat_raw = r["diagnostic_status"] if "diagnostic_status" in r.keys() else None
                diag_stat = VerificationStatus(diag_stat_raw) if diag_stat_raw else None
                diag_out = r["diagnostic_outcome"] if "diagnostic_outcome" in r.keys() else None
                status_val = VerificationStatus(r["status"])
                summary_val = r["summary"] or ""
                is_diag_raw = bool(r["is_diagnostic"]) if "is_diagnostic" in r.keys() and r["is_diagnostic"] is not None else False

                is_diag, status_val, diag_stat, diag_out = self._normalize_diagnostic_run_fields(
                    is_diagnostic=is_diag_raw,
                    status=status_val,
                    diagnostic_status=diag_stat,
                    diagnostic_outcome=diag_out,
                    finding_statuses=finding_statuses,
                    finding_rules=finding_rules,
                    summary=summary_val,
                    target_count=r["target_count"],
                )

                summaries.append(
                    VerificationRunSummary(
                        verification_id=r["verification_id"],
                        mission_id=r["mission_id"],
                        mission_revision=r["mission_revision"],
                        verification_scope=r["verification_scope"],
                        status=status_val,
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
                        is_diagnostic=is_diag,
                        diagnostic_status=diag_stat,
                        diagnostic_outcome=diag_out,
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

    # -------------------------------------------------------------------------
    # Closed-Loop Feedback Records (Prompt 37)
    # -------------------------------------------------------------------------

    def _row_to_feedback_record(self, r: sqlite3.Row) -> VerificationFeedbackRecord:
        details = json.loads(r["details_json"]) if r["details_json"] else {}
        return VerificationFeedbackRecord(
            feedback_id=r["feedback_id"],
            tenant_id=r["tenant_id"],
            workspace_id=r["workspace_id"],
            plant_id=r["plant_id"],
            trigger_event_id=r["trigger_event_id"],
            trigger_event_fingerprint=r["trigger_event_fingerprint"],
            eligibility_status=EligibilityStatus(r["eligibility_status"]),
            eligibility_reason=r["eligibility_reason"],
            mission_id=r["mission_id"],
            mission_revision=r["mission_revision"],
            verification_id=r["verification_id"],
            verification_status=r["verification_status"],
            is_diagnostic=bool(r["is_diagnostic"]),
            diagnostic_status=r["diagnostic_status"],
            diagnostic_outcome=r["diagnostic_outcome"],
            feedback_event_id=r["feedback_event_id"],
            feedback_event_fingerprint=r["feedback_event_fingerprint"],
            idempotency_key=r["idempotency_key"],
            details=details,
            created_at=r["created_at"],
        )

    def save_feedback_record(self, record: VerificationFeedbackRecord) -> VerificationFeedbackRecord:
        """
        Persists a closed-loop verification feedback record within tenant & workspace boundaries.
        Thread-safe, atomic SQLite WAL operation.
        """
        sql = """
            INSERT INTO verification_feedback_records (
                feedback_id, tenant_id, workspace_id, plant_id,
                trigger_event_id, trigger_event_fingerprint,
                eligibility_status, eligibility_reason,
                mission_id, mission_revision,
                verification_id, verification_status,
                is_diagnostic, diagnostic_status, diagnostic_outcome,
                feedback_event_id, feedback_event_fingerprint,
                idempotency_key, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, workspace_id, feedback_id) DO UPDATE SET
                eligibility_status = excluded.eligibility_status,
                eligibility_reason = excluded.eligibility_reason,
                verification_id = excluded.verification_id,
                verification_status = excluded.verification_status,
                is_diagnostic = excluded.is_diagnostic,
                diagnostic_status = excluded.diagnostic_status,
                diagnostic_outcome = excluded.diagnostic_outcome,
                feedback_event_id = excluded.feedback_event_id,
                feedback_event_fingerprint = excluded.feedback_event_fingerprint,
                details_json = excluded.details_json
        """
        params = (
            record.feedback_id,
            record.tenant_id,
            record.workspace_id,
            record.plant_id,
            record.trigger_event_id,
            record.trigger_event_fingerprint,
            record.eligibility_status.value if hasattr(record.eligibility_status, "value") else str(record.eligibility_status),
            record.eligibility_reason,
            record.mission_id,
            record.mission_revision,
            record.verification_id,
            record.verification_status,
            1 if record.is_diagnostic else 0,
            record.diagnostic_status,
            record.diagnostic_outcome,
            record.feedback_event_id,
            record.feedback_event_fingerprint,
            record.idempotency_key,
            json.dumps(record.details),
            record.created_at,
        )
        with self._lock, self._get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
        return record

    def get_feedback_record(
        self, tenant_id: str, workspace_id: str, feedback_id: str
    ) -> Optional[VerificationFeedbackRecord]:
        """Retrieves a single feedback record scoped strictly to tenant and workspace."""
        query = """
            SELECT * FROM verification_feedback_records
            WHERE tenant_id = ? AND workspace_id = ? AND feedback_id = ?
        """
        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, (tenant_id, workspace_id, feedback_id)).fetchone()
            if not row:
                return None
            return self._row_to_feedback_record(row)

    def list_feedback_records(
        self, tenant_id: str, workspace_id: str, mission_id: Optional[str] = None, limit: int = 50
    ) -> List[VerificationFeedbackRecord]:
        """Lists feedback records scoped strictly to tenant and workspace."""
        query = """
            SELECT * FROM verification_feedback_records
            WHERE tenant_id = ? AND workspace_id = ?
        """
        params: List[Any] = [tenant_id, workspace_id]
        if mission_id:
            query += " AND mission_id = ?"
            params.append(mission_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(max(1, limit), 200))

        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_feedback_record(r) for r in rows]

    def get_feedback_by_trigger_event(
        self, tenant_id: str, trigger_event_id: str
    ) -> Optional[VerificationFeedbackRecord]:
        """Retrieves feedback record for a given trigger event within tenant boundary."""
        query = """
            SELECT * FROM verification_feedback_records
            WHERE tenant_id = ? AND trigger_event_id = ?
            ORDER BY created_at DESC LIMIT 1
        """
        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, (tenant_id, trigger_event_id)).fetchone()
            if not row:
                return None
            return self._row_to_feedback_record(row)

    def check_feedback_idempotency(
        self, tenant_id: str, workspace_id: str, idempotency_key: str
    ) -> Optional[VerificationFeedbackRecord]:
        """Finds existing feedback record for a deterministic idempotency key."""
        if not idempotency_key:
            return None
        query = """
            SELECT * FROM verification_feedback_records
            WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?
            LIMIT 1
        """
        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, (tenant_id, workspace_id, idempotency_key)).fetchone()
            if not row:
                return None
            return self._row_to_feedback_record(row)


# Canonical singleton repository instance
verification_repository = VerificationRepository()
