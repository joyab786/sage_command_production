# backend/governance/redaction.py
import re
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field


class ConnectionInfo(BaseModel):
    """Safe, credential-redacted database connection representation."""
    connection_id: str
    database_type: str
    host: Optional[str] = "localhost"
    port: Optional[int] = None
    database: Optional[str] = "default"
    username: str = "[REDACTED]"
    password: str = "[REDACTED]"
    is_valid_scheme: bool = True


def sanitize_connection_string(connection_string: str) -> str:
    """
    Redacts passwords and sensitive tokens from database URIs and connection strings.
    Example: 'postgresql://admin:super_secret@localhost:5432/db' -> 'postgresql://admin:[REDACTED]@localhost:5432/db'
    """
    if not connection_string:
        return ""
    
    # Redact URI user:password pattern
    pattern = r'(:\/\/[^:]+:)([^@]+)(@)'
    redacted = re.sub(pattern, r'\1[REDACTED]\3', connection_string)
    
    # Redact inline password= values
    redacted = re.sub(r'password\s*=\s*[\'"]?[^\s;\'"]+[\'"]?', 'password=[REDACTED]', redacted, flags=re.IGNORECASE)
    redacted = re.sub(r'pwd\s*=\s*[\'"]?[^\s;\'"]+[\'"]?', 'pwd=[REDACTED]', redacted, flags=re.IGNORECASE)
    
    return redacted


def parse_safe_connection_info(connection_string: str, connection_id: str = "conn_default") -> ConnectionInfo:
    """Parses a raw DB URI and returns a safe ConnectionInfo object with zero raw credentials."""
    sanitized = sanitize_connection_string(connection_string)
    
    try:
        parsed = urlparse(connection_string)
        db_type = parsed.scheme.split("+")[0] if parsed.scheme else "sqlite"
        host = parsed.hostname or "localhost"
        port = parsed.port
        db_name = parsed.path.lstrip("/") if parsed.path else "datacore"
        
        return ConnectionInfo(
            connection_id=connection_id,
            database_type=db_type,
            host=host,
            port=port,
            database=db_name,
            username="[REDACTED]" if parsed.username else "none",
            password="[REDACTED]" if parsed.password else "none",
            is_valid_scheme=True
        )
    except Exception:
        return ConnectionInfo(
            connection_id=connection_id,
            database_type="unknown",
            host="unknown",
            database="unknown",
            is_valid_scheme=False
        )


def sanitize_log_message(message: str) -> str:
    """Removes passwords, API keys, JWT tokens, and authorization headers from log strings."""
    if not message:
        return ""
    
    sanitized = sanitize_connection_string(str(message))
    
    # Redact Bearer tokens
    sanitized = re.sub(r'Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*', 'Bearer [REDACTED_TOKEN]', sanitized, flags=re.IGNORECASE)
    # Redact common API key parameters
    sanitized = re.sub(r'(api_key|secret|token)\s*=\s*[\'"]?[^\s;\'"]+[\'"]?', r'\1=[REDACTED]', sanitized, flags=re.IGNORECASE)
    
    return sanitized


SENSITIVE_KEY_PATTERNS = {
    "password", "passwd", "secret", "token", "access_token", "refresh_token",
    "api_key", "apikey", "authorization", "auth_header", "private_key",
    "connection_string", "dsn", "cookie", "credential", "client_secret"
}


def is_sensitive_key(key: str) -> bool:
    k_lower = key.lower().strip()
    return any(pattern in k_lower for pattern in SENSITIVE_KEY_PATTERNS)


def sanitize_payload(
    data: Any,
    max_depth: int = 8,
    current_depth: int = 0,
    max_size_bytes: int = 65536
) -> Any:
    """
    Recursively redacts sensitive credentials, tokens, and keys from arbitrary nested payloads.
    Enforces maximum nesting depth and safe payload size boundaries.
    """
    if current_depth > max_depth:
        return "[MAX_DEPTH_EXCEEDED]"

    if data is None:
        return None

    if isinstance(data, (int, float, bool)):
        return data

    if isinstance(data, str):
        if len(data) > 8192:
            return sanitize_log_message(data[:8192]) + "...[TRUNCATED]"
        return sanitize_log_message(data)

    if isinstance(data, dict):
        sanitized_dict = {}
        for k, v in data.items():
            k_str = str(k)
            if is_sensitive_key(k_str):
                sanitized_dict[k_str] = "[REDACTED]"
            else:
                sanitized_dict[k_str] = sanitize_payload(
                    v,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                    max_size_bytes=max_size_bytes
                )
        return sanitized_dict

    if isinstance(data, (list, tuple, set)):
        # Bound list items to avoid massive audit payload bloat
        items_to_process = list(data)[:50]
        sanitized_list = [
            sanitize_payload(item, max_depth=max_depth, current_depth=current_depth + 1, max_size_bytes=max_size_bytes)
            for item in items_to_process
        ]
        if len(data) > 50:
            sanitized_list.append(f"...[{len(data) - 50} items truncated]")
        return sanitized_list

    # Fallback for complex/Pydantic objects
    try:
        if hasattr(data, "dict"):
            return sanitize_payload(data.dict(), max_depth=max_depth, current_depth=current_depth + 1)
        return sanitize_log_message(str(data))
    except Exception:
        return "[UNSERIALIZABLE_OBJECT]"

