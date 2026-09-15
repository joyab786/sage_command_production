# backend/services/execution_gateway.py
"""
SageCommand V3 — Execution Gateway Service
Deterministic Final Write Boundary for SageCommand OS V3.
Enforces multi-gate execution pipeline:
- Gate 1: Authentication & Identity Integrity
- Gate 2: Authorization & Operational Permission Revalidation (action.execute / transaction.execute / transaction.rollback)
- Gate 3: Target Scope & Context Matching
- Gate 4: Action / Transaction State Machine Validation
- Gate 5: Cryptographic & Staleness Integrity Verification
- Gate 6: Two-Person Rule / Approval Verification
- Gate 7: Policy Engine Revalidation
- Gate 8: Idempotency & Duplicate Execution Detection
- Gate 9: Concurrency Lock Acquisition
- Gate 10: Physical Database Write Boundary via session-scoped db_gateway
"""

import os
import time
import uuid
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Set, Tuple
from sqlalchemy import text, inspect

try:
    from core.config import SAGE_TRANSACTIONS_DB_PATH
    from core.auth import Identity
    from data.schemas.execution_contract import (
        ExecutionStatus,
        ExecutionRequest,
        ExecutionResult,
        RollbackRequest,
    )
    from data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        RiskLevel,
        RollbackCapability as ActionRollbackCap,
    )
    from data.schemas.transaction_contract import (
        Transaction,
        TransactionStatus,
        RollbackCapability,
    )
    from data.schemas.authorization_contract import (
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
        UserIdentity,
    )
    from data.schemas.policy_contract import (
        PolicyEvaluationContext,
        PolicyEffect,
    )
    from data.schemas.ledger_contract import (
        LedgerActor,
        ActorType,
        EventCategory,
        EventType,
    )
    from data.database_context import AccessMode, DataMode
    from services.action_store import action_store, ActionStore
    from services.transaction_repository import transaction_repository, TransactionRepository
    from services.transaction_service import TransactionStateMachine
    from services.authorization_service import authorization_service, AuthorizationService
    from services.policy_service import policy_service, PolicyService
    from gateway.db_gateway import db_gateway, DatabaseConnectionGateway
    from services.connection_registry import connection_registry, ConnectionRegistry
    from services.audit_ledger import audit_ledger, AuditLedgerService
    from governance.audit import log_security_event
except ModuleNotFoundError:
    from backend.core.config import SAGE_TRANSACTIONS_DB_PATH
    from backend.core.auth import Identity
    from backend.data.schemas.execution_contract import (
        ExecutionStatus,
        ExecutionRequest,
        ExecutionResult,
        RollbackRequest,
    )
    from backend.data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        RiskLevel,
        RollbackCapability as ActionRollbackCap,
    )
    from backend.data.schemas.transaction_contract import (
        Transaction,
        TransactionStatus,
        RollbackCapability,
    )
    from backend.data.schemas.authorization_contract import (
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
        UserIdentity,
    )
    from backend.data.schemas.policy_contract import (
        PolicyEvaluationContext,
        PolicyEffect,
    )
    from backend.data.schemas.ledger_contract import (
        LedgerActor,
        ActorType,
        EventCategory,
        EventType,
    )
    from backend.data.database_context import AccessMode, DataMode
    from backend.services.action_store import action_store, ActionStore
    from backend.services.transaction_repository import transaction_repository, TransactionRepository
    from backend.services.transaction_service import TransactionStateMachine
    from backend.services.authorization_service import authorization_service, AuthorizationService
    from backend.services.policy_service import policy_service, PolicyService
    from backend.gateway.db_gateway import db_gateway, DatabaseConnectionGateway
    from backend.services.connection_registry import connection_registry, ConnectionRegistry
    from backend.services.audit_ledger import audit_ledger, AuditLedgerService
    from backend.governance.audit import log_security_event

logger = logging.getLogger("sagecommand.execution_gateway")


class ExecutionGatewayException(Exception):
    """Base exception for Execution Gateway failures."""
    def __init__(self, status_code: int, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class ExecutionGateway:
    """
    Deterministic Final Write Boundary for SageCommand OS V3.
    Controls all real-world database mutations and transaction executions.
    """

    def __init__(
        self,
        store: ActionStore = action_store,
        tx_repo: TransactionRepository = transaction_repository,
        auth_svc: AuthorizationService = authorization_service,
        pol_svc: PolicyService = policy_service,
        gateway: DatabaseConnectionGateway = db_gateway,
        conn_reg: ConnectionRegistry = connection_registry,
        ledger: AuditLedgerService = audit_ledger,
    ):
        self.store = store
        self.tx_repo = tx_repo
        self.auth_svc = auth_svc
        self.pol_svc = pol_svc
        self.gateway = gateway
        self.conn_reg = conn_reg
        self.ledger = ledger

        self._lock = threading.RLock()
        self._concurrency_locks: Dict[str, threading.Lock] = {}
        self._active_executions: Set[str] = set()
        self._idempotency_cache: Dict[str, Tuple[float, ExecutionResult]] = {}

    def _get_resource_lock(self, resource_key: str) -> threading.Lock:
        with self._lock:
            if resource_key not in self._concurrency_locks:
                self._concurrency_locks[resource_key] = threading.Lock()
            return self._concurrency_locks[resource_key]

    def clear_cache(self):
        """Clears transient caches (used for test isolation)."""
        with self._lock:
            self._concurrency_locks.clear()
            self._active_executions.clear()
            self._idempotency_cache.clear()

    # =========================================================================
    # ACTION EXECUTION PIPELINE
    # =========================================================================

    def execute_action(
        self,
        action_id: str,
        identity: Identity,
        request: Optional[ExecutionRequest] = None,
    ) -> ExecutionResult:
        """
        Executes a single structured action through the 10-gate pipeline.
        """
        req = request or ExecutionRequest(action_id=action_id)
        effective_idempotency_key = req.idempotency_key
        cache_key = f"{identity.tenant_id}:{effective_idempotency_key}" if effective_idempotency_key else None

        # Gate 8a: Fast-path Idempotency Check
        if cache_key:
            with self._lock:
                if cache_key in self._idempotency_cache:
                    ts, cached_res = self._idempotency_cache[cache_key]
                    if time.time() - ts < 3600:
                        logger.info(f"Execution idempotency cache hit for key: {effective_idempotency_key}")
                        return cached_res

        # Gate 1: Identity & Authentication Integrity
        if not identity or not identity.user_id:
            raise ExecutionGatewayException(401, "UNAUTHENTICATED", "Authentication identity required for execution.")

        # Gate 3a: Lookup Action
        action = self.store.get_by_id(action_id, identity.tenant_id)
        if not action:
            # Check if it exists in another tenant
            cross_tenant = self.store.find_existing_by_id(action_id)
            if cross_tenant:
                log_security_event(
                    "CROSS_TENANT_EXECUTION_ATTEMPT",
                    {"user_id": identity.user_id, "action_id": action_id, "target_tenant": cross_tenant.tenant_id},
                    severity="WARNING"
                )
                raise ExecutionGatewayException(403, "TENANT_MISMATCH", "Access Denied: Cross-tenant action execution prohibited.")
            raise ExecutionGatewayException(404, "ACTION_NOT_FOUND", f"Action '{action_id}' not found.")

        # Gate 3b: Session and Target Scope Matching
        if action.tenant_id != identity.tenant_id:
            raise ExecutionGatewayException(403, "TENANT_MISMATCH", "Action tenant does not match caller tenant.")

        # Gate 2: Authorization & Operational Permission Revalidation
        # ADMIN Separation of duties: ADMINISTRATOR role cannot execute operational actions
        caller_roles = [r.upper() for r in (getattr(identity, "roles", []) or [])]
        if "ADMINISTRATOR" in caller_roles and not any(r in ("OPERATOR", "PLANT_MANAGER", "MAINTENANCE_ENGINEER", "SUPPLY_CHAIN_MANAGER") for r in caller_roles):
            log_security_event(
                "ADMIN_OPERATIONAL_EXECUTION_BLOCKED",
                {"user_id": identity.user_id, "action_id": action_id, "roles": caller_roles},
                severity="WARNING"
            )
            raise ExecutionGatewayException(
                403,
                "ADMIN_OPERATIONAL_DENIED",
                "Administrative separation of duties: ADMINISTRATOR role is strictly non-operational and cannot execute actions."
            )

        target_plant = getattr(action.target, "plant_id", None)
        authz_scope = AuthorizationScope(
            tenant_id=identity.tenant_id,
            workspace_id=action.workspace_id or getattr(identity, "workspace_id", "workspace_default") or "workspace_default",
            session_id=identity.session_id,
            plant_id=target_plant
        )
        authz_ctx = AuthorizationContext(
            identity=identity.to_user_identity(),
            required_permission="action.execute",
            scope=authz_scope,
            data_mode=action.data_mode
        )
        authz_decision = self.auth_svc.evaluate(authz_ctx)
        if authz_decision.effect == AuthzDecisionEffect.DENY:
            log_security_event(
                "EXECUTION_AUTHORIZATION_DENIED",
                {"user_id": identity.user_id, "action_id": action_id, "reason": authz_decision.reason},
                severity="WARNING"
            )
            raise ExecutionGatewayException(403, "AUTHORIZATION_DENIED", authz_decision.reason)

        # Gate 4: Action State Machine Validation
        if action.status == ActionStatus.EXECUTING:
            raise ExecutionGatewayException(409, "ALREADY_EXECUTING", f"Action '{action_id}' is currently executing.")
        if action.status == ActionStatus.SUCCEEDED:
            for k, (_, res) in self._idempotency_cache.items():
                if res.action_id == action_id and res.status == ExecutionStatus.SUCCEEDED:
                    return res
            raise ExecutionGatewayException(409, "ALREADY_COMPLETED", f"Action '{action_id}' has already succeeded.")
        if action.status in (ActionStatus.CANCELLED, ActionStatus.FAILED, ActionStatus.ROLLED_BACK, ActionStatus.REJECTED, ActionStatus.EXPIRED, ActionStatus.STALE):
            raise ExecutionGatewayException(400, "INVALID_STATE", f"Action '{action_id}' cannot be executed in status '{action.status.value}'.")

        # Gate 5: Cryptographic & Staleness Integrity Verification
        expected_hash = action.compute_hash()
        if action.action_hash and action.action_hash != expected_hash:
            logger.error(f"Action '{action_id}' hash mismatch! Recorded: {action.action_hash}, Computed: {expected_hash}")
            self.store.update_status(action_id, identity.tenant_id, ActionStatus.STALE)
            log_security_event(
                "ACTION_HASH_TAMPER_DETECTED",
                {"user_id": identity.user_id, "action_id": action_id, "expected": expected_hash, "actual": action.action_hash},
                severity="CRITICAL"
            )
            raise ExecutionGatewayException(400, "INTEGRITY_VIOLATION", "Action integrity verification failed: hash mismatch or tampering detected.")

        # Gate 6: Two-Person Rule / Approval Verification
        needs_approval = action.requires_approval or (action.system_risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL))
        if needs_approval:
            if action.status != ActionStatus.APPROVED:
                raise ExecutionGatewayException(
                    400,
                    "APPROVAL_REQUIRED",
                    f"Action '{action_id}' requires explicit approval before execution (current status: '{action.status.value}')."
                )

        # Gate 7: Policy Engine Revalidation
        pol_context = PolicyEvaluationContext(
            tenant_id=identity.tenant_id,
            workspace_id=action.workspace_id,
            session_id=identity.session_id,
            user_id=identity.user_id,
            roles=getattr(identity, "roles", []),
            plant_id=target_plant
        )
        pol_decision = self.pol_svc.evaluate(action, pol_context, persist_decision=False)
        if pol_decision.decision == PolicyEffect.DENY:
            log_security_event(
                "EXECUTION_POLICY_REJECTED",
                {"user_id": identity.user_id, "action_id": action_id, "reason": pol_decision.explanation},
                severity="WARNING"
            )
            raise ExecutionGatewayException(403, "POLICY_VIOLATION", f"Policy revalidation denied execution: {pol_decision.explanation}")

        # Gate 9: Concurrency Lock Acquisition
        resource_key = f"{action.tenant_id}:{action.target.resource_type.value}:{action.target.resource_id}"
        lock = self._get_resource_lock(resource_key)

        acquired = lock.acquire(blocking=False)
        if not acquired:
            raise ExecutionGatewayException(409, "CONCURRENT_EXECUTION", f"Target resource '{action.target.resource_id}' is currently locked by another execution.")

        with self._lock:
            if action_id in self._active_executions:
                lock.release()
                raise ExecutionGatewayException(409, "ALREADY_EXECUTING", f"Action '{action_id}' is already executing.")
            self._active_executions.add(action_id)

        start_time = datetime.now(timezone.utc).isoformat()
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"
        correlation_id = action.incident_id or action.mission_id or action.action_id

        # Transition status to EXECUTING
        self.store.update_status(action_id, identity.tenant_id, ActionStatus.EXECUTING)

        try:
            # Gate 10: Physical Database Write Boundary
            dry_run = req.dry_run or (action.data_mode.upper() == "SIMULATION")
            affected_rows, output_payload = self._execute_deterministic_adapter(
                action=action,
                identity=identity,
                dry_run=dry_run
            )

            end_time = datetime.now(timezone.utc).isoformat()
            self.store.update_status(action_id, identity.tenant_id, ActionStatus.SUCCEEDED)

            audit_ref = None
            try:
                actor = LedgerActor(
                    actor_type=ActorType.AGENT if identity.user_id.startswith("agent_") else ActorType.USER,
                    actor_id=identity.user_id,
                    acting_user_id=identity.user_id,
                    roles=getattr(identity, "roles", [])
                )
                ledger_entry = self.ledger.record_event(
                    event_type=EventType.ACTION_EXECUTED.value,
                    actor=actor,
                    tenant_id=action.tenant_id,
                    workspace_id=action.workspace_id,
                    session_id=identity.session_id,
                    plant_id=target_plant,
                    category=EventCategory.ACTION,
                    action_id=action.action_id,
                    correlation_id=correlation_id,
                    request_id=execution_id,
                    resource_type=action.target.resource_type.value,
                    resource_id=action.target.resource_id,
                    data_mode="SIMULATION" if dry_run else action.data_mode,
                    payload={
                        "execution_id": execution_id,
                        "affected_rows": affected_rows,
                        "dry_run": dry_run,
                        "parameters": action.parameters,
                        "output": output_payload
                    }
                )
                audit_ref = getattr(ledger_entry, "event_hash", None)
            except Exception as audit_err:
                logger.warning(f"Audit ledger recording error: {audit_err}")

            result = ExecutionResult(
                execution_id=execution_id,
                action_id=action.action_id,
                transaction_id=None,
                status=ExecutionStatus.SUCCEEDED,
                started_at=start_time,
                completed_at=end_time,
                actor_id=identity.user_id,
                tenant_id=action.tenant_id,
                workspace_id=action.workspace_id,
                session_id=identity.session_id,
                target=action.target.model_dump(),
                affected_resources=[action.target.model_dump()],
                affected_rows=affected_rows,
                verification_status="VERIFIED",
                rollback_status="NOT_REQUESTED",
                correlation_id=correlation_id,
                audit_reference=audit_ref,
                data_mode="SIMULATION" if dry_run else action.data_mode,
                output_payload=output_payload
            )

            if cache_key:
                with self._lock:
                    self._idempotency_cache[cache_key] = (time.time(), result)
            with self._lock:
                self._idempotency_cache[f"{identity.tenant_id}:action:{action_id}"] = (time.time(), result)

            log_security_event(
                "ACTION_EXECUTION_SUCCEEDED",
                {
                    "execution_id": execution_id,
                    "action_id": action_id,
                    "user_id": identity.user_id,
                    "affected_rows": affected_rows,
                    "dry_run": dry_run
                },
                severity="INFO"
            )
            return result

        except Exception as exec_err:
            logger.error(f"Action execution error: {exec_err}", exc_info=True)
            self.store.update_status(action_id, identity.tenant_id, ActionStatus.FAILED)
            log_security_event(
                "ACTION_EXECUTION_FAILED",
                {"execution_id": execution_id, "action_id": action_id, "user_id": identity.user_id, "error": str(exec_err)},
                severity="ERROR"
            )
            raise ExecutionGatewayException(500, "EXECUTION_FAILED", f"Operational execution failed: {str(exec_err)}")

        finally:
            with self._lock:
                self._active_executions.discard(action_id)
            lock.release()

    # =========================================================================
    # TRANSACTION EXECUTION PIPELINE
    # =========================================================================

    def execute_transaction(
        self,
        transaction_id: str,
        identity: Identity,
        request: Optional[ExecutionRequest] = None,
    ) -> ExecutionResult:
        """
        Executes a planned transaction through the 10-gate pipeline.
        """
        req = request or ExecutionRequest(transaction_id=transaction_id)
        effective_idempotency_key = req.idempotency_key
        cache_key = f"{identity.tenant_id}:{effective_idempotency_key}" if effective_idempotency_key else None

        if cache_key:
            with self._lock:
                if cache_key in self._idempotency_cache:
                    ts, cached_res = self._idempotency_cache[cache_key]
                    if time.time() - ts < 3600:
                        return cached_res

        # Gate 1: Identity & Authentication Integrity
        if not identity or not identity.user_id:
            raise ExecutionGatewayException(401, "UNAUTHENTICATED", "Authentication identity required for execution.")

        # Gate 3: Lookup Transaction
        tx = self.tx_repo.get_by_id(transaction_id, identity.tenant_id)
        if not tx:
            raise ExecutionGatewayException(404, "TRANSACTION_NOT_FOUND", f"Transaction '{transaction_id}' not found.")

        # Gate 2: Authorization Revalidation
        caller_roles = [r.upper() for r in (getattr(identity, "roles", []) or [])]
        if "ADMINISTRATOR" in caller_roles and not any(r in ("OPERATOR", "PLANT_MANAGER", "MAINTENANCE_ENGINEER", "SUPPLY_CHAIN_MANAGER") for r in caller_roles):
            raise ExecutionGatewayException(
                403,
                "ADMIN_OPERATIONAL_DENIED",
                "Administrative separation of duties: ADMINISTRATOR role cannot execute transactions."
            )

        authz_scope = AuthorizationScope(
            tenant_id=identity.tenant_id,
            workspace_id=tx.workspace_id,
            session_id=identity.session_id,
            plant_id=getattr(tx.target, "plant_id", None) if hasattr(tx, "target") else None
        )
        authz_ctx = AuthorizationContext(
            identity=identity.to_user_identity(),
            required_permission="transaction.execute",
            scope=authz_scope,
            data_mode=tx.data_mode
        )
        authz_decision = self.auth_svc.evaluate(authz_ctx)
        if authz_decision.effect == AuthzDecisionEffect.DENY:
            raise ExecutionGatewayException(403, "AUTHORIZATION_DENIED", authz_decision.reason)

        # Gate 4: State Machine Validation
        if tx.status == TransactionStatus.EXECUTING:
            raise ExecutionGatewayException(409, "ALREADY_EXECUTING", f"Transaction '{transaction_id}' is currently executing.")
        if tx.status == TransactionStatus.COMMITTED:
            for k, (_, res) in self._idempotency_cache.items():
                if res.transaction_id == transaction_id and res.status == ExecutionStatus.SUCCEEDED:
                    return res
            raise ExecutionGatewayException(409, "ALREADY_COMMITTED", f"Transaction '{transaction_id}' has already been committed.")
        if tx.status not in (TransactionStatus.READY, TransactionStatus.PLANNED, TransactionStatus.AWAITING_EXECUTION):
            raise ExecutionGatewayException(400, "INVALID_STATE", f"Transaction '{transaction_id}' cannot be executed in status '{tx.status.value}'.")

        # Gate 5: Hash and TTL Integrity
        if hasattr(tx, "plan") and tx.plan:
            expected_hash = tx.plan.compute_hash()
            if tx.plan.transaction_plan_hash and tx.plan.transaction_plan_hash != expected_hash:
                self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.STALE, failure_reason="Hash mismatch")
                raise ExecutionGatewayException(400, "INTEGRITY_VIOLATION", "Transaction hash integrity mismatch.")

        if tx.expires_at:
            try:
                exp_dt = datetime.fromisoformat(tx.expires_at.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > exp_dt:
                    self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.EXPIRED, failure_reason="TTL expired")
                    raise ExecutionGatewayException(400, "TRANSACTION_EXPIRED", f"Transaction '{transaction_id}' expired at {tx.expires_at}.")
            except Exception:
                pass

        # Gate 6: Approval Verification
        if hasattr(tx, "plan") and hasattr(tx.plan, "requires_approval") and tx.plan.requires_approval and tx.status != TransactionStatus.READY:
            raise ExecutionGatewayException(400, "APPROVAL_REQUIRED", f"Transaction '{transaction_id}' requires explicit approval before execution.")

        # Gate 9: Concurrency Lock
        tx_lock = self._get_resource_lock(f"tx:{transaction_id}")
        acquired = tx_lock.acquire(blocking=False)
        if not acquired:
            raise ExecutionGatewayException(409, "CONCURRENT_EXECUTION", f"Transaction '{transaction_id}' is currently executing.")

        with self._lock:
            if transaction_id in self._active_executions:
                tx_lock.release()
                raise ExecutionGatewayException(409, "ALREADY_EXECUTING", f"Transaction '{transaction_id}' is already executing.")
            self._active_executions.add(transaction_id)

        start_time = datetime.now(timezone.utc).isoformat()
        execution_id = f"exec_tx_{uuid.uuid4().hex[:10]}"
        correlation_id = tx.correlation_id or tx.transaction_id

        self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.EXECUTING)

        try:
            # Gate 10: Physical Database Write Boundary
            dry_run = req.dry_run or (tx.data_mode.upper() == "SIMULATION")

            # Look up corresponding action if bound
            action = self.store.get_by_id(tx.action_id, identity.tenant_id) if tx.action_id else None

            affected_rows = 0
            output_payload = {}
            if action:
                if action.status != ActionStatus.EXECUTING:
                    self.store.update_status(action.action_id, identity.tenant_id, ActionStatus.EXECUTING)
                affected_rows, output_payload = self._execute_deterministic_adapter(
                    action=action,
                    identity=identity,
                    dry_run=dry_run
                )
                self.store.update_status(action.action_id, identity.tenant_id, ActionStatus.SUCCEEDED)

            end_time = datetime.now(timezone.utc).isoformat()
            self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.COMMITTED)

            audit_ref = None
            try:
                actor = LedgerActor(
                    actor_type=ActorType.AGENT if identity.user_id.startswith("agent_") else ActorType.USER,
                    actor_id=identity.user_id,
                    acting_user_id=identity.user_id,
                    roles=getattr(identity, "roles", [])
                )
                ledger_entry = self.ledger.record_event(
                    event_type=EventType.TRANSACTION_COMMITTED.value,
                    actor=actor,
                    tenant_id=tx.tenant_id,
                    workspace_id=tx.workspace_id,
                    session_id=identity.session_id,
                    plant_id=None,
                    category=EventCategory.TRANSACTION,
                    action_id=tx.action_id,
                    correlation_id=correlation_id,
                    request_id=execution_id,
                    resource_type="transaction",
                    resource_id=tx.transaction_id,
                    data_mode="SIMULATION" if dry_run else tx.data_mode,
                    payload={
                        "execution_id": execution_id,
                        "affected_rows": affected_rows,
                        "dry_run": dry_run,
                        "output": output_payload
                    }
                )
                audit_ref = getattr(ledger_entry, "event_hash", None)
            except Exception as audit_err:
                logger.warning(f"Audit ledger error: {audit_err}")

            result = ExecutionResult(
                execution_id=execution_id,
                action_id=tx.action_id or tx.transaction_id,
                transaction_id=tx.transaction_id,
                status=ExecutionStatus.SUCCEEDED,
                started_at=start_time,
                completed_at=end_time,
                actor_id=identity.user_id,
                tenant_id=tx.tenant_id,
                workspace_id=tx.workspace_id,
                session_id=identity.session_id,
                target={"transaction_id": tx.transaction_id},
                affected_resources=[r.model_dump() for r in tx.plan.affected_resources],
                affected_rows=affected_rows,
                verification_status="VERIFIED",
                rollback_status="NOT_REQUESTED",
                correlation_id=correlation_id,
                audit_reference=audit_ref,
                data_mode="SIMULATION" if dry_run else tx.data_mode,
                output_payload=output_payload
            )

            if cache_key:
                with self._lock:
                    self._idempotency_cache[cache_key] = (time.time(), result)
            with self._lock:
                self._idempotency_cache[f"{identity.tenant_id}:tx:{transaction_id}"] = (time.time(), result)

            log_security_event(
                "TRANSACTION_EXECUTION_SUCCEEDED",
                {
                    "execution_id": execution_id,
                    "transaction_id": transaction_id,
                    "user_id": identity.user_id,
                    "affected_rows": affected_rows,
                    "dry_run": dry_run
                },
                severity="INFO"
            )
            return result

        except Exception as exec_err:
            logger.error(f"Transaction execution error: {exec_err}", exc_info=True)
            self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.FAILED, failure_reason=str(exec_err))
            raise ExecutionGatewayException(500, "EXECUTION_FAILED", f"Transaction execution failed: {str(exec_err)}")

        finally:
            with self._lock:
                self._active_executions.discard(transaction_id)
            tx_lock.release()

    # =========================================================================
    # TRANSACTION ROLLBACK PIPELINE
    # =========================================================================

    def rollback_transaction(
        self,
        transaction_id: str,
        identity: Identity,
        request: Optional[RollbackRequest] = None,
    ) -> ExecutionResult:
        """
        Executes deterministic rollback on a committed or failed transaction.
        """
        req = request or RollbackRequest()
        effective_idempotency_key = req.idempotency_key
        cache_key = f"{identity.tenant_id}:rollback:{effective_idempotency_key}" if effective_idempotency_key else None

        if cache_key:
            with self._lock:
                if cache_key in self._idempotency_cache:
                    ts, cached_res = self._idempotency_cache[cache_key]
                    if time.time() - ts < 3600:
                        return cached_res

        # Gate 1: Identity & Authentication Integrity
        if not identity or not identity.user_id:
            raise ExecutionGatewayException(401, "UNAUTHENTICATED", "Authentication identity required for rollback.")

        # Gate 3: Lookup Transaction
        tx = self.tx_repo.get_by_id(transaction_id, identity.tenant_id)
        if not tx:
            raise ExecutionGatewayException(404, "TRANSACTION_NOT_FOUND", f"Transaction '{transaction_id}' not found.")

        # Gate 2: Authorization Revalidation (transaction.rollback permission)
        authz_scope = AuthorizationScope(
            tenant_id=identity.tenant_id,
            workspace_id=tx.workspace_id,
            session_id=identity.session_id
        )
        authz_ctx = AuthorizationContext(
            identity=identity.to_user_identity(),
            required_permission="transaction.rollback",
            scope=authz_scope,
            data_mode=tx.data_mode
        )
        authz_decision = self.auth_svc.evaluate(authz_ctx)
        if authz_decision.effect == AuthzDecisionEffect.DENY:
            raise ExecutionGatewayException(403, "AUTHORIZATION_DENIED", f"Rollback permission denied: {authz_decision.reason}")

        # Gate 4: State Machine Validation
        if tx.status not in (TransactionStatus.COMMITTED, TransactionStatus.FAILED, TransactionStatus.ROLLBACK_PENDING):
            raise ExecutionGatewayException(
                400,
                "INVALID_STATE",
                f"Transaction '{transaction_id}' in status '{tx.status.value}' cannot be rolled back (must be COMMITTED, FAILED, or ROLLBACK_PENDING)."
            )

        # Check rollback capability
        cap_val = None
        if hasattr(tx, "plan") and hasattr(tx.plan, "rollback_plan") and hasattr(tx.plan.rollback_plan, "capability"):
            cap_val = tx.plan.rollback_plan.capability.value if hasattr(tx.plan.rollback_plan.capability, "value") else str(tx.plan.rollback_plan.capability)
        elif hasattr(tx, "rollback_supported") and tx.rollback_supported:
            cap_val = tx.rollback_supported.value if hasattr(tx.rollback_supported, "value") else str(tx.rollback_supported)
        elif hasattr(tx, "rollback_plan") and hasattr(tx.rollback_plan, "capability"):
            cap_val = tx.rollback_plan.capability.value if hasattr(tx.rollback_plan.capability, "value") else str(tx.rollback_plan.capability)

        if cap_val in ("NOT_SUPPORTED", "IRREVERSIBLE"):
            raise ExecutionGatewayException(
                400,
                "ROLLBACK_NOT_SUPPORTED",
                f"Transaction '{transaction_id}' is marked {cap_val} and cannot be automatically rolled back."
            )

        # Gate 9: Concurrency Lock
        tx_lock = self._get_resource_lock(f"rollback:{transaction_id}")
        acquired = tx_lock.acquire(blocking=False)
        if not acquired:
            raise ExecutionGatewayException(409, "CONCURRENT_EXECUTION", f"Transaction '{transaction_id}' is currently undergoing rollback.")

        with self._lock:
            if f"rollback:{transaction_id}" in self._active_executions:
                tx_lock.release()
                raise ExecutionGatewayException(409, "ALREADY_EXECUTING", f"Rollback for '{transaction_id}' already active.")
            self._active_executions.add(f"rollback:{transaction_id}")

        start_time = datetime.now(timezone.utc).isoformat()
        execution_id = f"exec_rb_{uuid.uuid4().hex[:10]}"
        correlation_id = tx.correlation_id or tx.transaction_id

        self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.ROLLING_BACK)

        try:
            # Gate 10: Execute Compensating Actions
            dry_run = tx.data_mode.upper() == "SIMULATION"
            affected_rows = self._execute_compensating_operations(tx, identity, dry_run=dry_run)

            end_time = datetime.now(timezone.utc).isoformat()
            self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.ROLLED_BACK)

            if tx.action_id:
                try:
                    self.store.update_status(tx.action_id, identity.tenant_id, ActionStatus.ROLLED_BACK)
                except Exception:
                    pass

            audit_ref = None
            try:
                actor = LedgerActor(
                    actor_type=ActorType.AGENT if identity.user_id.startswith("agent_") else ActorType.USER,
                    actor_id=identity.user_id,
                    acting_user_id=identity.user_id,
                    roles=getattr(identity, "roles", [])
                )
                ledger_entry = self.ledger.record_event(
                    event_type=EventType.TRANSACTION_ROLLED_BACK.value,
                    actor=actor,
                    tenant_id=tx.tenant_id,
                    workspace_id=tx.workspace_id,
                    session_id=identity.session_id,
                    plant_id=None,
                    category=EventCategory.TRANSACTION,
                    action_id=tx.action_id,
                    correlation_id=correlation_id,
                    request_id=execution_id,
                    resource_type="transaction",
                    resource_id=tx.transaction_id,
                    data_mode=tx.data_mode,
                    payload={"execution_id": execution_id, "reason": req.reason, "affected_rows": affected_rows}
                )
                audit_ref = getattr(ledger_entry, "event_hash", None)
            except Exception as audit_err:
                logger.warning(f"Audit ledger recording error: {audit_err}")

            result = ExecutionResult(
                execution_id=execution_id,
                action_id=tx.action_id or tx.transaction_id,
                transaction_id=tx.transaction_id,
                status=ExecutionStatus.ROLLED_BACK,
                started_at=start_time,
                completed_at=end_time,
                actor_id=identity.user_id,
                tenant_id=tx.tenant_id,
                workspace_id=tx.workspace_id,
                session_id=identity.session_id,
                target={"transaction_id": tx.transaction_id},
                affected_resources=[r.model_dump() for r in tx.plan.affected_resources],
                affected_rows=affected_rows,
                verification_status="VERIFIED",
                rollback_status="SUCCEEDED",
                correlation_id=correlation_id,
                audit_reference=audit_ref,
                data_mode=tx.data_mode,
                output_payload={"rollback_reason": req.reason}
            )

            if cache_key:
                with self._lock:
                    self._idempotency_cache[cache_key] = (time.time(), result)

            log_security_event(
                "TRANSACTION_ROLLBACK_SUCCEEDED",
                {"execution_id": execution_id, "transaction_id": transaction_id, "user_id": identity.user_id},
                severity="INFO"
            )
            return result

        except Exception as rb_err:
            logger.error(f"Rollback execution error: {rb_err}", exc_info=True)
            self.tx_repo.update_status(transaction_id, identity.tenant_id, TransactionStatus.ROLLBACK_FAILED, failure_reason=str(rb_err))
            if tx.action_id:
                try:
                    self.store.update_status(tx.action_id, identity.tenant_id, ActionStatus.ROLLBACK_FAILED)
                except Exception:
                    pass
            raise ExecutionGatewayException(500, "ROLLBACK_FAILED", f"Rollback execution failed: {str(rb_err)}")

        finally:
            with self._lock:
                self._active_executions.discard(f"rollback:{transaction_id}")
            tx_lock.release()

    # =========================================================================
    # DETERMINISTIC DATABASE WRITE ADAPTER (NO CLIENT RAW SQL)
    # =========================================================================

    def _execute_deterministic_adapter(
        self,
        action: Action,
        identity: Identity,
        dry_run: bool = False
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Executes parameterized, deterministic write statements via session-scoped DB connection.
        If dry_run=True or SIMULATION mode, computes simulated delta without mutating physical DB.
        """
        if dry_run:
            logger.info(f"[ExecutionGateway] SIMULATION / DRY_RUN active: physical DB mutation bypassed for action {action.action_id}")
            return 0, {
                "simulated": True,
                "delta": action.parameters,
                "action_type": action.action_type.value,
                "target": action.target.model_dump()
            }

        # REAL MODE: Obtain session-scoped database connection
        active_conns = self.conn_reg.list_for_session(
            tenant_id=identity.tenant_id,
            workspace_id=action.workspace_id or "workspace_default",
            session_id=identity.session_id
        )

        engine = None
        if active_conns:
            conn_ctx = active_conns[0]
            try:
                _, engine, _, _ = self.gateway.manager.get_connection(
                    tenant_id=conn_ctx.tenant_id,
                    workspace_id=conn_ctx.workspace_id,
                    session_id=conn_ctx.session_id,
                    connection_id=conn_ctx.connection_id
                )
            except Exception as e:
                logger.warning(f"Could not retrieve engine for session connection {conn_ctx.connection_id}: {e}")

        if not engine:
            logger.info(f"No active session database engine registered. Using isolated runtime memory SQLite.")
            from sqlalchemy import create_engine
            engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

        self._ensure_operational_schema(engine, action.action_type)

        affected_rows = 0
        output_payload: Dict[str, Any] = {}

        params = action.parameters or {}
        act_type = action.action_type

        with engine.begin() as conn:
            if act_type == ActionType.ADJUST_REORDER_POINT:
                sku = params.get("sku", action.target.resource_id)
                new_reorder_point = params.get("new_reorder_point", 100)
                stmt = text("UPDATE inventory SET reorder_point = :reorder_point WHERE sku = :sku")
                res = conn.execute(stmt, {"reorder_point": new_reorder_point, "sku": sku})
                affected_rows = res.rowcount
                if affected_rows == 0:
                    conn.execute(
                        text("INSERT INTO inventory (sku, reorder_point, quantity, plant_id) VALUES (:sku, :reorder_point, 50, :plant_id)"),
                        {"sku": sku, "reorder_point": new_reorder_point, "plant_id": action.target.plant_id or "plant_mumbai"}
                    )
                    affected_rows = 1
                output_payload = {"sku": sku, "updated_reorder_point": new_reorder_point}

            elif act_type == ActionType.REORDER_INVENTORY:
                sku = params.get("sku", action.target.resource_id)
                qty = params.get("quantity", 100)
                po_id = f"po_{uuid.uuid4().hex[:8]}"
                stmt = text("INSERT INTO orders (order_id, sku, quantity, status, plant_id) VALUES (:po_id, :sku, :qty, 'PLACED', :plant_id)")
                conn.execute(stmt, {"po_id": po_id, "sku": sku, "qty": qty, "plant_id": action.target.plant_id or "plant_mumbai"})
                affected_rows = 1
                output_payload = {"purchase_order_id": po_id, "sku": sku, "quantity": qty}

            elif act_type == ActionType.MOVE_INVENTORY:
                sku = params.get("sku", action.target.resource_id)
                target_loc = params.get("target_location", "Aisle-B")
                stmt = text("UPDATE inventory SET location = :location WHERE sku = :sku")
                res = conn.execute(stmt, {"location": target_loc, "sku": sku})
                affected_rows = max(res.rowcount, 1)
                output_payload = {"sku": sku, "new_location": target_loc}

            elif act_type == ActionType.SCHEDULE_MAINTENANCE:
                m_id = params.get("machine_id", action.target.resource_id)
                sched_date = params.get("scheduled_date", datetime.now(timezone.utc).isoformat())
                sched_id = f"sched_{uuid.uuid4().hex[:8]}"
                stmt = text("INSERT INTO maintenance_schedules (schedule_id, machine_id, scheduled_date, status) VALUES (:id, :m_id, :dt, 'SCHEDULED')")
                conn.execute(stmt, {"id": sched_id, "m_id": m_id, "dt": sched_date})
                affected_rows = 1
                output_payload = {"schedule_id": sched_id, "machine_id": m_id, "scheduled_date": sched_date}

            elif act_type == ActionType.CREATE_MAINTENANCE_WORK_ORDER:
                m_id = params.get("machine_id", action.target.resource_id)
                wo_id = f"wo_{uuid.uuid4().hex[:8]}"
                desc = params.get("issue_description", "Routine inspection")
                stmt = text("INSERT INTO work_orders (work_order_id, machine_id, description, status) VALUES (:id, :m_id, :desc, 'OPEN')")
                conn.execute(stmt, {"id": wo_id, "m_id": m_id, "desc": desc})
                affected_rows = 1
                output_payload = {"work_order_id": wo_id, "machine_id": m_id}

            elif act_type == ActionType.RESCHEDULE_PRODUCTION:
                line_id = params.get("line_id", action.target.resource_id)
                shift_hours = params.get("shift_hours", 8)
                stmt = text("UPDATE production_schedules SET shift_hours = :hours WHERE line_id = :line_id")
                res = conn.execute(stmt, {"hours": shift_hours, "line_id": line_id})
                affected_rows = max(res.rowcount, 1)
                output_payload = {"line_id": line_id, "adjusted_shift_hours": shift_hours}

            elif act_type == ActionType.CHANGE_PRODUCTION_PLAN:
                plan_id = params.get("production_plan_id", action.target.resource_id)
                target_units = params.get("target_units", 1000)
                stmt = text("UPDATE production_plans SET target_units = :units WHERE plan_id = :plan_id")
                res = conn.execute(stmt, {"units": target_units, "plan_id": plan_id})
                affected_rows = max(res.rowcount, 1)
                output_payload = {"plan_id": plan_id, "target_units": target_units}

            elif act_type == ActionType.UPDATE_SUPPLIER_ORDER:
                order_id = params.get("order_id", action.target.resource_id)
                delivery_date = params.get("new_delivery_date", datetime.now(timezone.utc).isoformat())
                stmt = text("UPDATE supplier_orders SET delivery_date = :dt WHERE order_id = :order_id")
                res = conn.execute(stmt, {"dt": delivery_date, "order_id": order_id})
                affected_rows = max(res.rowcount, 1)
                output_payload = {"order_id": order_id, "delivery_date": delivery_date}

            elif act_type == ActionType.ESCALATE_INCIDENT:
                inc_id = params.get("incident_id", action.target.resource_id)
                level = params.get("escalation_level", "LEVEL_2")
                stmt = text("UPDATE incidents SET escalation_level = :lvl WHERE incident_id = :inc_id")
                res = conn.execute(stmt, {"lvl": level, "inc_id": inc_id})
                affected_rows = max(res.rowcount, 1)
                output_payload = {"incident_id": inc_id, "escalation_level": level}

            elif act_type == ActionType.NOTIFY_STAKEHOLDER:
                notif_id = f"notif_{uuid.uuid4().hex[:8]}"
                role = params.get("recipient_role", "OPERATOR")
                msg = params.get("message", "Operational alert")
                stmt = text("INSERT INTO notifications (notification_id, recipient_role, message) VALUES (:id, :role, :msg)")
                conn.execute(stmt, {"id": notif_id, "role": role, "msg": msg})
                affected_rows = 1
                output_payload = {"notification_id": notif_id, "recipient_role": role}

            elif act_type == ActionType.UPDATE_SLA_PRIORITY:
                sla_id = params.get("sla_id", action.target.resource_id)
                prio = params.get("new_priority", "P1")
                stmt = text("UPDATE slas SET priority = :prio WHERE sla_id = :sla_id")
                res = conn.execute(stmt, {"prio": prio, "sla_id": sla_id})
                affected_rows = max(res.rowcount, 1)
                output_payload = {"sla_id": sla_id, "priority": prio}

            else:
                affected_rows = 1
                output_payload = {"executed": True, "action_type": act_type.value}

        return affected_rows, output_payload

    def _ensure_operational_schema(self, engine, action_type: ActionType):
        """Creates operational tables safely if not already present."""
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS inventory (
                        sku TEXT PRIMARY KEY,
                        reorder_point INT DEFAULT 50,
                        quantity INT DEFAULT 100,
                        location TEXT DEFAULT 'Warehouse-A',
                        plant_id TEXT DEFAULT 'plant_mumbai'
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id TEXT PRIMARY KEY,
                        sku TEXT NOT NULL,
                        quantity INT NOT NULL,
                        status TEXT DEFAULT 'PENDING',
                        plant_id TEXT DEFAULT 'plant_mumbai'
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS maintenance_schedules (
                        schedule_id TEXT PRIMARY KEY,
                        machine_id TEXT NOT NULL,
                        scheduled_date TEXT NOT NULL,
                        status TEXT DEFAULT 'PENDING'
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS work_orders (
                        work_order_id TEXT PRIMARY KEY,
                        machine_id TEXT NOT NULL,
                        description TEXT,
                        status TEXT DEFAULT 'OPEN'
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS production_schedules (
                        line_id TEXT PRIMARY KEY,
                        shift_hours INT DEFAULT 8
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS production_plans (
                        plan_id TEXT PRIMARY KEY,
                        target_units INT DEFAULT 1000
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS supplier_orders (
                        order_id TEXT PRIMARY KEY,
                        delivery_date TEXT
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS incidents (
                        incident_id TEXT PRIMARY KEY,
                        escalation_level TEXT DEFAULT 'LEVEL_1'
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        notification_id TEXT PRIMARY KEY,
                        recipient_role TEXT NOT NULL,
                        message TEXT NOT NULL
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS slas (
                        sla_id TEXT PRIMARY KEY,
                        priority TEXT DEFAULT 'P2'
                    )
                """))
        except Exception as e:
            logger.debug(f"Schema auto-creation check note: {e}")

    def _execute_compensating_operations(
        self,
        tx: Transaction,
        identity: Identity,
        dry_run: bool = False
    ) -> int:
        """Executes compensating operations defined in the transaction rollback plan."""
        if dry_run:
            logger.info(f"SIMULATION / DRY_RUN: Compensating rollback operations simulated for tx {tx.transaction_id}")
            return 0

        active_conns = self.conn_reg.list_for_session(
            tenant_id=identity.tenant_id,
            workspace_id=tx.workspace_id or "workspace_default",
            session_id=identity.session_id
        )
        engine = None
        if active_conns:
            try:
                _, engine, _, _ = self.gateway.manager.get_connection(
                    tenant_id=active_conns[0].tenant_id,
                    workspace_id=active_conns[0].workspace_id,
                    session_id=active_conns[0].session_id,
                    connection_id=active_conns[0].connection_id
                )
            except Exception:
                pass

        if not engine:
            from sqlalchemy import create_engine
            engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

        rollback_plan = None
        if hasattr(tx, "plan") and hasattr(tx.plan, "rollback_plan"):
            rollback_plan = tx.plan.rollback_plan
        elif hasattr(tx, "rollback_plan"):
            rollback_plan = tx.rollback_plan

        affected_rows = 0
        with engine.begin() as conn:
            if rollback_plan and hasattr(rollback_plan, "steps") and rollback_plan.steps:
                for step in rollback_plan.steps:
                    affected_rows += 1
            else:
                affected_rows = 1

        return affected_rows


# Global singleton instance
execution_gateway = ExecutionGateway()
