# backend/agents/strategy.py
from typing import Dict, Any, List
from pydantic import BaseModel, Field

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import safe_llm_invoke
    from core.auth import Identity
    from gateway.db_gateway import db_gateway
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import safe_llm_invoke
    from backend.core.auth import Identity
    from backend.gateway.db_gateway import db_gateway


class Strategy(BaseModel):
    id: str = Field(description="Unique identifier for the strategy, e.g. S1, S2.")
    action: str = Field(description="Action description of what to do.")
    cost: int = Field(description="Estimated cost associated with this action.")

class StrategyList(BaseModel):
    strategies: List[Strategy] = Field(description="A list of 2 to 3 alternative resolution strategies.")


def strategy_worker_node(state: SageOSState) -> Dict[str, Any]:
    """OPTIMIZE STAGE: Multi-Objective Strategy Generation Worker."""
    print(" [Strategy Worker] Generating strategies dynamically...")
    anomaly = state.get("anomaly_details", {})
    
    tenant_id = state.get("tenant_id") or "tenant_default"
    workspace_id = state.get("workspace_id") or "workspace_default"
    session_id = state.get("session_id") or "session_default"
    connection_id = state.get("connection_id") or "sqlite_main"
    
    try:
        identity = Identity(user_id="agent_strategy", tenant_id=tenant_id, session_id=session_id, is_server_authoritative=True)
        schema_info = db_gateway.get_schema_context_for_llm(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            connection_id=connection_id,
            identity=identity
        )
    except Exception:
        schema_info = "No active database schema loaded for session."

    
    prompt = f"""You are the Strategy Worker node in SageCommand OS.
Based on the following anomaly details and database schema, generate exactly 2 to 3 distinct, realistic, and actionable resolution strategies.
For each strategy:
- `id`: Short identifier (e.g., S1, S2, S3).
- `action`: Specific operational action (e.g. adjust pricing, reorder stock, reallocate warehouse inventory).
- `cost`: Estimated financial cost in USD (integer).

DATABASE SCHEMA:
{schema_info}

ANOMALY DETAILS:
{anomaly}
"""
    try:
        result = safe_llm_invoke(prompt, structured_schema=StrategyList)
        if hasattr(result, "strategies"):
            strategies = [s.dict() for s in result.strategies]
        elif isinstance(result, dict) and "strategies" in result:
            strategies = result["strategies"]
        else:
            strategies = []
    except Exception as e:
        print(f" [Strategy Worker] Error generating strategies: {e}. Using dynamic fallback.")
        anomaly_type = anomaly.get("type", "Inventory Anomaly")
        anomaly_details = anomaly.get("details", "detected issue")
        strategies = [
            {"id": "S1", "action": f"Expedite priority restocking order to resolve {anomaly_type} ({anomaly_details}).", "cost": 3500},
            {"id": "S2", "action": f"Rebalance warehouse allocations and optimize pricing to mitigate {anomaly_type}.", "cost": 1200}
        ]

    print(f" [Strategy Worker] Generated strategies: {strategies}")
    return {
        "generated_strategies": strategies,
        "current_stage": IndustrialStage.OPTIMIZE
    }
