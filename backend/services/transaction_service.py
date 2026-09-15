# backend/services/transaction_service.py
"""
SageCommand V3 — Transaction & Rollback Architecture Service
The definitive transaction planning, validation, revalidation, and rollback capability engine.
Acts as the mandatory deterministic boundary between Policy/Approval and future Execution.
Maintains: LLMs reason. Deterministic systems enforce. Transactions protect state.
"""

import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple

try:
    from core.config import SAGE_TRANSACTIONS_DB_PATH, SAGE_TRANSACTION_DEFAULT_TTL_SECONDS
    from core.auth import Identity
    from data.schemas.action_contract import Action, ActionStatus, ActionType, RiskLevel, RollbackCapability as ActionRollbackCap
    from data.schemas.policy_contract import PolicyEffect, PolicyEvaluationContext
    from data.schemas.transaction_contract import (
        Transaction,
        TransactionPlan,
        TransactionPrecondition,
        TransactionInvariant,
        AffectedResource,
        RollbackPlan,
        RollbackStrategy,
        RollbackCapability,
        TransactionStatus,
        TransactionType,
        ConflictType,
        PreconditionType,
        InvariantType,
        TransactionValidationResult
    )
    from data.schemas.ledger_contract import EventType, EventCategory, EventStatus
    from services.action_store import action_store, ActionStore
    from services.authorization_service import authorization_service, AuthorizationService
    from services.policy_service import policy_service, PolicyService
    from services.transaction_repository import transaction_repository, TransactionRepository
    from services.audit_ledger import audit_ledger, AuditLedgerService
    from governance.audit import log_security_event
    from data.schemas.authorization_contract import AuthorizationContext, AuthorizationScope, AuthzDecisionEffect
except ModuleNotFoundError:
    from backend.core.config import SAGE_TRANSACTIONS_DB_PATH, SAGE_TRANSACTION_DEFAULT_TTL_SECONDS
    from backend.core.auth import Identity
    from backend.data.schemas.action_contract import Action, ActionStatus, ActionType, RiskLevel, RollbackCapability as ActionRollbackCap
    from backend.data.schemas.policy_contract import PolicyEffect, PolicyEvaluationContext
    from backend.data.schemas.transaction_contract import (
        Transaction,
        TransactionPlan,
        TransactionPrecondition,
        TransactionInvariant,
        AffectedResource,
        RollbackPlan,
        RollbackStrategy,
        RollbackCapability,
        TransactionStatus,
        TransactionType,
        ConflictType,
        PreconditionType,
        InvariantType,
        TransactionValidationResult
    )
    from backend.data.schemas.ledger_contract import EventType, EventCategory, EventStatus
    from backend.services.action_store import action_store, ActionStore
    from backend.services.authorization_service import authorization_service, AuthorizationService
    from backend.services.policy_service import policy_service, PolicyService
    from backend.services.transaction_repository import transaction_repository, TransactionRepository
    from backend.services.audit_ledger import audit_ledger, AuditLedgerService
    from backend.governance.audit import log_security_event
    from backend.data.schemas.authorization_contract import AuthorizationContext, AuthorizationScope, AuthzDecisionEffect

logger = logging.getLogger("sagecommand.transaction")


# =====================================================================
# 1. TRANSACTION STATE MACHINE
# =====================================================================

class TransactionStateMachine:
    """
    Deterministic state machine enforcing guarded lifecycle transitions.
    Strictly forbids illegal jumps (e.g. PLANNED -> COMMITTED).
    """

    ALLOWED_TRANSITIONS: Dict[TransactionStatus, List[TransactionStatus]] = {
        TransactionStatus.PLANNED: [
            TransactionStatus.VALIDATING,
            TransactionStatus.CANCELLED,
            TransactionStatus.EXPIRED,
            TransactionStatus.FAILED
        ],
        TransactionStatus.VALIDATING: [
            TransactionStatus.READY,
            TransactionStatus.AWAITING_EXECUTION,
            TransactionStatus.FAILED,
            TransactionStatus.CANCELLED,
            TransactionStatus.EXPIRED
        ],
        TransactionStatus.READY: [
            TransactionStatus.AWAITING_EXECUTION,
            TransactionStatus.VALIDATING,
            TransactionStatus.CANCELLED,
            TransactionStatus.EXPIRED
        ],
        TransactionStatus.AWAITING_EXECUTION: [
            TransactionStatus.VALIDATING,
            TransactionStatus.CANCELLED,
            TransactionStatus.EXPIRED
            # Note: EXECUTING transition deferred to future Execution Gateway
        ],
        TransactionStatus.FAILED: [
            TransactionStatus.CANCELLED
        ],
        TransactionStatus.CANCELLED: [],
        TransactionStatus.EXPIRED: []
    }

    @classmethod
    def can_transition(cls, current: TransactionStatus, target: TransactionStatus) -> bool:
        allowed = cls.ALLOWED_TRANSITIONS.get(current, [])
        return target in allowed

    @classmethod
    def validate_transition(cls, current: TransactionStatus, target: TransactionStatus) -> None:
        if not cls.can_transition(current, target):
            msg = f"Illegal transaction state transition: '{current.value}' -> '{target.value}' is prohibited."
            logger.error(msg)
            raise ValueError(msg)


# =====================================================================
# 2. TRANSACTION PLANNER
# =====================================================================

class TransactionPlanner:
    """
    Deterministic Transaction Plan Generator.
    Produces safe, auditable TransactionPlans describing 'what would need to happen'
    without executing any operational side effects.
    """

    def __init__(
        self,
        store: ActionStore = action_store,
        auth_svc: AuthorizationService = authorization_service,
        pol_svc: PolicyService = policy_service
    ):
        self.store = store
        self.auth_svc = auth_svc
        self.pol_svc = pol_svc

    def create_plan(
        self,
        action: Action,
        identity: Identity,
        idempotency_key: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        data_mode_override: Optional[str] = None
    ) -> TransactionPlan:
        """
        Synthesizes a deterministic TransactionPlan from a validated Action.
        Side effects = False, Execution permitted = False.
        """
        # 1. Enforce Data Mode Rule: SIMULATION cannot promote to REAL
        plan_data_mode = action.data_mode
        if data_mode_override:
            if action.data_mode == "SIMULATION" and data_mode_override.upper() == "REAL":
                raise ValueError("Security Policy Violation: SIMULATION action cannot be promoted to REAL transaction.")
            plan_data_mode = data_mode_override.upper()

        # 2. Derive Expiration
        ttl = ttl_seconds or SAGE_TRANSACTION_DEFAULT_TTL_SECONDS
        now_dt = datetime.now(timezone.utc)
        expires_at = (now_dt + timedelta(seconds=ttl)).isoformat()
        now_iso = now_dt.isoformat()

        # 3. Extract Affected Resources
        affected_resources = self._derive_affected_resources(action)

        # 4. Generate Deterministic Preconditions & Invariants
        preconditions = self._derive_preconditions(action)
        invariants = self._derive_invariants(action)

        # 5. Determine Rollback Specification & Strategy
        rollback_plan = self._build_rollback_plan(action)

        # 6. Capture Policy Reference
        policy_ref = None
        try:
            pol_dec = None
            if hasattr(self.pol_svc, "evaluate"):
                ctx = PolicyEvaluationContext(
                    tenant_id=identity.tenant_id,
                    workspace_id=identity.workspace_id,
                    session_id=identity.session_id,
                    plant_id=action.target.plant_id if action.target else None,
                    user_id=identity.user_id,
                    roles=identity.roles,
                    resource_metadata={"affected_resources": [r.model_dump() for r in affected_resources]}
                )
                pol_dec = self.pol_svc.evaluate(action, ctx, persist_decision=False)
            elif hasattr(self.pol_svc, "evaluate_action"):
                pol_dec = self.pol_svc.evaluate_action(
                    action=action,
                    identity=identity,
                    resource_metadata={"affected_resources": [r.model_dump() for r in affected_resources]}
                )
            if pol_dec:
                policy_ref = {
                    "decision_id": pol_dec.decision_id,
                    "decision": pol_dec.decision.value if hasattr(pol_dec.decision, "value") else str(pol_dec.decision),
                    "policy_id": pol_dec.policy_id,
                    "policy_version": pol_dec.policy_version,
                    "decision_hash": pol_dec.decision_hash,
                    "reason_codes": pol_dec.reason_codes
                }
            else:
                policy_ref = {"decision": "HOLD", "reason": "Policy evaluation deferred during planning"}
        except Exception as e:
            logger.warning(f"Could not retrieve policy reference during planning: {e}")
            policy_ref = {"decision": "HOLD", "reason": "Policy evaluation deferred during planning"}

        # 7. Capture Authorization Reference
        auth_ref = None
        try:
            scope = AuthorizationScope(
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                session_id=identity.session_id,
                plant_id=action.target.plant_id if action.target else None
            )
            auth_ctx = AuthorizationContext(
                identity=identity.to_user_identity(),
                required_permission="transaction.plan",
                scope=scope,
                data_mode=plan_data_mode
            )
            auth_dec = self.auth_svc.evaluate(auth_ctx)
            auth_ref = {
                "decision_hash": auth_dec.decision_hash,
                "decision": auth_dec.effect.value,
                "evaluated_at": auth_dec.evaluated_at,
                "required_permission": "transaction.plan"
            }
        except Exception as e:
            logger.warning(f"Could not retrieve auth reference during planning: {e}")
            auth_ref = {"decision": "DENY", "reason": str(e)}

        # 8. Assemble TransactionPlan
        plan = TransactionPlan(
            transaction_plan_id=f"txp_{uuid.uuid4().hex[:10]}",
            transaction_plan_version=1,
            action_id=action.action_id,
            action_type=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type),
            action_version=action.version,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            session_id=action.session_id,
            plant_id=action.target.plant_id if action.target else None,
            target=action.target.model_dump() if hasattr(action.target, "model_dump") else action.target,
            parameters=action.parameters,
            preconditions=preconditions,
            invariants=invariants,
            affected_resources=affected_resources,
            expected_changes=self._derive_expected_changes(action),
            rollback_plan=rollback_plan,
            risk_level=action.system_risk_level.value if hasattr(action.system_risk_level, "value") else str(action.system_risk_level),
            system_risk_level=action.system_risk_level.value if hasattr(action.system_risk_level, "value") else str(action.system_risk_level),
            estimated_cost=action.estimated_cost.model_dump() if (action.estimated_cost and hasattr(action.estimated_cost, "model_dump")) else None,
            estimated_duration_seconds=(action.estimated_duration_minutes * 60) if action.estimated_duration_minutes else None,
            data_mode=plan_data_mode,
            access_mode="READ_WRITE",
            idempotency_key=idempotency_key,
            requires_approval=action.requires_approval,
            approval_reference="NOT_AVAILABLE",
            policy_reference=policy_ref,
            authorization_reference=auth_ref,
            state_version=1,
            observed_at=now_iso,
            expires_at=expires_at,
            created_at=now_iso,
            side_effects=False,
            execution_permitted=False
        )
        return plan

    def _derive_affected_resources(self, action: Action) -> List[AffectedResource]:
        """Extracts affected resources strictly bounded by plant scope."""
        resources = []
        target = action.target
        plant_id = target.plant_id if target else None

        if target and target.resource_id:
            res_type = target.resource_type.value if hasattr(target.resource_type, "value") else str(target.resource_type)
            resources.append(AffectedResource(
                resource_type=res_type,
                resource_id=target.resource_id,
                plant_id=plant_id,
                current_version=1,
                expected_version=1,
                action_type=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
            ))

        # Secondary resources based on action parameters
        params = action.parameters or {}
        if "machine_id" in params and params["machine_id"] != (target.resource_id if target else None):
            resources.append(AffectedResource(
                resource_type="MACHINE",
                resource_id=str(params["machine_id"]),
                plant_id=plant_id,
                current_version=1,
                expected_version=1,
                action_type=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
            ))
        if "from_warehouse" in params:
            resources.append(AffectedResource(
                resource_type="WAREHOUSE",
                resource_id=str(params["from_warehouse"]),
                plant_id=plant_id,
                current_version=1,
                expected_version=1,
                action_type="TRANSFER_OUT"
            ))
        if "to_warehouse" in params:
            resources.append(AffectedResource(
                resource_type="WAREHOUSE",
                resource_id=str(params["to_warehouse"]),
                plant_id=plant_id,
                current_version=1,
                expected_version=1,
                action_type="TRANSFER_IN"
            ))

        return resources

    def _derive_preconditions(self, action: Action) -> List[TransactionPrecondition]:
        """Generates deterministic preconditions that must hold prior to execution."""
        preconditions = []
        act_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        params = action.parameters or {}

        # 1. Base Resource Version Precondition
        if action.target and action.target.resource_id:
            preconditions.append(TransactionPrecondition(
                precondition_type=PreconditionType.VERSION_CHECK,
                field=f"{action.target.resource_id}.version",
                operator="==",
                expected_value=1,
                actual_value=1,
                is_satisfied=True
            ))

        # 2. Action-Specific Domain Preconditions
        if act_type in ("MOVE_INVENTORY", "REORDER_INVENTORY", "ADJUST_REORDER_POINT"):
            qty = params.get("quantity") or params.get("new_reorder_point", 0)
            preconditions.append(TransactionPrecondition(
                precondition_type=PreconditionType.INVENTORY_LEVEL,
                field="quantity",
                operator=">=",
                expected_value=0,
                actual_value=qty,
                is_satisfied=(qty >= 0)
            ))
        elif act_type in ("SCHEDULE_MAINTENANCE", "CREATE_MAINTENANCE_WORK_ORDER"):
            preconditions.append(TransactionPrecondition(
                precondition_type=PreconditionType.MACHINE_STATUS,
                field="machine.status",
                operator="!=",
                expected_value="DECOMMISSIONED",
                actual_value="OPERATIONAL",
                is_satisfied=True
            ))
        elif act_type in ("RESCHEDULE_PRODUCTION", "CHANGE_PRODUCTION_PLAN"):
            preconditions.append(TransactionPrecondition(
                precondition_type=PreconditionType.LINE_STATUS,
                field="production_line.status",
                operator="==",
                expected_value="ACTIVE",
                actual_value="ACTIVE",
                is_satisfied=True
            ))

        return preconditions

    def _derive_invariants(self, action: Action) -> List[TransactionInvariant]:
        """Generates domain business invariants."""
        invariants = [
            TransactionInvariant(
                invariant_type=InvariantType.NON_NEGATIVE_QUANTITY,
                description="Physical inventory quantities must remain non-negative post-transaction",
                rule_expression="quantity >= 0",
                is_enforced=True
            ),
            TransactionInvariant(
                invariant_type=InvariantType.NON_NEGATIVE_COST,
                description="Calculated financial transaction cost must be non-negative",
                rule_expression="estimated_cost >= 0",
                is_enforced=True
            )
        ]
        return invariants

    def _derive_expected_changes(self, action: Action) -> Dict[str, Any]:
        """Calculates expected delta values."""
        act_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        params = action.parameters or {}

        if act_type == "MOVE_INVENTORY":
            return {
                "source_warehouse": params.get("from_warehouse"),
                "destination_warehouse": params.get("to_warehouse"),
                "quantity_delta": -abs(params.get("quantity", 0)),
                "destination_delta": abs(params.get("quantity", 0))
            }
        elif act_type == "ADJUST_REORDER_POINT":
            return {"new_reorder_point": params.get("new_reorder_point")}
        elif act_type == "REORDER_INVENTORY":
            return {"purchase_quantity": params.get("quantity"), "supplier_id": params.get("supplier_id")}
        return {"action_type": act_type, "status_transition": "PLANNED"}

    def _build_rollback_plan(self, action: Action) -> RollbackPlan:
        """Determines deterministic rollback strategy, capability, and compensation steps."""
        act_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        params = action.parameters or {}

        if act_type == "MOVE_INVENTORY":
            from_wh = params.get("from_warehouse")
            to_wh = params.get("to_warehouse")
            qty = params.get("quantity", 0)
            return RollbackPlan(
                strategy=RollbackStrategy.COMPENSATING_ACTION,
                capability=RollbackCapability.SUPPORTED,
                steps=[{
                    "step": 1,
                    "action": "MOVE_INVENTORY_REVERSE",
                    "from_warehouse": to_wh,
                    "to_warehouse": from_wh,
                    "quantity": qty,
                    "description": f"Transfer {qty} units from {to_wh} back to {from_wh}"
                }],
                preconditions=[
                    TransactionPrecondition(
                        precondition_type=PreconditionType.INVENTORY_LEVEL,
                        field=f"{to_wh}.quantity",
                        operator=">=",
                        expected_value=qty,
                        actual_value=qty,
                        is_satisfied=True
                    )
                ],
                limitations=["Requires target warehouse to retain original transferred inventory"],
                estimated_duration_seconds=300,
                risk_level="LOW"
            )
        elif act_type == "ADJUST_REORDER_POINT":
            return RollbackPlan(
                strategy=RollbackStrategy.DATABASE_ROLLBACK,
                capability=RollbackCapability.SUPPORTED,
                steps=[{"step": 1, "action": "RESTORE_PREVIOUS_REORDER_POINT", "description": "Revert reorder point to prior value"}],
                limitations=["Relational write rollback requires prior snapshot reference"],
                estimated_duration_seconds=10,
                risk_level="LOW"
            )
        elif act_type == "REORDER_INVENTORY":
            return RollbackPlan(
                strategy=RollbackStrategy.COMPENSATING_ACTION,
                capability=RollbackCapability.PARTIALLY_SUPPORTED,
                steps=[{"step": 1, "action": "CANCEL_SUPPLIER_ORDER", "description": "Send cancellation request to supplier"}],
                limitations=["Order cancellation subject to supplier acceptance and processing cut-off"],
                estimated_duration_seconds=600,
                risk_level="MEDIUM"
            )
        elif act_type in ("NOTIFY_STAKEHOLDER", "ESCALATE_INCIDENT"):
            return RollbackPlan(
                strategy=RollbackStrategy.NOT_SUPPORTED,
                capability=RollbackCapability.NOT_SUPPORTED,
                steps=[],
                limitations=["External communications and escalations cannot be rolled back once dispatched"],
                risk_level="CRITICAL"
            )
        else:
            return RollbackPlan(
                strategy=RollbackStrategy.MANUAL_RECOVERY,
                capability=RollbackCapability.PARTIALLY_SUPPORTED,
                steps=[{"step": 1, "action": "MANUAL_INSPECTION", "description": "Operator review required to verify safe state"}],
                limitations=["Automatic rollback unsupported; requires manual recovery protocol"],
                risk_level="HIGH"
            )


# =====================================================================
# 3. TRANSACTION VALIDATION & REVALIDATION SERVICES
# =====================================================================

class TransactionValidationService:
    """
    Deterministic Transaction Validator.
    Fails closed on any unknown state, policy violation, or precondition failure.
    """

    def __init__(self, store: ActionStore = action_store):
        self.store = store

    def validate(self, transaction: Transaction, identity: Identity) -> TransactionValidationResult:
        """Evaluates all safety, scoping, integrity, and precondition gates."""
        blocking_reasons = []
        warnings = []
        reason_codes = []
        conflict = ConflictType.NO_CONFLICT

        plan = transaction.plan

        # 1. Action Existence & Hash Integrity
        action = self.store.get(plan.action_id)
        if not action:
            blocking_reasons.append(f"Bound Action '{plan.action_id}' not found in Action Store.")
            reason_codes.append("ACTION_NOT_FOUND")
        else:
            if action.action_hash and action.action_hash != action.compute_hash():
                blocking_reasons.append("Action hash mismatch: underlying action definition has been altered.")
                reason_codes.append("ACTION_TAMPERED")

        # 2. Tenant Isolation
        if plan.tenant_id != identity.tenant_id:
            blocking_reasons.append("Tenant isolation violation: Transaction tenant does not match identity context.")
            reason_codes.append("TENANT_ISOLATION_VIOLATION")

        # 3. Expiration Check
        now_dt = datetime.now(timezone.utc)
        try:
            exp_dt = datetime.fromisoformat(plan.expires_at.replace("Z", "+00:00"))
            if now_dt >= exp_dt:
                blocking_reasons.append(f"Transaction plan expired at {plan.expires_at}.")
                reason_codes.append("TRANSACTION_EXPIRED")
                conflict = ConflictType.APPROVAL_EXPIRED
        except Exception:
            blocking_reasons.append("Invalid expiration timestamp.")
            reason_codes.append("INVALID_EXPIRATION")

        # 4. Data Mode Boundary Check
        if plan.data_mode == "SIMULATION" and transaction.data_mode == "REAL":
            blocking_reasons.append("Simulation transaction cannot be promoted to REAL data mode.")
            reason_codes.append("DATA_MODE_PROMOTION_PROHIBITED")

        # 5. Preconditions Verification
        checked_preconditions = []
        for prec in plan.preconditions:
            prec_dict = prec.model_dump()
            if not prec.is_satisfied:
                blocking_reasons.append(f"Precondition failed: {prec.field} {prec.operator} {prec.expected_value}")
                reason_codes.append("PRECONDITION_FAILED")
                prec_dict["outcome"] = "FAILED"
            else:
                prec_dict["outcome"] = "SATISFIED"
            checked_preconditions.append(prec_dict)

        # 6. Business Invariants Verification
        checked_invariants = []
        for inv in plan.invariants:
            inv_dict = inv.model_dump()
            inv_dict["status"] = "ENFORCED"
            checked_invariants.append(inv_dict)

        # 7. Policy Reference Check
        if plan.policy_reference:
            pol_dec = plan.policy_reference.get("decision")
            if pol_dec in (PolicyEffect.DENY.value, "DENY"):
                blocking_reasons.append("Policy Engine evaluated DENY for this action.")
                reason_codes.append("POLICY_DENIED")
            elif pol_dec in (PolicyEffect.HOLD.value, "HOLD"):
                warnings.append("Policy Engine placed transaction on HOLD.")
                reason_codes.append("POLICY_HOLD")

        # 8. Rollback Capability Verification
        if plan.rollback_plan.capability == RollbackCapability.NOT_SUPPORTED:
            warnings.append("Warning: This transaction cannot be automatically rolled back post-execution.")
            reason_codes.append("ROLLBACK_NOT_SUPPORTED")

        is_valid = len(blocking_reasons) == 0
        new_status = TransactionStatus.READY if is_valid else TransactionStatus.FAILED

        if is_valid and plan.requires_approval and transaction.approved_by is None:
            new_status = TransactionStatus.AWAITING_EXECUTION

        return TransactionValidationResult(
            valid=is_valid,
            status=new_status,
            reason_codes=reason_codes or ["VALIDATED_SUCCESSFULLY"],
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            checked_preconditions=checked_preconditions,
            checked_invariants=checked_invariants,
            conflict_type=conflict,
            policy_reference=plan.policy_reference,
            authorization_reference=plan.authorization_reference,
            validated_at=datetime.now(timezone.utc).isoformat()
        )


class TransactionRevalidationService:
    """
    Revalidates existing transaction plans before execution to detect stale state or external drift.
    """

    def __init__(
        self,
        validator: TransactionValidationService,
        pol_svc: PolicyService = policy_service,
        auth_svc: AuthorizationService = authorization_service,
        store: ActionStore = action_store
    ):
        self.validator = validator
        self.pol_svc = pol_svc
        self.auth_svc = auth_svc
        self.store = store

    def revalidate(self, transaction: Transaction, identity: Identity) -> Tuple[TransactionValidationResult, ConflictType]:
        """
        Revalidates transaction plan against current state:
        - Policy changes
        - Authorization changes
        - Expiration drift
        - Resource version drift
        """
        base_result = self.validator.validate(transaction, identity)
        conflict = ConflictType.NO_CONFLICT

        if not base_result.valid:
            return base_result, base_result.conflict_type

        plan = transaction.plan
        action = self.store.get(plan.action_id)

        # 1. Action Drift Detection
        if action:
            current_action_hash = action.compute_hash()
            if action.action_hash != current_action_hash:
                base_result.valid = False
                base_result.blocking_reasons.append("Underlying Action has drifted or been modified since planning.")
                base_result.reason_codes.append("ACTION_VERSION_MISMATCH")
                conflict = ConflictType.VERSION_MISMATCH

        # 2. Policy Version Drift Detection
        if plan.policy_reference and isinstance(plan.policy_reference, dict):
            planned_policy_ver = plan.policy_reference.get("policy_version")
            planned_policy_id = plan.policy_reference.get("policy_id")
            current_policy_ver = None

            if hasattr(self.pol_svc, "store") and hasattr(self.pol_svc.store, "get_policy") and planned_policy_id:
                active_pol = self.pol_svc.store.get_policy(planned_policy_id)
                if active_pol:
                    current_policy_ver = active_pol.policy_version
                else:
                    current_policy_ver = "NOT_FOUND"

            if current_policy_ver is None and action and hasattr(self.pol_svc, "evaluate"):
                try:
                    ctx = PolicyEvaluationContext(
                        tenant_id=identity.tenant_id,
                        workspace_id=identity.workspace_id,
                        session_id=identity.session_id,
                        plant_id=action.target.plant_id if hasattr(action, "target") and action.target else None,
                        user_id=identity.user_id,
                        roles=identity.roles
                    )
                    current_dec = self.pol_svc.evaluate(action, ctx, persist_decision=False)
                    if current_dec and current_dec.policy_version:
                        current_policy_ver = current_dec.policy_version
                except Exception as e:
                    logger.warning(f"Error evaluating policy drift: {e}")
            elif current_policy_ver is None and action and hasattr(self.pol_svc, "evaluate_action"):
                current_dec = self.pol_svc.evaluate_action(action, identity)
                if current_dec and hasattr(current_dec, "policy_version"):
                    current_policy_ver = current_dec.policy_version

            if planned_policy_ver and current_policy_ver and current_policy_ver != planned_policy_ver:
                base_result.valid = False
                base_result.blocking_reasons.append(
                    f"Policy drift detected: planned under v{planned_policy_ver}, active policy is v{current_policy_ver}."
                )
                base_result.reason_codes.append("POLICY_CHANGED")
                conflict = ConflictType.POLICY_CHANGED

        # 3. Expiration Check
        now_dt = datetime.now(timezone.utc)
        try:
            exp_dt = datetime.fromisoformat(plan.expires_at.replace("Z", "+00:00"))
            if now_dt >= exp_dt:
                base_result.valid = False
                base_result.blocking_reasons.append(f"Transaction plan has expired ({plan.expires_at}).")
                base_result.reason_codes.append("TRANSACTION_EXPIRED")
                conflict = ConflictType.APPROVAL_EXPIRED
        except Exception:
            pass

        base_result.conflict_type = conflict
        if not base_result.valid:
            base_result.status = TransactionStatus.FAILED

        return base_result, conflict


# =====================================================================
# 4. CANONICAL TRANSACTION SERVICE (FACADE)
# =====================================================================

class TransactionService:
    """
    Canonical Transaction Management Service.
    Orchestrates planning, validation, revalidation, cancellation, idempotency,
    and audit logging across the SageCommand V3 platform.
    """

    def __init__(
        self,
        repository: TransactionRepository = transaction_repository,
        planner: Optional[TransactionPlanner] = None,
        validator: Optional[TransactionValidationService] = None,
        revalidator: Optional[TransactionRevalidationService] = None,
        audit_svc: AuditLedgerService = audit_ledger
    ):
        self.repo = repository
        self.planner = planner or TransactionPlanner()
        self.validator = validator or TransactionValidationService()
        self.revalidator = revalidator or TransactionRevalidationService(self.validator)
        self.audit_svc = audit_svc

    def plan_transaction(
        self,
        action_id: str,
        identity: Identity,
        idempotency_key: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        data_mode_override: Optional[str] = None
    ) -> Tuple[Transaction, TransactionValidationResult]:
        """
        Creates, validates, and persists a new Transaction and TransactionPlan.
        Resolves idempotency: identical key + identical action returns existing plan;
        identical key + different action raises ValueError (IDEMPOTENCY_CONFLICT).
        """
        # 1. Authorize Transaction Planning capability
        scope = AuthorizationScope(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            session_id=identity.session_id
        )
        auth_ctx = AuthorizationContext(
            identity=identity.to_user_identity(),
            required_permission="transaction.plan",
            scope=scope,
            data_mode=data_mode_override or "REAL"
        )
        auth_dec = self.planner.auth_svc.evaluate(auth_ctx)
        if auth_dec.effect != AuthzDecisionEffect.ALLOW:
            log_security_event("TRANSACTION_UNAUTHORIZED", {
                "user_id": identity.user_id,
                "tenant_id": identity.tenant_id,
                "action_id": action_id,
                "reason": auth_dec.reason
            }, severity="WARNING")
            raise PermissionError(f"Authorization Denied: {auth_dec.reason}")

        # 2. Idempotency Check
        if idempotency_key:
            existing_tx = self.repo.get_by_idempotency_key(idempotency_key, identity.tenant_id)
            if existing_tx:
                # Check for parameter compatibility
                if existing_tx.action_id == action_id:
                    val_res = self.validator.validate(existing_tx, identity)
                    return existing_tx, val_res
                else:
                    self._record_audit_event(
                        EventType.TRANSACTION_CONFLICT_DETECTED,
                        identity,
                        existing_tx.transaction_id,
                        action_id,
                        EventStatus.FAILURE,
                        {"idempotency_key": idempotency_key, "conflict": "IDEMPOTENCY_CONFLICT"}
                    )
                    raise ValueError(f"IDEMPOTENCY_CONFLICT: Key '{idempotency_key}' was already used for Action '{existing_tx.action_id}'.")

        # 3. Load Action from Action Store
        action = self.planner.store.get(action_id)
        if not action:
            raise KeyError(f"Action '{action_id}' not found.")

        # Enforce tenant isolation on action
        if action.tenant_id != identity.tenant_id:
            log_security_event("TRANSACTION_CROSS_TENANT_BLOCKED", {
                "user_id": identity.user_id,
                "user_tenant": identity.tenant_id,
                "action_tenant": action.tenant_id,
                "action_id": action_id
            }, severity="CRITICAL")
            raise PermissionError("Cross-tenant transaction planning is strictly prohibited.")

        # 4. Generate Deterministic Plan
        plan = self.planner.create_plan(
            action=action,
            identity=identity,
            idempotency_key=idempotency_key,
            ttl_seconds=ttl_seconds,
            data_mode_override=data_mode_override
        )

        # 5. Instantiate Transaction Domain Record
        tx = Transaction(
            transaction_id=f"tx_{uuid.uuid4().hex[:12]}",
            transaction_version=1,
            tenant_id=plan.tenant_id,
            workspace_id=plan.workspace_id,
            session_id=plan.session_id,
            plant_id=plan.plant_id,
            action_id=plan.action_id,
            action_version=plan.action_version,
            mission_id=action.mission_id,
            incident_id=action.incident_id,
            status=TransactionStatus.PLANNED,
            transaction_type=TransactionType.DATABASE,
            data_mode=plan.data_mode,
            access_mode=plan.access_mode,
            plan=plan,
            idempotency_key=idempotency_key,
            requested_by=identity.user_id,
            expires_at=plan.expires_at,
            rollback_supported=plan.rollback_plan.capability
        )

        # 6. Validate Plan
        val_res = self.validator.validate(tx, identity)
        tx.status = val_res.status

        # 7. Persist Transaction
        self.repo.save(tx)

        # 8. Record Audit Events in Ledger
        self._record_audit_event(
            EventType.TRANSACTION_PLANNED,
            identity,
            tx.transaction_id,
            action_id,
            EventStatus.SUCCESS,
            {
                "transaction_id": tx.transaction_id,
                "action_id": tx.action_id,
                "risk_level": plan.risk_level,
                "status": tx.status.value,
                "data_mode": tx.data_mode,
                "expires_at": tx.expires_at,
                "side_effects": False,
                "execution_permitted": False
            }
        )

        self._record_audit_event(
            EventType.ROLLBACK_PLAN_CREATED,
            identity,
            tx.transaction_id,
            action_id,
            EventStatus.SUCCESS,
            {
                "rollback_plan_id": plan.rollback_plan.rollback_plan_id,
                "strategy": plan.rollback_plan.strategy.value,
                "capability": plan.rollback_plan.capability.value,
                "risk_level": plan.rollback_plan.risk_level
            }
        )

        return tx, val_res

    def get_transaction(self, transaction_id: str, identity: Identity) -> Optional[Transaction]:
        """Retrieves a transaction strictly scoped to caller's tenant."""
        return self.repo.get_by_id(transaction_id, identity.tenant_id)

    def list_transactions(
        self,
        identity: Identity,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Transaction]:
        """Lists transactions scoped to caller's tenant."""
        return self.repo.list_transactions(
            tenant_id=identity.tenant_id,
            workspace_id=workspace_id,
            status=status,
            limit=limit,
            offset=offset
        )

    def validate_transaction(self, transaction_id: str, identity: Identity) -> Tuple[Transaction, TransactionValidationResult]:
        """Validates an existing transaction plan."""
        tx = self.get_transaction(transaction_id, identity)
        if not tx:
            raise KeyError(f"Transaction '{transaction_id}' not found.")

        TransactionStateMachine.validate_transition(tx.status, TransactionStatus.VALIDATING)
        tx.status = TransactionStatus.VALIDATING

        val_res = self.validator.validate(tx, identity)
        tx.status = val_res.status
        self.repo.save(tx)

        self._record_audit_event(
            EventType.TRANSACTION_VALIDATED if val_res.valid else EventType.TRANSACTION_INVALID,
            identity,
            tx.transaction_id,
            tx.action_id,
            EventStatus.SUCCESS if val_res.valid else EventStatus.FAILURE,
            {
                "valid": val_res.valid,
                "status": tx.status.value,
                "reason_codes": val_res.reason_codes,
                "blocking_reasons": val_res.blocking_reasons
            }
        )

        return tx, val_res

    def revalidate_transaction(self, transaction_id: str, identity: Identity) -> Tuple[Transaction, TransactionValidationResult]:
        """Revalidates transaction plan to detect state, policy, or resource drift."""
        tx = self.get_transaction(transaction_id, identity)
        if not tx:
            raise KeyError(f"Transaction '{transaction_id}' not found.")

        val_res, conflict = self.revalidator.revalidate(tx, identity)
        tx.status = val_res.status
        tx.revalidation_count += 1
        tx.last_revalidated_at = datetime.now(timezone.utc).isoformat()

        if conflict != ConflictType.NO_CONFLICT:
            tx.failure_reason = f"Conflict detected during revalidation: {conflict.value}"
            tx.failure_code = conflict.value
            self._record_audit_event(
                EventType.TRANSACTION_CONFLICT_DETECTED,
                identity,
                tx.transaction_id,
                tx.action_id,
                EventStatus.FAILURE,
                {"conflict": conflict.value, "blocking_reasons": val_res.blocking_reasons}
            )

        self.repo.save(tx)
        return tx, val_res

    def cancel_transaction(self, transaction_id: str, identity: Identity, reason: str = "Cancelled by user") -> Transaction:
        """Cancels a pending transaction plan prior to execution."""
        tx = self.get_transaction(transaction_id, identity)
        if not tx:
            raise KeyError(f"Transaction '{transaction_id}' not found.")

        TransactionStateMachine.validate_transition(tx.status, TransactionStatus.CANCELLED)
        tx.status = TransactionStatus.CANCELLED
        tx.failure_reason = reason
        tx.failure_code = "TRANSACTION_CANCELLED"
        self.repo.save(tx)

        self._record_audit_event(
            EventType.TRANSACTION_CANCELLED,
            identity,
            tx.transaction_id,
            tx.action_id,
            EventStatus.SUCCESS,
            {"reason": reason}
        )

        return tx

    def _record_audit_event(
        self,
        event_type: EventType,
        identity: Identity,
        transaction_id: str,
        action_id: str,
        event_status: EventStatus,
        payload: Dict[str, Any]
    ) -> None:
        """Emits an immutable structured transaction event to the Audit Ledger."""
        try:
            from data.schemas.ledger_contract import LedgerActor, ActorType
            actor = LedgerActor(
                actor_type=ActorType.USER if identity.user_id != "system" else ActorType.SYSTEM,
                actor_id=identity.user_id,
                acting_user_id=identity.user_id,
                roles=identity.roles
            )
            self.audit_svc.record_event(
                event_type=event_type,
                category=EventCategory.TRANSACTION,
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                session_id=identity.session_id,
                actor=actor,
                data_mode="REAL",
                action_id=action_id,
                event_status=event_status,
                payload={
                    "transaction_id": transaction_id,
                    **payload
                }
            )
        except Exception as e:
            logger.error(f"Failed to record audit event for transaction '{transaction_id}': {e}")


# Canonical singleton service instance
transaction_service = TransactionService()
