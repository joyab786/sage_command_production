# backend/governance/guardrails.py
import re

def check_multi_statement_sql(query: str) -> None:
    """
    Blocks multi-statement SQL execution (e.g. 'SELECT 1; DROP TABLE inventory').
    Raises PermissionError if multiple non-empty statements separated by semicolons exist.
    """
    if not query:
        return
        
    # Remove strings/comments to accurately detect semicolon statements
    cleaned = re.sub(r"\'[^\']*\'", "", query)
    cleaned = re.sub(r'\"[^\"]*\"', "", cleaned)
    cleaned = re.sub(r"--.*$", "", cleaned, flags=re.MULTILINE)
    
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    if len(statements) > 1:
        raise PermissionError(
            f"SQL Security Guardrail Violation: Multi-statement SQL queries are strictly prohibited ({len(statements)} statements detected)."
        )


def validate_sql_query(query: str) -> None:
    """
    Layered SQL Security Validator:
    1. Blocks multi-statement execution.
    2. Enforces word-bounded keyword blocking (DROP, DELETE, TRUNCATE, ALTER, GRANT, REVOKE).
    3. Prevents unauthorized access to system metadata catalog tables.
    """
    if not query:
        return
        
    # Layer 1: Multi-statement check
    check_multi_statement_sql(query)
    
    normalized = query.lower()
    
    # Layer 2: Destructive statement check (word-bounded)
    destructive_keywords = ["drop", "delete", "truncate", "alter", "grant", "revoke", "create", "execute", "exec"]
    for keyword in destructive_keywords:
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, normalized):
            raise PermissionError(
                f"SQL Guardrail Violation: Query contains prohibited destructive statement '{keyword.upper()}'."
            )
            
    # Layer 3: System catalog access check
    unauthorized_system_tables = [
        "sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema",
        "information_schema", "pg_catalog", "mysql", "pg_stat_activity", "sys", "master"
    ]
    for table in unauthorized_system_tables:
        pattern = rf"\b{table}\b"
        if re.search(pattern, normalized):
            raise PermissionError(
                f"SQL Guardrail Violation: Access to unauthorized system metadata catalog '{table}' is prohibited."
            )
