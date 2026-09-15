# backend/governance/audit.py
import json
import time
from typing import Dict, Any
from datetime import datetime, timezone

try:
    from governance.redaction import sanitize_log_message
    from services.audit_ledger import audit_ledger
except ModuleNotFoundError:
    from backend.governance.redaction import sanitize_log_message
    from backend.services.audit_ledger import audit_ledger


def log_security_event(
    event_name: str,
    details: Dict[str, Any],
    user_id: str = "anonymous",
    severity: str = "INFO",
    tenant_id: str = "tenant_default",
    session_id: str = None
) -> Dict[str, Any]:
    """
    Logs structured security audit events and persists them into the Audit & Decision Ledger.
    Redacts all sensitive passwords, tokens, and keys automatically.
    """
    safe_details = {}
    for k, v in details.items():
        if "password" in k.lower() or "secret" in k.lower() or "token" in k.lower() or "key" in k.lower():
            safe_details[k] = "[REDACTED]"
        else:
            safe_details[k] = sanitize_log_message(str(v))

    utc_now = datetime.now(timezone.utc).isoformat()
    audit_entry = {
        "timestamp": utc_now,
        "event": event_name,
        "severity": severity,
        "user_id": user_id,
        "details": safe_details
    }

    log_line = f" [SECURITY AUDIT] [{severity}] {event_name} | User: {user_id} | Details: {json.dumps(safe_details)}"
    print(log_line)

    # Bridge into persistent Audit Ledger
    try:
        t_id = details.get("tenant_id") or tenant_id
        s_id = details.get("session_id") or session_id
        audit_ledger.record_security_event_bridge(
            event_name=event_name,
            details=safe_details,
            user_id=user_id,
            severity=severity,
            tenant_id=t_id,
            session_id=s_id
        )
    except Exception:
        pass

    return audit_entry

