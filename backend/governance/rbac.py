# backend/governance/rbac.py
from typing import Dict, Any

def is_high_risk_action(eval_payload: Dict[str, Any]) -> bool:
    """
    Classifies whether a pending execution action is high-risk.
    Operations with non-empty SQL queries or high-impact operational commands
    require 'manager' role authorization.
    """
    if not eval_payload:
        return True
    
    sql_query = eval_payload.get("sql_query", "").strip()
    action_text = eval_payload.get("action", "").lower()
    
    if sql_query:
        return True
    
    high_risk_keywords = ["update", "delete", "reallocate", "expedite", "restock", "price", "order"]
    for keyword in high_risk_keywords:
        if keyword in action_text:
            return True
            
    return False
