# backend/governance/custody.py
import json
import time
import hashlib
from typing import Dict, Any, List

def create_custody_entry(
    proposed_action: str,
    justification: str,
    sql_query: str,
    keys_read: List[str] = None
) -> Dict[str, Any]:
    """Generates cryptographic SHA-256 chain-of-custody audit entry."""
    if keys_read is None:
        keys_read = ["anomaly_details", "blast_radius_analysis", "generated_strategies", "external_market_context", "database_schema"]
        
    custody_payload = {
        "timestamp": time.time(),
        "keys_read": keys_read,
        "proposed_action": proposed_action,
        "justification": justification,
        "sql_query": sql_query
    }
    custody_json = json.dumps(custody_payload, sort_keys=True)
    hash_digest = hashlib.sha256(custody_json.encode("utf-8")).hexdigest()
    
    return {
        "hash": hash_digest,
        "payload": custody_payload
    }
