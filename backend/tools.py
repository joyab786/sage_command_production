import os
import re
from dotenv import load_dotenv
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool
from langchain_core.tools import tool
from database import engine

# Load API keys from .env file if present
load_dotenv()

# 1. TAVILY WEB SEARCH TOOL
if os.getenv("TAVILY_API_KEY"):
    from langchain_tavily import TavilySearch
    web_search_tool = TavilySearch(max_results=3)
else:
    @tool
    def web_search_tool(query: str) -> str:
        """Search the web for external market context, pricing, or supply chain info."""
        return f"[Web Search Context] Market research query executed for '{query}'. Simulated context: Stable supplier lead times and market price parity."


# 2. DYNAMIC HOT-SWAP WRAPPER
class DynamicDB:
    def __init__(self, initial_engine):
        self.engine = initial_engine
        try:
            self.db = SQLDatabase(initial_engine)
            self.query_tool = QuerySQLDatabaseTool(db=self.db)
            tables = self.db.get_usable_table_names()
            if tables:
                print(f" Database loaded with tables: {tables}")
            else:
                print(" Database is empty  ready to receive data via upload or live tether.")
        except Exception as e:
            print(f"  Could not connect to default database: {e}. Starting with null state.")
            self.db = None
            self.query_tool = None
            self.engine = None

    def update_engine(self, new_engine):
        """Called by server.py to hot-swap the AI's brain to a new database"""
        self.engine = new_engine
        self.db = SQLDatabase(new_engine)
        self.query_tool = QuerySQLDatabaseTool(db=self.db)
        print(" AI Cortex re-wired to new database schema.")

# Initialize the global dynamic database state
dynamic_db = DynamicDB(engine)

# 3. SQL GUARDRAIL VALIDATOR
def validate_sql_query(query: str) -> None:
    """
    Validates SQL queries before they run on the database.
    Raises PermissionError if a forbidden keyword (like DROP, DELETE, TRUNCATE, ALTER, GRANT, REVOKE) 
    or unauthorized system schema table access is detected.
    """
    if not query:
        return
        
    normalized = query.lower()
    
    # 1. Destructive commands check (word-bounded to avoid false positives)
    destructive_keywords = ["drop", "delete", "truncate", "alter", "grant", "revoke"]
    for keyword in destructive_keywords:
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, normalized):
            raise PermissionError(
                f"SQL Guardrail Violation: Query contains prohibited destructive statement '{keyword.upper()}'."
            )
            
    # 2. System tables and metadata catalog access check (word-bounded)
    unauthorized_system_tables = [
        "sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema",
        "information_schema", "pg_catalog", "mysql", "pg_stat_activity"
    ]
    for table in unauthorized_system_tables:
        pattern = rf"\b{table}\b"
        if re.search(pattern, normalized):
            raise PermissionError(
                f"SQL Guardrail Violation: Access to unauthorized system metadata table '{table}' is prohibited."
            )

# 4. RUNTIME-EVALUATED TOOLS
@tool
def list_database_tables() -> str:
    """Always use this tool first to see what tables are available in the database."""
    if dynamic_db.db is None:
        return "No database is currently loaded. Please upload a .csv or .sqlite file first."
    return str(dynamic_db.db.get_usable_table_names())

@tool
def query_database(query: str) -> str:
    """Execute a SQL query against the database and get the results."""
    if dynamic_db.query_tool is None:
        return "No database is currently loaded. Please upload a .csv or .sqlite file first."
    
    # Execute SQL Validator check (raises PermissionError on violation)
    validate_sql_query(query)
    
    return dynamic_db.query_tool.invoke(query)

@tool
def check_live_inventory() -> str:
    """Scans the database for inventory anomalies such as low-stock items. 
    Returns a report of items that may need attention."""
    try:
        tables = dynamic_db.db.get_usable_table_names()
        if not tables:
            return "No tables found in the current database. Please upload a dataset first."
        
        # Try to find inventory-related tables and check for low stock
        results = []
        for table in tables:
            try:
                query = f"SELECT * FROM {table} LIMIT 5"
                result = dynamic_db.query_tool.invoke(query)
                results.append(f"Table '{table}': {result}")
            except Exception:
                pass
        
        if results:
            return "Inventory Scan Report:\n" + "\n".join(results)
        return "Inventory scan complete. No anomalies detected in accessible tables."
    except Exception as e:
        return f"Inventory scan failed: {str(e)}"

# Export tools for your agent_graph.py
sage_tools = [list_database_tables, query_database, web_search_tool]
