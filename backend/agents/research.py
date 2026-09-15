# backend/agents/research.py
from typing import Dict, Any
from langchain_core.messages import HumanMessage

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import safe_llm_invoke
    from tools.search_tools import web_search_tool
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import safe_llm_invoke
    from backend.tools.search_tools import web_search_tool


def web_researcher_node(state: SageOSState) -> Dict[str, Any]:
    """ANALYZE & OPTIMIZE STAGE: Web Market Research Agent."""
    print(" [Web Researcher] Scanning global internet via Tavily...")
    anomaly = state.get("anomaly_details", {})
    strategies = state.get("generated_strategies", [])
    messages = state.get("messages", [])
    
    user_input = ""
    if messages:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
                user_input = msg.content
                break

    prompt = f"""You are the Web Researcher node in SageCommand OS.
Your objective is to inspect the current state/anomaly and construct a single, highly targeted search query for Tavily to gather external market intelligence, supplier pricing, market benchmarks, or industry supply chain conditions.

CONTEXT:
- Anomaly Details: {anomaly}
- Proposed Strategies: {strategies}
- User Context: {user_input}

Construct a single search query (under 15 words, plain text, search-engine optimized, no quotes or surrounding punctuation).
"""
    try:
        search_query = safe_llm_invoke(prompt).strip().strip('"').strip("'")
    except Exception as e:
        print(f" [Web Researcher] Failed to generate LLM search query: {e}. Constructing dynamic query from anomaly.")
        anomaly_str = f"{anomaly.get('type', '')} {anomaly.get('details', '')}"
        search_query = f"market prices supply chain {anomaly_str}"[:80].strip()
        
    print(f" [Web Researcher] Executing dynamic search query: '{search_query}'")
    try:
        if hasattr(web_search_tool, "invoke"):
            search_results = web_search_tool.invoke({"query": search_query})
        else:
            search_results = web_search_tool(search_query)
    except Exception as e:
        print(f" [Web Researcher] Tavily search tool invocation error: {e}. Retrying with direct query string.")
        try:
            search_results = web_search_tool.invoke(search_query)
        except Exception as err:
            search_results = f"Web search could not retrieve external data for query '{search_query}': {err}"
        
    return {
        "external_market_context": str(search_results),
        "current_stage": IndustrialStage.ANALYZE
    }
