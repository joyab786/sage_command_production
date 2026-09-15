# backend/governance/middleware.py
import uuid
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from core.config import SAGE_MAX_REQUEST_SIZE, IS_PRODUCTION
    from governance.redaction import sanitize_log_message
    from governance.audit import log_security_event
except ModuleNotFoundError:
    from backend.core.config import SAGE_MAX_REQUEST_SIZE, IS_PRODUCTION
    from backend.governance.redaction import sanitize_log_message
    from backend.governance.audit import log_security_event


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces standard HTTP security response headers."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self' ws: wss:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval';"
        return response


class RequestSizeLimiterMiddleware(BaseHTTPMiddleware):
    """Rejects HTTP payloads exceeding configured SAGE_MAX_REQUEST_SIZE limit."""
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > SAGE_MAX_REQUEST_SIZE:
            log_security_event(
                "SECURITY_POLICY_BLOCKED",
                {"reason": "Request size exceeded limit", "content_length": content_length},
                severity="WARNING"
            )
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": f"Payload size exceeds maximum allowed limit ({SAGE_MAX_REQUEST_SIZE} bytes)."
                    }
                }
            )
        return await call_next(request)


async def safe_production_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler. Returns safe, sanitized error responses
    without exposing backend tracebacks, internal file paths, or credentials.
    """
    request_id = str(uuid.uuid4())
    error_code = "INTERNAL_SERVER_ERROR"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    
    if isinstance(exc, PermissionError):
        error_code = "PERMISSION_DENIED"
        status_code = status.HTTP_403_FORBIDDEN
        user_msg = str(exc)
    elif isinstance(exc, HTTPException):
        error_code = "HTTP_ERROR"
        status_code = exc.status_code
        user_msg = exc.detail
    elif IS_PRODUCTION:
        user_msg = "An internal operational error occurred. Please contact system administrator."
    else:
        user_msg = sanitize_log_message(str(exc))
        
    print(f" [Error Handler] [{request_id}] Error: {sanitize_log_message(str(exc))}")
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error_code,
                "message": user_msg,
                "request_id": request_id
            }
        }
    )
