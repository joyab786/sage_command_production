# backend/agents/supervisor.py
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

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


class SupervisorDecision(BaseModel):
    next_worker: Literal["strategy_worker", "web_researcher", "evaluator", "execution", "END"] = Field(
        description="The next worker node or stage to delegate the task to."
    )
    delegation_message: str = Field(
        description="A clear delegation instruction explaining what needs to be done next."
    )


def supervisor_agent_node(state: SageOSState) -> Dict[str, Any]:
    """GOVERN & ROUTE STAGE: Autonomous Supervisor Hub Node."""
    print(" [Supervisor] Evaluating schema and anomaly to delegate task...")
    
    tenant_id = state.get("tenant_id") or "tenant_default"
    workspace_id = state.get("workspace_id") or "workspace_default"
    session_id = state.get("session_id") or "session_default"
    connection_id = state.get("connection_id") or "sqlite_main"
    
    try:
        identity = Identity(user_id="agent_supervisor", tenant_id=tenant_id, session_id=session_id, is_server_authoritative=True)
        schema_info = db_gateway.get_schema_context_for_llm(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            connection_id=connection_id,
            identity=identity
        )
    except Exception:
        schema_info = "No active database schema loaded for session."

    anomaly = state.get("anomaly_details", {})
    messages = state.get("messages", [])
    
    user_input = ""
    if messages:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
                user_input = msg.content
                break
    if not user_input:
        user_input = anomaly.get("details", "Verify inventory status and plan optimal resolution path.")

    prompt = f"""You are the Supervisor node in SageCommand OS, an AI COO orchestrating an autonomous enterprise response system.
Your responsibility is to analyze the user request, anomaly telemetry, and database schema, then delegate to the appropriate worker node.

WORKER NODES:
1. 'strategy_worker': Generates 2-3 distinct internal operational resolution strategies with cost estimates.
2. 'web_researcher': Researches external market conditions, competitor pricing, or supplier availability via Tavily.
3. 'evaluator': Synthesizes internal strategies and external market data to select the optimal resolution path and generate database update SQL.
4. 'execution': Executes the approved SQL query against the production database (requires human authorization).
5. 'END': Concludes the workflow when processing is complete.

ACTIVE DATABASE SCHEMA:
{schema_info}

CURRENT SYSTEM STATE:
- Anomaly Details: {anomaly}
- Blast Radius Analysis: {state.get('blast_radius_analysis', {})}
- User Inquiry: {user_input}
- Generated Strategies: {state.get('generated_strategies', [])}
- External Market Context: {state.get('external_market_context', '')}
- Utility Evaluation: {state.get('utility_evaluation', {})}

ROUTING LOGIC RULE:
- If strategies ('generated_strategies') are missing/empty -> Delegate to 'strategy_worker'.
- If strategies are present BUT external research ('external_market_context') is missing/empty -> Delegate to 'web_researcher'.
- If strategies AND web research are present BUT evaluation ('utility_evaluation') is missing/empty -> Delegate to 'evaluator'.
- If utility evaluation is complete -> Delegate to 'execution'.

Formulate your decision using structured output with `next_worker` and `delegation_message`.
"""
    try:
        decision = safe_llm_invoke(prompt, structured_schema=SupervisorDecision)
        if hasattr(decision, "next_worker"):
            next_worker = decision.next_worker
            msg_content = decision.delegation_message
        elif isinstance(decision, dict):
            next_worker = decision.get("next_worker", "strategy_worker")
            msg_content = decision.get("delegation_message", "Supervisor delegating task based on state evaluation.")
        else:
            raise ValueError("Invalid supervisor decision format")
    except Exception as e:
        print(f" [Supervisor] Routing call failed: {e}. Using state-aware fallback.")
        if not state.get("generated_strategies"):
            next_worker = "strategy_worker"
            msg_content = "Delegating to Strategy Worker: Generate operational resolution strategies."
        elif not state.get("external_market_context"):
            next_worker = "web_researcher"
            msg_content = "Delegating to Web Researcher: Gather market intelligence and supplier context."
        elif not state.get("utility_evaluation"):
            next_worker = "evaluator"
            msg_content = "Delegating to Evaluator: Synthesize strategies and market data."
        else:
            next_worker = "execution"
            msg_content = "Routing to Execution: Evaluation complete; awaiting human execution authorization."

    print(f" [Supervisor] Routing decision: next_worker={next_worker} | message={msg_content}")
    return {
        "messages": [AIMessage(content=msg_content)],
        "next_worker": next_worker,
        "current_stage": IndustrialStage.GOVERN
    }
