# backend/governance/security.py
from typing import Dict, Any
try:
    from core.state import SageOSState, IndustrialStage
    from governance.guardrails import validate_sql_query
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.governance.guardrails import validate_sql_query

def security_agent_node(state: SageOSState) -> Dict[str, Any]:
    """
    GOVERN STAGE: Security Intrusion Detection Agent.
    Monitors payload for prompt injection, raw SQL injection syntax, and abnormal payload size.
    """
    print(" [Security Agent] Monitoring payload for intrusion patterns...")
    messages = state.get("messages", [])
    input_text = ""
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            input_text = str(last_msg.get("content", ""))
        elif hasattr(last_msg, "content"):
            input_text = str(last_msg.content)

    # Check for Prompt Injections / System Overrides
    injection_keywords = [
        "ignore previous instructions", "system prompt", "override security",
        "admin mode", "bypass guardrails", "forget rules", "developer mode"
    ]
    for kw in injection_keywords:
        if kw in input_text.lower():
            print(f" [Security Alert] Prompt injection pattern detected: '{kw}'")
            return {
                "security_status": "CRITICAL_THREAT",
                "threat_details": f"Prompt injection attempt detected containing pattern: '{kw}'",
                "next_worker": "END",
                "current_stage": IndustrialStage.GOVERN
            }
            
    # Check for Unauthorized Raw SQL Injection Syntax in Chat Input
    sql_threats = ["DROP TABLE", "DELETE FROM", "TRUNCATE TABLE", "ALTER TABLE", "UNION SELECT", ";--"]
    for sql_kw in sql_threats:
        if sql_kw in input_text.upper():
            print(f" [Security Alert] Malicious SQL pattern detected in payload: '{sql_kw}'")
            return {
                "security_status": "CRITICAL_THREAT",
                "threat_details": f"Unauthorized raw SQL payload pattern detected: '{sql_kw}'",
                "next_worker": "END",
                "current_stage": IndustrialStage.GOVERN
            }

    # Check for Abnormal Payload Size
    if len(input_text) > 2500:
        print(" [Security Alert] Abnormal payload size detected.")
        return {
            "security_status": "CRITICAL_THREAT",
            "threat_details": f"Abnormal payload size detected ({len(input_text)} characters exceeds security threshold 2500).",
            "next_worker": "END",
            "current_stage": IndustrialStage.GOVERN
        }

    print(" [Security Agent] Payload verified cleanly. Security clearance GRANTED.")
    return {
        "security_status": "CLEAR", 
        "threat_details": "",
        "current_stage": IndustrialStage.GOVERN
    }
