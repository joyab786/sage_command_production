# backend/agent_graph.py
from typing import TypedDict, List, Dict, Any, Literal, Annotated
import operator
from langgraph.graph import StateGraph, START, END, MessagesState
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite import SqliteSaver
from tools import sage_tools, check_live_inventory, web_search_tool
import sqlite3
import os

# LLM Selection: Uses Groq (free, fast) if GROQ_API_KEY is set, else falls back to Gemini
import os
from dotenv import load_dotenv
load_dotenv()

if os.getenv("GROQ_API_KEY"):
    from langchain_groq import ChatGroq
    # llama-3.3-70b-versatile: current recommended Groq model, supports tool/function calling
    # 128k context window, 6000 tokens/min on free tier
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)
    print("[AI] Using Groq llama-3.3-70b-versatile")
else:
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.2)
    print("[AI] Using Google Gemini 2.0 Flash")

# 1. THE ADVANCED STATE
class SageOSState(MessagesState):
    anomaly_details: Dict[str, Any]
    generated_strategies: List[Dict[str, Any]]
    external_market_context: str
    utility_evaluation: Dict[str, Any]

# 2. THE COPILOT AGENT (Direct Human Chat)
# Max messages to keep in context to avoid context_length_exceeded errors
MAX_CONTEXT_MESSAGES = 10

def copilot_agent_node(state: SageOSState):
    print(" [Copilot] Processing human inquiry...")
    llm_with_tools = llm.bind_tools(sage_tools)
    sys_msg = SystemMessage(content=(
        "You are SageCommand, an Omni-Agent COO. "
        "Use the list_database_tables tool first to inspect the schema, "
        "then use query_database for SQL queries. "
        "Use the web search tool for external/internet queries. "
        "Always pass SQL as a plain string to query_database."
    ))
    # Trim message history to avoid context length exceeded errors
    messages = state["messages"]
    if len(messages) > MAX_CONTEXT_MESSAGES:
        messages = messages[-MAX_CONTEXT_MESSAGES:]
    response = llm_with_tools.invoke([sys_msg] + messages)
    return {"messages": [response]}

# 3. AUTONOMOUS BACKGROUND AGENTS
def discovery_agent_node(state: SageOSState):
    print(" [Discovery] Scanning industrial database...")
    # AI uses the tool to check for issues
    report = check_live_inventory.invoke({})
    anomaly = {"type": "Low Stock Anomaly", "details": report}
    return {"anomaly_details": anomaly}

def supervisor_agent_node(state: SageOSState):
    return {"messages": [AIMessage(content="Supervisor delegating task.")]}

def strategy_worker_node(state: SageOSState):
    strategies = [
        {"id": "S1", "action": "Rush order from secondary supplier at 20% markup.", "cost": 5000},
        {"id": "S2", "action": "Reallocate from passive warehouse.", "cost": 1500}
    ]
    return {"generated_strategies": strategies}

def web_researcher_node(state: SageOSState):
    print(" [Web Researcher] Scanning global internet...")
    search_results = web_search_tool.invoke({"query": "global supply chain delays thermal sensors electronics"})
    return {"external_market_context": str(search_results)}

def evaluator_agent_node(state: SageOSState):
    print(" [Evaluator] Synthesizing internal strategies with global web context...")
    eval_prompt = f"""
    Internal Strategies: {state['generated_strategies']}
    External Web Data: {state['external_market_context']}
    Provide a real-world justification and select the best strategy.
    """
    decision = llm.invoke(eval_prompt)
    best_strategy = {
        "action": "Dynamic AI Selected Action",
        "justification": decision.content
    }
    return {"utility_evaluation": best_strategy}

def execution_node(state: SageOSState):
    print(" [Execution] Authorized. Committing to database...")
    return {"messages": [AIMessage(content="Execution committed.")]}

# 4. TRAFFIC ROUTING
def route_initial_input(state: SageOSState) -> Literal["copilot_agent", "discovery"]:
    if state.get("messages") and isinstance(state["messages"][-1], HumanMessage):
        return "copilot_agent"
    return "discovery"

def route_copilot_tools(state: SageOSState) -> Literal["tools", "__end__"]:
    # If the Copilot decides to use a tool, route to the pre-built ToolNode
    messages = state.get("messages", [])
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return "__end__"

# 5. BUILD THE GRAPH
workflow = StateGraph(SageOSState)

# We use LangGraph's prebuilt ToolNode to auto-execute database/web searches
from langgraph.prebuilt import ToolNode
workflow.add_node("tools", ToolNode(sage_tools))

workflow.add_node("copilot_agent", copilot_agent_node)
workflow.add_node("discovery", discovery_agent_node)
workflow.add_node("supervisor", supervisor_agent_node)
workflow.add_node("strategy_worker", strategy_worker_node)
workflow.add_node("web_researcher", web_researcher_node)
workflow.add_node("evaluator", evaluator_agent_node)
workflow.add_node("execution", execution_node)

# Wiring
workflow.add_conditional_edges(START, route_initial_input)

# Copilot Loop
workflow.add_conditional_edges("copilot_agent", route_copilot_tools)
workflow.add_edge("tools", "copilot_agent")

# Autonomous Loop
workflow.add_edge("discovery", "supervisor")
workflow.add_edge("supervisor", "strategy_worker")
workflow.add_edge("strategy_worker", "web_researcher")
workflow.add_edge("web_researcher", "evaluator")
workflow.add_edge("evaluator", "execution")
workflow.add_edge("execution", END)

# Memory & Compilation
db_conn = sqlite3.connect("sage_memory.sqlite", check_same_thread=False)
memory = SqliteSaver(db_conn)

sage_app = workflow.compile(checkpointer=memory, interrupt_before=["execution"])
