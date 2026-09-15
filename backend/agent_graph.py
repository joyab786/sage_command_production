# backend/agent_graph.py
"""
SageCommand V3 Agent Graph Module (Backward Compatibility Re-export Wrapper)
Re-exports modular V3 core state, agents, governance, and compiled LangGraph workflow.
"""

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import llm, get_fallback_llm, safe_llm_invoke

    from governance.rbac import is_high_risk_action
    from governance.security import security_agent_node
    from governance.guardrails import validate_sql_query

    from agents.observe_detect import VisionFindingPayload, vision_diagnostics_agent_node, discovery_agent_node
    from agents.risk_analysis import (
        AffectedSystem, CascadingTimelineEvent, BlastRadiusPayload, risk_agent_node
    )
    from agents.supervisor import SupervisorDecision, supervisor_agent_node
    from agents.strategy import Strategy, StrategyList, strategy_worker_node
    from agents.research import web_researcher_node
    from agents.evaluator import EvaluationResult, evaluator_agent_node
    from agents.execution import execution_node
    from agents.copilot import copilot_agent_node

    from graph.checkpointer import memory, db_conn
    from graph.builder import (
        sage_app, build_sage_graph, route_security_check, route_copilot_tools, route_supervisor
    )
except ModuleNotFoundError:
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import llm, get_fallback_llm, safe_llm_invoke

    from backend.governance.rbac import is_high_risk_action
    from backend.governance.security import security_agent_node
    from backend.governance.guardrails import validate_sql_query

    from backend.agents.observe_detect import VisionFindingPayload, vision_diagnostics_agent_node, discovery_agent_node
    from backend.agents.risk_analysis import (
        AffectedSystem, CascadingTimelineEvent, BlastRadiusPayload, risk_agent_node
    )
    from backend.agents.supervisor import SupervisorDecision, supervisor_agent_node
    from backend.agents.strategy import Strategy, StrategyList, strategy_worker_node
    from backend.agents.research import web_researcher_node
    from backend.agents.evaluator import EvaluationResult, evaluator_agent_node
    from backend.agents.execution import execution_node
    from backend.agents.copilot import copilot_agent_node

    from backend.graph.checkpointer import memory, db_conn
    from backend.graph.builder import (
        sage_app, build_sage_graph, route_security_check, route_copilot_tools, route_supervisor
    )

# Preserve workflow reference if imported directly
workflow = build_sage_graph
