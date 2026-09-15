# backend/graph/builder.py
from typing import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage

try:
    from core.state import SageOSState
    from governance.security import security_agent_node
    from agents.observe_detect import vision_diagnostics_agent_node, discovery_agent_node
    from agents.risk_analysis import risk_agent_node
    from agents.copilot import copilot_agent_node, copilot_tools
    from agents.supervisor import supervisor_agent_node
    from agents.strategy import strategy_worker_node
    from agents.research import web_researcher_node
    from agents.evaluator import evaluator_agent_node
    from agents.execution import execution_node
    from graph.checkpointer import memory
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState
    from backend.governance.security import security_agent_node
    from backend.agents.observe_detect import vision_diagnostics_agent_node, discovery_agent_node
    from backend.agents.risk_analysis import risk_agent_node
    from backend.agents.copilot import copilot_agent_node, copilot_tools
    from backend.agents.supervisor import supervisor_agent_node
    from backend.agents.strategy import strategy_worker_node
    from backend.agents.research import web_researcher_node
    from backend.agents.evaluator import evaluator_agent_node
    from backend.agents.execution import execution_node
    from backend.graph.checkpointer import memory


# --- TRAFFIC ROUTING FUNCTIONS ---
def route_security_check(state: SageOSState) -> Literal["vision_diagnostics_agent", "copilot_agent", "discovery", "__end__"]:
    if state.get("security_status") == "CRITICAL_THREAT":
        return "__end__"
    if state.get("image_data"):
        return "vision_diagnostics_agent"
    if state.get("messages") and isinstance(state["messages"][-1], HumanMessage):
        return "copilot_agent"
    return "discovery"


def route_copilot_tools(state: SageOSState) -> Literal["tools", "__end__"]:
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
    return "__end__"


def route_supervisor(state: SageOSState) -> Literal["strategy_worker", "web_researcher", "evaluator", "execution", "__end__"]:
    next_worker = state.get("next_worker")
    if next_worker == "END" or next_worker is None:
        return "__end__"
    return next_worker


# --- BUILD THE GRAPH TOPOLOGY ---
def build_sage_graph():
    workflow = StateGraph(SageOSState)

    workflow.add_node("tools", ToolNode(copilot_tools))
    workflow.add_node("security_agent", security_agent_node)
    workflow.add_node("vision_diagnostics_agent", vision_diagnostics_agent_node)
    workflow.add_node("copilot_agent", copilot_agent_node)
    workflow.add_node("discovery", discovery_agent_node)
    workflow.add_node("risk_agent", risk_agent_node)
    workflow.add_node("supervisor", supervisor_agent_node)
    workflow.add_node("strategy_worker", strategy_worker_node)
    workflow.add_node("web_researcher", web_researcher_node)
    workflow.add_node("evaluator", evaluator_agent_node)
    workflow.add_node("execution", execution_node)

    # Entry Gate: START -> security_agent -> (vision_diagnostics_agent | copilot_agent | discovery | END)
    workflow.add_edge(START, "security_agent")
    workflow.add_conditional_edges("security_agent", route_security_check)

    # Vision Diagnostics Pipeline: vision_diagnostics_agent -> strategy_worker -> supervisor
    workflow.add_edge("vision_diagnostics_agent", "strategy_worker")

    # Copilot Routing Loop
    workflow.add_conditional_edges("copilot_agent", route_copilot_tools)
    workflow.add_edge("tools", "copilot_agent")

    # Autonomous Pipeline: Discovery -> Risk Agent -> Supervisor
    workflow.add_edge("discovery", "risk_agent")
    workflow.add_edge("risk_agent", "supervisor")

    # Dynamic Supervisor Routing Hub
    workflow.add_conditional_edges("supervisor", route_supervisor)
    workflow.add_edge("strategy_worker", "supervisor")
    workflow.add_edge("web_researcher", "supervisor")
    workflow.add_edge("evaluator", "supervisor")
    workflow.add_edge("execution", END)

    return workflow.compile(checkpointer=memory, interrupt_before=["execution"])


sage_app = build_sage_graph()
