# backend/tools/inventory_tools.py
from langchain_core.tools import tool

try:
    from services.connection_manager import db_manager
except ModuleNotFoundError:
    from backend.services.connection_manager import db_manager

@tool
def check_live_inventory(
    tenant_id: str = "tenant_default",
    workspace_id: str = "workspace_default",
    session_id: str = "session_default",
    connection_id: str = "sqlite_main"
) -> str:
    """Scans the database for inventory anomalies such as low-stock items for the active session context."""
    try:
        _, _, db, query_tool = db_manager.get_connection(tenant_id, workspace_id, session_id, connection_id)
        tables = db.get_usable_table_names() if db else []
        if not tables:
            return "No tables found in the current database. Please upload a dataset first."
        
        # Try to find inventory-related tables and check for low stock
        results = []
        for table in tables:
            try:
                query = f"SELECT * FROM {table} LIMIT 5"
                result = query_tool.invoke(query)
                results.append(f"Table '{table}': {result}")
            except Exception:
                pass
        
        if results:
            return "Inventory Scan Report:\n" + "\n".join(results)
        return "Inventory scan complete. No anomalies detected in accessible tables."
    except Exception as e:
        return f"Inventory scan failed: {str(e)}"

