# backend/tools/search_tools.py
from langchain_core.tools import tool

try:
    from core.config import TAVILY_API_KEY
except (ImportError, ModuleNotFoundError):
    from backend.core.config import TAVILY_API_KEY

if TAVILY_API_KEY:
    from langchain_tavily import TavilySearch
    web_search_tool = TavilySearch(max_results=3)
else:
    @tool
    def web_search_tool(query: str) -> str:
        """Search the web for external market context, pricing, or supply chain info."""
        return f"[Web Search Context] Market research query executed for '{query}'. Simulated context: Stable supplier lead times and market price parity."
