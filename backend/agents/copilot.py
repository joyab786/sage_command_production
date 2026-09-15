# backend/agents/copilot.py
from typing import Dict, Any
from langchain_core.messages import SystemMessage

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import llm, get_fallback_llm
    from tools.db_tools import list_database_tables, query_database
    from tools.search_tools import web_search_tool
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import llm, get_fallback_llm
    from backend.tools.db_tools import list_database_tables, query_database
    from backend.tools.search_tools import web_search_tool

copilot_tools = [list_database_tables, query_database, web_search_tool]
MAX_CONTEXT_MESSAGES = 10

def copilot_agent_node(state: SageOSState) -> Dict[str, Any]:
    """UNDERSTAND STAGE: Strategic Copilot Agent (Direct Human Conversational Agent)."""
    print(" [Copilot] Processing human inquiry...")
    llm_with_tools = llm.bind_tools(copilot_tools)
    sys_msg = SystemMessage(content=(
        "You are SageCommand, an Omni-Agent COO. "
        "Use the list_database_tables tool first to inspect the schema, "
        "then use query_database for SQL queries. "
        "Use the web search tool for external/internet queries. "
        "Always pass SQL as a plain string to query_database."
    ))
    messages = state["messages"]
    if len(messages) > MAX_CONTEXT_MESSAGES:
        messages = messages[-MAX_CONTEXT_MESSAGES:]
    try:
        response = llm_with_tools.invoke([sys_msg] + messages)
    except Exception as e:
        print(f" [Copilot] Tool execution failed over to Gemini: {e}")
        fallback_llm = get_fallback_llm().bind_tools(copilot_tools)
        response = fallback_llm.invoke([sys_msg] + messages)
        
    return {
        "messages": [response],
        "current_stage": IndustrialStage.UNDERSTAND
    }
