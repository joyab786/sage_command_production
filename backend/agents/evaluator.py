# backend/agents/evaluator.py
from typing import Dict, Any
from pydantic import BaseModel, Field

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import safe_llm_invoke
    from services.db_service import dynamic_db
    from governance.custody import create_custody_entry
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
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import safe_llm_invoke
    from backend.services.db_service import dynamic_db
    from backend.governance.custody import create_custody_entry
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


class EvaluationResult(BaseModel):
    action: str = Field(description="The selected action/resolution path chosen as the best course of action.")
    justification: str = Field(description="Real-world justification for selecting this strategy.")
    action_type: str = Field(
        default="REORDER_INVENTORY",
        description="Structured industrial action type: ADJUST_REORDER_POINT, REORDER_INVENTORY, MOVE_INVENTORY, SCHEDULE_MAINTENANCE, etc."
    )
    target_resource_id: str = Field(default="SKU_INV_1001", description="Identifier of the target industrial resource (e.g. SKU, Machine ID).")
    sql_query: str = Field(
        default="",
        description="Deprecated. SageCommand V3 enforces structured actions. Operational SQL write statements are prohibited from direct generation."
    )


def evaluator_agent_node(state: SageOSState) -> Dict[str, Any]:
    """OPTIMIZE & GOVERN STAGE: Heuristic Evaluator & Strategy Synthesizer Node."""
    print(" [Evaluator] Synthesizing internal strategies with external market context into Structured Action...")
    
    schema_info = dynamic_db.db.get_table_info() if (dynamic_db and dynamic_db.db) else "No database loaded."
    strategies = state.get("generated_strategies", [])
    web_context = state.get("external_market_context", "")
    anomaly = state.get("anomaly_details", {})
    blast_radius = state.get("blast_radius_analysis", {})
    
    tenant_id = state.get("tenant_id") or "tenant_default"
    workspace_id = state.get("workspace_id") or "workspace_default"
    session_id = state.get("session_id") or "session_default"

    eval_prompt = f"""You are the Heuristic Evaluator node in SageCommand OS.
Your job is to synthesize internal operational strategies with external market intelligence, risk blast radius, and database schema details to choose the optimal resolution path.

ACTIVE DATABASE SCHEMA:
{schema_info}

ANOMALY DETAILS:
{anomaly}

BLAST RADIUS ANALYSIS:
{blast_radius}

PROPOSED INTERNAL STRATEGIES:
{strategies}

EXTERNAL MARKET INTELLIGENCE:
{web_context}

INSTRUCTIONS:
1. Select or synthesize the single best resolution `action` based on financial cost, implementation speed, and external market context.
2. Provide a thorough, professional real-world `justification` for why this resolution path is superior.
3. Categorize the action into a structured `action_type` (e.g., REORDER_INVENTORY, ADJUST_REORDER_POINT, SCHEDULE_MAINTENANCE, MOVE_INVENTORY, ESCALATE_INCIDENT).
4. Specify the `target_resource_id` (e.g. SKU or Machine identifier).
5. Do NOT generate raw SQL write queries; structured actions enforce safety deterministically.
"""
    try:
        result = safe_llm_invoke(eval_prompt, structured_schema=EvaluationResult)
        if hasattr(result, "dict"):
            utility_eval = result.dict()
        elif isinstance(result, dict):
            utility_eval = result
        else:
            raise ValueError("Structured LLM output did not return a valid evaluation object.")
    except Exception as e:
        print(f" [Evaluator] Structured evaluation fallback: {e}.")
        try:
            justification_text = safe_llm_invoke(eval_prompt)
        except Exception:
            justification_text = f"Synthesized evaluation based on strategies: {strategies} and market context."

        selected_action = strategies[0].get("action") if strategies else "Execute operational restocking and maintenance resolution."
        utility_eval = {
            "action": selected_action,
            "justification": justification_text,
            "action_type": "REORDER_INVENTORY",
            "target_resource_id": "SKU_INV_1001",
            "sql_query": ""
        }

    # Ensure raw SQL is not executed directly
    utility_eval["sql_query"] = ""

    # Map to typed action domain object
    raw_action_type = utility_eval.get("action_type", "REORDER_INVENTORY").upper()
    try:
        act_enum = ActionType(raw_action_type)
    except ValueError:
        act_enum = ActionType.REORDER_INVENTORY

    target_res_id = utility_eval.get("target_resource_id", "SKU_INV_1001")
    target_res_type = ResourceType.MACHINE if "MAINTENANCE" in act_enum.value else ResourceType.SKU

    target = ActionTarget(
        resource_type=target_res_type,
        resource_id=target_res_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        plant_id="plant_001"
    )

    # Deterministic default parameters based on action type
    if act_enum == ActionType.REORDER_INVENTORY:
        params = {"sku_id": target_res_id, "quantity": 100, "priority": "EXPEDITE"}
    elif act_enum == ActionType.ADJUST_REORDER_POINT:
        params = {"sku_id": target_res_id, "new_reorder_point": 250, "effective_date": "2026-10-01T00:00:00Z"}
    elif act_enum == ActionType.SCHEDULE_MAINTENANCE:
        params = {
            "machine_id": target_res_id,
            "maintenance_type": "PREVENTIVE",
            "scheduled_start": "2026-10-02T08:00:00Z",
            "estimated_duration_minutes": 120
        }
    else:
        params = {"notes": utility_eval.get("justification", "")[:200]}

    cost_val = float(strategies[0].get("cost", 2500)) if strategies else 2500.0
    cost = CostEstimate(value=cost_val, currency="USD")

    system_risk = action_registry.classify_risk(act_enum, target, params, cost)
    requires_approval = system_risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]

    action = Action(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        session_id=session_id,
        action_type=act_enum,
        version="1.0",
        target=target,
        parameters=params,
        reason=ActionReason(
            summary=utility_eval.get("action", "Operational resolution"),
            justification=utility_eval.get("justification", "Generated by Evaluator Agent."),
            reason_code="OPERATIONAL_RECOVERY"
        ),
        data_mode="REAL",
        system_risk_level=system_risk,
        requires_approval=requires_approval,
        estimated_cost=cost,
        estimated_duration_minutes=60,
        provenance=ActionProvenance(
            requested_by_user_id="agent_evaluator",
            source="AGENT",
            model_name="agent-evaluator-v3",
            reasoning_trace=utility_eval.get("justification", "")
        ),
        status=ActionStatus.PROPOSED
    )

    action_store.save(action)

    # CRYPTOGRAPHIC CHAIN OF CUSTODY LOGGING
    custody_entry = create_custody_entry(
        proposed_action=f"[{action.action_type.value}] {utility_eval.get('action', '')} (ActionID: {action.action_id})",
        justification=utility_eval.get("justification", ""),
        sql_query=""
    )
    custody_entry["action_id"] = action.action_id
    custody_entry["action_hash"] = action.action_hash
    
    print(f" [Evaluator] Final Utility Evaluation complete. Action ID: {action.action_id}. Hash: {action.action_hash[:16]}...")
    existing_custody = state.get("chain_of_custody", [])
    
    return {
        "utility_evaluation": utility_eval,
        "proposed_action": action.model_dump(),
        "chain_of_custody": existing_custody + [custody_entry],
        "current_stage": IndustrialStage.GOVERN
    }
