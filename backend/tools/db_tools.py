# backend/tools/db_tools.py
from langchain_core.tools import tool

try:
    from gateway.db_gateway import db_gateway
    from core.auth import Identity
    from governance.guardrails import validate_sql_query
except ModuleNotFoundError:
    from backend.gateway.db_gateway import db_gateway
    from backend.core.auth import Identity
    from backend.governance.guardrails import validate_sql_query

@tool
def list_database_tables(
    tenant_id: str = "tenant_default",
    workspace_id: str = "workspace_default",
    session_id: str = "session_default",
    connection_id: str = "sqlite_main"
) -> str:
    """Always use this tool first to see what tables are available in the database for the active session context."""
    try:
        identity = Identity(user_id="agent_db_tool", tenant_id=tenant_id, session_id=session_id)
        schema_info = db_gateway.discover_schema(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            connection_id=connection_id,
            identity=identity,
            limit_tables=50
        )
        tables = [t["table_name"] for t in schema_info.get("tables", [])]
        return str(tables)
    except Exception as e:
        return f"Error listing database tables: {str(e)}"

@tool
def query_database(
    query: str,
    tenant_id: str = "tenant_default",
    workspace_id: str = "workspace_default",
    session_id: str = "session_default",
    connection_id: str = "sqlite_main"
) -> str:
    """Execute a SQL query against the database for the given session context and return results."""
    # Execute SQL Validator check (raises PermissionError on violation)
    validate_sql_query(query)
    
    try:
        identity = Identity(user_id="agent_db_tool", tenant_id=tenant_id, session_id=session_id)
        _, _, _, query_tool = db_gateway.get_connection(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            connection_id=connection_id,
            identity=identity
        )
        if query_tool is None:
            return "No active query tool available for this session context."
        return query_tool.invoke(query)
    except Exception as e:
        return f"Database query failed: {str(e)}"


import json
from typing import Dict, Any, Optional

class DatabaseTool:
    """
    Internal service/tool abstraction for AI Agents.
    Resolves connection_id through DatabaseConnectionGateway, keeping agents
    strictly decoupled and isolated from database credentials and raw network topology.
    """
    def __init__(self, gateway=db_gateway):
        self.gateway = gateway

    def get_llm_connection_context(
        self,
        connection_id: str,
        tenant_id: str = "tenant_default",
        workspace_id: str = "workspace_default",
        session_id: str = "session_default"
    ) -> Dict[str, Any]:
        """
        Returns safe, credential-free connection metadata explicitly formatted for LLM prompts.
        Guarantees zero leakage of host credentials, passwords, URIs, secrets, or tokens.
        """
        identity = Identity(user_id="agent_db_tool", tenant_id=tenant_id, session_id=session_id)
        conn = self.gateway.get_canonical_connection(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            connection_id=connection_id,
            identity=identity
        )
        return {
            "connection_id": conn.connection_id,
            "database_type": conn.database_type.value,
            "data_mode": conn.data_mode.value,
            "access_mode": conn.access_mode.value,
            "capabilities": {
                "read": conn.capabilities.read,
                "write": conn.capabilities.write,
                "schema_inspection": conn.capabilities.schema_inspection
            }
        }

    def discover_schema(
        self,
        connection_id: str,
        tenant_id: str = "tenant_default",
        workspace_id: str = "workspace_default",
        session_id: str = "session_default",
        limit: int = 50
    ) -> str:
        """Retrieves bounded schema representation for agent reasoning."""
        identity = Identity(user_id="agent_db_tool", tenant_id=tenant_id, session_id=session_id)
        return self.gateway.get_schema_context_for_llm(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            connection_id=connection_id,
            identity=identity,
            limit_tables=limit
        )

# Global DatabaseTool instance for agent invocation
database_tool = DatabaseTool()

@tool
def get_database_connection_context(
    connection_id: str = "sqlite_main",
    tenant_id: str = "tenant_default",
    workspace_id: str = "workspace_default",
    session_id: str = "session_default"
) -> str:
    """Retrieves safe, credential-free connection capabilities and operational modes for the LLM."""
    try:
        ctx = database_tool.get_llm_connection_context(
            connection_id=connection_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id
        )
        return json.dumps(ctx, indent=2)
    except Exception as e:
        return f"Error retrieving database context: {str(e)}"



