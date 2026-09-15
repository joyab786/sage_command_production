# backend/tools.py
"""
SageCommand V3 Tools Module (Backward Compatibility Re-export Wrapper)
Re-exports database, search, and inventory tools from modular backend packages.
"""

from backend.services.db_service import dynamic_db, DynamicDB
from backend.governance.guardrails import validate_sql_query

from backend.tools.search_tools import web_search_tool
from backend.tools.db_tools import list_database_tables, query_database
from backend.tools.inventory_tools import check_live_inventory

sage_tools = [list_database_tables, query_database, web_search_tool]
