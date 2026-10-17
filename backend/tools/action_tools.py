# backend/tools/action_tools.py
"""
SageCommand V3 — Agent Action Tools
Enables LangGraph agents to propose, validate, and simulate structured actions
without directly generating or executing raw operational SQL statements.
"""

import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

logger = logging.getLogger("sagecommand.action_tools")


try:
    from core.auth import Identity
    from data.schemas.action_contract import (
        Action,
        ActionType,
        ResourceType,
        ActionTarget,
        ActionReason,
        ActionProvenance,
        CostEstimate,
        ActionStatus,
        RiskLevel,
    )
    from services.action_registry import action_registry
    from services.action_validator import action_validator
    from services.action_store import action_store
    from services.policy_service import policy_service
    from data.schemas.policy_contract import PolicyEvaluationContext
    from data.schemas.autonomy_contract import AutonomyScope, AutonomyDecisionEffect, SubjectType
    from services.autonomy_service import autonomy_service
    from tools.autonomy_context import get_active_autonomy_identity, get_active_autonomy_subject
except ModuleNotFoundError:
    from backend.core.auth import Identity
    from backend.data.schemas.action_contract import (
        Action,
        ActionType,
        ResourceType,
        ActionTarget,
        ActionReason,
        ActionProvenance,
        CostEstimate,
        ActionStatus,
        RiskLevel,
    )
    from backend.services.action_registry import action_registry
    from backend.services.action_validator import action_validator
    from backend.services.action_store import action_store
    from backend.services.policy_service import policy_service
    from backend.data.schemas.policy_contract import PolicyEvaluationContext
    from backend.data.schemas.autonomy_contract import AutonomyScope, AutonomyDecisionEffect, SubjectType
    from backend.services.autonomy_service import autonomy_service
    from backend.tools.autonomy_context import get_active_autonomy_identity, get_active_autonomy_subject



def is_plant_authorized(identity: Identity, plant_id: Optional[str]) -> bool:
    """
    Validates requested target plant against authenticated identity's authoritative plant assignments.
    Strictly fail-closed:
    - Target plant must not be empty or wildcard.
    - Identity must have non-empty assigned_plants.
    - Wildcard '*' in identity.assigned_plants grants admin access to any specific plant.
    - Otherwise, requested plant must explicitly be in identity.assigned_plants.
    """
    if not plant_id or not str(plant_id).strip():
        return False
    clean_plant = str(plant_id).strip()
    if clean_plant == "*":
        return False  # Tool argument plant_id="*" is never allowed as target authorization

    raw_plants = getattr(identity, "assigned_plants", None)
    if not raw_plants or not isinstance(raw_plants, (list, set, tuple)):
        return False
    user_plants = set(raw_plants)
    if "*" in user_plants:
        return True
    return clean_plant in user_plants


@tool
def propose_action(
    action_type: str,
    resource_type: str,
    resource_id: str,
    parameters: Dict[str, Any],
    reason: str,
    reason_code: str = "OPERATIONAL_RECOVERY",
    estimated_cost_usd: float = 0.0,
    estimated_duration_minutes: int = 0,
    tenant_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    plant_id: Optional[str] = None
) -> str:
    """
    Proposes a typed, validated industrial action instead of raw operational SQL.
    Available Action Types:
      ADJUST_REORDER_POINT, REORDER_INVENTORY, MOVE_INVENTORY,
      SCHEDULE_MAINTENANCE, CREATE_MAINTENANCE_WORK_ORDER, RESCHEDULE_PRODUCTION,
      CHANGE_PRODUCTION_PLAN, UPDATE_SUPPLIER_ORDER, ESCALATE_INCIDENT,
      NOTIFY_STAKEHOLDER, UPDATE_SLA_PRIORITY.
    """
    try:
        # Require trusted authenticated autonomy identity (Prompt 38C)
        active_ident = get_active_autonomy_identity()
        if not active_ident:
            return (
                "ACTION PROPOSAL BLOCKED: Authenticated autonomy context is required. "
                "No active trusted identity found in server execution context."
            )

        auth_ident = active_ident
        auth_tenant = auth_ident.tenant_id
        auth_workspace = getattr(auth_ident, "workspace_id", None)
        if not auth_workspace or not str(auth_workspace).strip():
            return "ACTION PROPOSAL BLOCKED: Authenticated identity lacks required workspace scope."
        auth_workspace = str(auth_workspace).strip()
        auth_session = getattr(auth_ident, "session_id", None)

        # Reject forged context arguments if provided
        if tenant_id is not None and str(tenant_id).strip() != str(auth_tenant).strip():
            return (
                f"ACTION PROPOSAL BLOCKED: Forged tenant context detected. "
                f"Tool argument tenant_id '{tenant_id}' does not match authenticated tenant '{auth_tenant}'."
            )
        if workspace_id is not None and str(workspace_id).strip() != auth_workspace:
            return (
                f"ACTION PROPOSAL BLOCKED: Forged workspace context detected. "
                f"Tool argument workspace_id '{workspace_id}' does not match authenticated workspace '{auth_workspace}'."
            )
        if session_id is not None:
            if not auth_session:
                return (
                    f"ACTION PROPOSAL BLOCKED: Forged session context detected. "
                    f"Tool argument session_id '{session_id}' cannot substitute for unauthenticated session."
                )
            if str(session_id).strip() != str(auth_session).strip():
                return (
                    f"ACTION PROPOSAL BLOCKED: Forged session context detected. "
                    f"Tool argument session_id '{session_id}' does not match authenticated session '{auth_session}'."
                )

        # Validate target plant scope against trusted identity before autonomy evaluation
        if not plant_id or not str(plant_id).strip():
            return "ACTION PROPOSAL BLOCKED: Missing target plant scope. A specific authorized plant_id must be provided."

        clean_plant = str(plant_id).strip()
        if clean_plant == "*":
            return "ACTION PROPOSAL BLOCKED: Wildcard plant identifier is not permitted for action proposal."

        if not is_plant_authorized(auth_ident, clean_plant):
            user_plants = getattr(auth_ident, "assigned_plants", None) or []
            return (
                f"ACTION PROPOSAL BLOCKED: Unauthorized plant scope. "
                f"Caller '{auth_ident.user_id}' is assigned to {user_plants}, but requested plant '{clean_plant}' is not authorized."
            )

        # 1. Parse and validate ActionType
        try:
            act_type_enum = ActionType(action_type.upper().strip())
        except ValueError:
            valid_types = [a.value for a in ActionType]
            return f"Error: Invalid action_type '{action_type}'. Must be one of: {', '.join(valid_types)}"

        # 2. Parse and validate ResourceType
        try:
            res_type_enum = ResourceType(resource_type.upper().strip())
        except ValueError:
            valid_resources = [r.value for r in ResourceType]
            return f"Error: Invalid resource_type '{resource_type}'. Must be one of: {', '.join(valid_resources)}"

        # 3. Build domain components using authoritative identity
        target = ActionTarget(
            resource_type=res_type_enum,
            resource_id=resource_id.strip(),
            tenant_id=auth_tenant,
            workspace_id=auth_workspace,
            plant_id=clean_plant
        )

        cost = CostEstimate(value=float(estimated_cost_usd), currency="USD") if estimated_cost_usd > 0 else None

        reason_obj = ActionReason(
            summary=reason.strip(),
            justification=f"Autonomous recommendation generated by agent reasoning for {resource_id}.",
            reason_code=reason_code.strip()
        )

        provenance = ActionProvenance(
            requested_by_user_id=auth_ident.user_id,
            source="AGENT",
            model_name="agent-evaluator-v3",
            reasoning_trace=reason
        )

        # 4. Classify risk deterministically
        system_risk = action_registry.classify_risk(
            action_type=act_type_enum,
            target=target,
            parameters=parameters,
            cost_estimate=cost
        )
        requires_approval = system_risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]

        # 4a. Autonomy Evaluation Boundary
        subj_type, subj_id = get_active_autonomy_subject()

        autonomy_scope = AutonomyScope(
            tenant_id=auth_tenant,
            workspace_id=auth_workspace,
            session_id=auth_session,
            plant_id=clean_plant
        )

        autonomy_dec = autonomy_service.evaluate_autonomy(
            identity=auth_ident,
            subject_type=subj_type,
            subject_id=subj_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=autonomy_scope,
            data_mode="REAL",
            risk_context={
                "action_type": act_type_enum.value,
                "target_resource_id": target.resource_id if target else None,
                "parameters": parameters,
                "cost_estimate_usd": float(estimated_cost_usd) if estimated_cost_usd is not None else None,
                "risk_level": system_risk.value,
                "proposer_id": auth_ident.user_id,
            }
        )

        if autonomy_dec.decision != AutonomyDecisionEffect.ALLOW:
            return (
                f"ACTION PROPOSAL BLOCKED BY AUTONOMY GOVERNANCE:\n"
                f"Decision: {autonomy_dec.decision.value}\n"
                f"Reason Code: {autonomy_dec.reason_code.value}\n"
                f"Explanation: {autonomy_dec.reason}"
            )

        action = Action(
            tenant_id=auth_tenant,
            workspace_id=auth_workspace,
            session_id=auth_session,
            action_type=act_type_enum,
            version="1.0",
            target=target,
            parameters=parameters,
            reason=reason_obj,
            data_mode="REAL",
            system_risk_level=system_risk,
            requires_approval=requires_approval,
            estimated_cost=cost,
            estimated_duration_minutes=estimated_duration_minutes if estimated_duration_minutes > 0 else 15,
            requested_by=auth_ident.user_id,
            provenance=provenance,
            status=ActionStatus.PROPOSED
        )

        # 5. Execute two-layer validation using authoritative identity
        is_valid, checks = action_validator.validate_all(action, auth_ident)
        failed_checks = [c for c in checks if c.status == "FAIL"]

        if not is_valid:
            action.status = ActionStatus.REJECTED
            fail_reasons = "\n".join([f"- {c.name}: {c.message}" for c in failed_checks])
            return f"ACTION REJECTED BY VALIDATION ENGINE:\n{fail_reasons}"

        # 6. Store proposed action
        action_store.save(action)

        return (
            f"ACTION PROPOSED SUCCESSFULLY:\n"
            f"Action ID: {action.action_id}\n"
            f"Type: {action.action_type.value}\n"
            f"Target: {action.target.resource_id} ({action.target.resource_type.value})\n"
            f"Deterministic Risk: {action.system_risk_level.value}\n"
            f"Requires Human Approval: {'YES' if action.requires_approval else 'NO'}\n"
            f"Status: {action.status.value}\n\n"
            f"Preview:\n{action.generate_human_preview()}"
        )

    except Exception as e:
        logger.error("Internal error proposing action: %s", type(e).__name__, exc_info=True)
        return "ACTION PROPOSAL FAILED: An internal error occurred while processing the action proposal."


@tool
def preview_action_impact(
    action_id: str,
    tenant_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Generates a safe simulation of the expected effects and impact of a proposed action."""
    try:
        active_ident = get_active_autonomy_identity()
        if not active_ident:
            return (
                "ACTION PREVIEW BLOCKED: Authenticated autonomy context is required. "
                "No active trusted identity found in server execution context."
            )

        auth_ident = active_ident
        auth_tenant = auth_ident.tenant_id
        auth_workspace = getattr(auth_ident, "workspace_id", None)
        auth_session = getattr(auth_ident, "session_id", None)

        # Anti-forgery checks on optional caller-supplied context arguments
        if tenant_id is not None and str(tenant_id).strip() != str(auth_tenant).strip():
            return (
                f"ACTION PREVIEW BLOCKED: Forged tenant context detected. "
                f"Tool argument tenant_id '{tenant_id}' does not match authenticated tenant '{auth_tenant}'."
            )
        if workspace_id is not None:
            if not auth_workspace or str(workspace_id).strip() != str(auth_workspace).strip():
                return (
                    f"ACTION PREVIEW BLOCKED: Forged workspace context detected. "
                    f"Tool argument workspace_id '{workspace_id}' does not match authenticated workspace '{auth_workspace}'."
                )
        if session_id is not None:
            if not auth_session:
                return (
                    f"ACTION PREVIEW BLOCKED: Forged session context detected. "
                    f"Tool argument session_id '{session_id}' cannot substitute for unauthenticated session."
                )
            if str(session_id).strip() != str(auth_session).strip():
                return (
                    f"ACTION PREVIEW BLOCKED: Forged session context detected. "
                    f"Tool argument session_id '{session_id}' does not match authenticated session '{auth_session}'."
                )

        # Retrieve action strictly within trusted tenant (non-disclosing error if missing/cross-tenant)
        action = action_store.get_by_id(action_id, auth_tenant)
        if not action:
            return f"ACTION PREVIEW BLOCKED: Action '{action_id}' not found."

        # Validate workspace scope (Prompt 38E: mandatory matching)
        if not auth_workspace or not str(auth_workspace).strip():
            return "ACTION PREVIEW BLOCKED: Authenticated identity lacks required workspace scope."
        clean_auth_workspace = str(auth_workspace).strip()

        act_workspace = getattr(action, "workspace_id", None)
        if not act_workspace or not str(act_workspace).strip():
            return f"ACTION PREVIEW BLOCKED: Missing stored action workspace scope. Action '{action_id}' lacks a valid workspace."
        clean_act_workspace = str(act_workspace).strip()

        if clean_act_workspace != clean_auth_workspace:
            return f"ACTION PREVIEW BLOCKED: Workspace scope mismatch. Action '{action_id}' does not belong to workspace '{clean_auth_workspace}'."

        # Validate session scope for session-bound actions
        act_session = getattr(action, "session_id", None)
        if act_session and str(act_session).strip():
            clean_act_sess = str(act_session).strip()
            if not auth_session or not str(auth_session).strip():
                return (
                    f"ACTION PREVIEW BLOCKED: Session mismatch. "
                    f"Action '{action_id}' is session-bound, but authenticated identity has no active session."
                )
            if str(auth_session).strip() != clean_act_sess:
                return (
                    f"ACTION PREVIEW BLOCKED: Session mismatch. "
                    f"Action '{action_id}' belongs to session '{clean_act_sess}', not '{auth_session}'."
                )

        # Validate plant scope
        act_plant = action.target.plant_id if action.target else None
        if not is_plant_authorized(auth_ident, act_plant):
            return (
                f"ACTION PREVIEW BLOCKED: Plant scope denied. "
                f"Caller '{auth_ident.user_id}' is not authorized for target plant '{act_plant}'."
            )

        sim = action_validator.generate_simulation(action)
        effects_str = "\n".join([
            f"- Resource: {e.resource} | Field: {e.field} | Before: {e.before} -> After: {e.after}"
            for e in sim.expected_effects
        ])
        return (
            f"SIMULATION PREVIEW for {action.action_id} ({action.action_type.value}):\n"
            f"Expected Effects:\n{effects_str}\n\n"
            f"Estimated Impact:\n{sim.estimated_impact}\n"
            f"Note: This was a simulated preview. Live state has not been modified."
        )
    except Exception as e:
        logger.error("Internal error previewing action impact: %s", type(e).__name__, exc_info=True)
        return "ACTION PREVIEW FAILED: An internal error occurred while generating action preview."


@tool
def list_supported_actions() -> str:
    """Lists all 11 supported action types with parameter schemas and risk tiers."""
    lines = ["SAGECOMMAND V3 SUPPORTED ACTION TYPES:"]
    for defn in action_registry.list_definitions():
        lines.append(
            f"\n• {defn.action_type.value} (Default Risk: {defn.default_risk.value})\n"
            f"  Description: {defn.description}\n"
            f"  Allowed Targets: {', '.join([t.value for t in defn.allowed_resource_types])}\n"
            f"  Rollback: {defn.rollback_capability.value}"
        )
    return "\n".join(lines)


@tool
def check_action_policy(
    action_id: str,
    tenant_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Evaluates an existing proposed action against active system policies and returns the governance decision."""
    try:
        active_ident = get_active_autonomy_identity()
        if not active_ident:
            return (
                "ACTION POLICY CHECK BLOCKED: Authenticated autonomy context is required. "
                "No active trusted identity found in server execution context."
            )

        auth_ident = active_ident
        auth_tenant = auth_ident.tenant_id
        auth_workspace = getattr(auth_ident, "workspace_id", None)
        auth_session = getattr(auth_ident, "session_id", None)

        # Anti-forgery checks on optional caller-supplied context arguments
        if tenant_id is not None and str(tenant_id).strip() != str(auth_tenant).strip():
            return (
                f"ACTION POLICY CHECK BLOCKED: Forged tenant context detected. "
                f"Tool argument tenant_id '{tenant_id}' does not match authenticated tenant '{auth_tenant}'."
            )
        if workspace_id is not None:
            if not auth_workspace or str(workspace_id).strip() != str(auth_workspace).strip():
                return (
                    f"ACTION POLICY CHECK BLOCKED: Forged workspace context detected. "
                    f"Tool argument workspace_id '{workspace_id}' does not match authenticated workspace '{auth_workspace}'."
                )
        if session_id is not None:
            if not auth_session:
                return (
                    f"ACTION POLICY CHECK BLOCKED: Forged session context detected. "
                    f"Tool argument session_id '{session_id}' cannot substitute for unauthenticated session."
                )
            if str(session_id).strip() != str(auth_session).strip():
                return (
                    f"ACTION POLICY CHECK BLOCKED: Forged session context detected. "
                    f"Tool argument session_id '{session_id}' does not match authenticated session '{auth_session}'."
                )

        # Retrieve action strictly within trusted tenant (non-disclosing error if missing/cross-tenant)
        action = action_store.get_by_id(action_id, auth_tenant)
        if not action:
            return f"ACTION POLICY CHECK BLOCKED: Action '{action_id}' not found."

        # Validate workspace scope (Prompt 38E: mandatory matching)
        if not auth_workspace or not str(auth_workspace).strip():
            return "ACTION POLICY CHECK BLOCKED: Authenticated identity lacks required workspace scope."
        clean_auth_workspace = str(auth_workspace).strip()

        act_workspace = getattr(action, "workspace_id", None)
        if not act_workspace or not str(act_workspace).strip():
            return f"ACTION POLICY CHECK BLOCKED: Missing stored action workspace scope. Action '{action_id}' lacks a valid workspace."
        clean_act_workspace = str(act_workspace).strip()

        if clean_act_workspace != clean_auth_workspace:
            return f"ACTION POLICY CHECK BLOCKED: Workspace scope mismatch. Action '{action_id}' does not belong to workspace '{clean_auth_workspace}'."

        # Validate session scope (Prompt 38E: explicit truthful session representation, no session_default)
        act_session = getattr(action, "session_id", None)
        clean_act_sess = str(act_session).strip() if (act_session and str(act_session).strip()) else None
        clean_auth_sess = str(auth_session).strip() if (auth_session and str(auth_session).strip()) else None

        if clean_act_sess:
            if not clean_auth_sess:
                return (
                    f"ACTION POLICY CHECK BLOCKED: Session mismatch. "
                    f"Action '{action_id}' is session-bound, but authenticated identity has no active session."
                )
            if clean_auth_sess != clean_act_sess:
                return (
                    f"ACTION POLICY CHECK BLOCKED: Session mismatch. "
                    f"Action '{action_id}' belongs to session '{clean_act_sess}', not '{auth_session}'."
                )

        effective_session = clean_act_sess or clean_auth_sess
        if not effective_session:
            return "ACTION POLICY CHECK BLOCKED: Missing authoritative session scope. Policy evaluation requires a valid session context."

        # Validate plant scope
        act_plant = action.target.plant_id if action.target else None
        if not is_plant_authorized(auth_ident, act_plant):
            return (
                f"ACTION POLICY CHECK BLOCKED: Plant scope denied. "
                f"Caller '{auth_ident.user_id}' is not authorized for target plant '{act_plant}'."
            )

        # Build PolicyEvaluationContext strictly from trusted identity and authoritative action data
        context = PolicyEvaluationContext(
            tenant_id=auth_tenant,
            workspace_id=clean_act_workspace,
            session_id=effective_session,
            user_id=auth_ident.user_id,
            plant_id=act_plant,
            roles=list(auth_ident.roles or []),
            permissions=list(getattr(auth_ident, "permissions", []) or []),
            data_mode=action.data_mode
        )

        decision = policy_service.evaluate(action=action, context=context, persist_decision=True)
        approval_str = f"Yes ({decision.approval_requirement.reason})" if decision.requires_approval and decision.approval_requirement else ("Yes" if decision.requires_approval else "No")

        return (
            f"POLICY EVALUATION RESULT for {action.action_id}:\n"
            f"Decision: {decision.decision.value}\n"
            f"Governing Policy: {decision.policy_id or 'None'} (v{decision.policy_version or 'N/A'})\n"
            f"Requires Approval: {approval_str}\n"
            f"Explanation: {decision.explanation}\n"
            f"Reason Codes: {', '.join(decision.reason_codes)}"
        )
    except Exception as e:
        logger.error("Internal error checking action policy: %s", type(e).__name__, exc_info=True)
        return "ACTION POLICY CHECK FAILED: An internal error occurred while evaluating action policy."

