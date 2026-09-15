# backend/agents/strategy.py
from typing import Dict, Any, List
from pydantic import BaseModel, Field

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import safe_llm_invoke
    from services.db_service import dynamic_db
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import safe_llm_invoke
    from backend.services.db_service import dynamic_db


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
    schema_info = dynamic_db.db.get_table_info() if (dynamic_db and dynamic_db.db) else "No active database schema."
    
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
