# backend/agents/execution.py
"""
SageCommand V3 — Execution Node Boundary Guard
Enforces Constraint E and Constraint K:
Agents must NOT directly execute arbitrary SQL writes or mutate production databases.
Structured actions represent intent only; production execution is strictly deferred to the Execution Gateway.
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage

try:
    from core.state import SageOSState, IndustrialStage
    from governance.audit import log_security_event
except ModuleNotFoundError:
    from backend.core.state import SageOSState, IndustrialStage
    from backend.governance.audit import log_security_event


def execution_node(state: SageOSState) -> Dict[str, Any]:
    """
    EXECUTE, VERIFY & LEARN STAGE: Boundary Guard Node.
    Prevents direct AI operational database writes.
    Captures structured action proposals and queues them for downstream policy/approval gateways.
    """
    proposed_action = state.get("proposed_action")
    eval_result = state.get("utility_evaluation", {})
    sql_query = eval_result.get("sql_query", "")

    # 1. Handle Structured Action Proposal (Canonical Path)
    if proposed_action:
        act_id = proposed_action.get("action_id", "act_unknown")
        act_type = proposed_action.get("action_type", "UNKNOWN")
        risk_level = proposed_action.get("system_risk_level", "MEDIUM")
        requires_appr = proposed_action.get("requires_approval", True)

        msg = (
            f"[ACTION REGISTERED] Structured Action '{act_id}' ({act_type}) registered in Action Store. "
            f"Deterministic Risk: {risk_level} | Human Approval Required: {requires_appr}. "
            f"Execution Gateway is disabled in Prompt 05; awaiting Policy Enforcement Engine."
        )
        print(f" [Execution Boundary] {msg}")

        return {
            "messages": [AIMessage(content=msg)],
            "current_stage": IndustrialStage.EXECUTE,
            "verification_result": {
                "status": "QUEUED_FOR_GOVERNANCE",
                "action_id": act_id,
                "action_type": act_type,
                "risk_level": risk_level,
                "details": "Operational changes must proceed via Policy Enforcement and Execution Gateway."
            }
        }

    # 2. Block Legacy Raw SQL Write Attempts (Constraint K Enforcement)
    if sql_query and sql_query.strip():
        block_msg = (
            "Direct SQL execution by AI agents is strictly prohibited under SageCommand V3 "
            "Constraint K. Operational modifications must be proposed as typed Action domain objects."
        )
        print(f" [Execution Boundary Alert] {block_msg}")
        log_security_event(
            event_name="AGENT_DIRECT_SQL_BLOCKED",
            details={"attempted_query": sql_query[:200]},
            user_id=state.get("tenant_id", "system"),
            severity="WARNING"
        )
        return {
            "messages": [AIMessage(content=block_msg)],
            "current_stage": IndustrialStage.EXECUTE,
            "verification_result": {
                "status": "BLOCKED",
                "details": "Direct agent operational SQL writes are prohibited."
            }
        }

    # 3. Default Safe Pass-Through
    return {
        "messages": [AIMessage(content="Execution stage complete (no operational transaction required).")],
        "current_stage": IndustrialStage.EXECUTE,
        "verification_result": {"status": "SUCCESS", "details": "No operational write requested."}
    }
