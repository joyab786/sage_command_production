# backend/server.py
"""
SageCommand V3 FastAPI Server Entrypoint
Mounts CORS middleware, Security Headers, Request Size Limiter, API routes, WebSocket nervous system, and background simulation loop.
"""

import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from core.config import SAGE_ALLOWED_ORIGINS, IS_PRODUCTION
    from governance.middleware import (
        SecurityHeadersMiddleware,
        RequestSizeLimiterMiddleware,
        safe_production_exception_handler
    )
    from services.simulator import run_factory_simulation_loop
    from api.routes import router as api_router
    from api.websocket import router as ws_router
    from api.database_routes import router as database_router
    from api.action_routes import router as action_router
    from api.policy_routes import router as policy_router
    from api.authorization_routes import router as authorization_router
    from api.audit_routes import router as audit_router
    from api.transaction_routes import router as transaction_router
    from api.ontology_routes import router as ontology_router
except (ImportError, ModuleNotFoundError):
    from backend.core.config import SAGE_ALLOWED_ORIGINS, IS_PRODUCTION
    from backend.governance.middleware import (
        SecurityHeadersMiddleware,
        RequestSizeLimiterMiddleware,
        safe_production_exception_handler
    )
    from backend.services.simulator import run_factory_simulation_loop
    from backend.api.routes import router as api_router
    from backend.api.websocket import router as ws_router
    from backend.api.database_routes import router as database_router
    from backend.api.action_routes import router as action_router
    from backend.api.policy_routes import router as policy_router
    from backend.api.authorization_routes import router as authorization_router
    from backend.api.audit_routes import router as audit_router
    from backend.api.transaction_routes import router as transaction_router
    from backend.api.ontology_routes import router as ontology_router

app = FastAPI(title="SageCommand V3 Industrial Operations AI OS")

# Production Exception Handler (Prevents internal tracebacks/credentials in 500 error responses)
app.add_exception_handler(Exception, safe_production_exception_handler)

# Security Middleware Pipeline
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimiterMiddleware)

# CORS Configuration Hardening
# Production must NOT use allow_origins=["*"] together with allow_credentials=True.
raw_origins = SAGE_ALLOWED_ORIGINS if isinstance(SAGE_ALLOWED_ORIGINS, list) else [SAGE_ALLOWED_ORIGINS]
filtered_origins = [o.strip() for o in raw_origins if o and o.strip() != "*"]

if IS_PRODUCTION:
    # Fail safely: require explicit production origins; never allow wildcard with credentials
    cors_origins = filtered_origins
    allow_creds = True if cors_origins else False
else:
    # Development: permit explicit dev origins (default to localhost:3000 / 127.0.0.1:3000)
    cors_origins = filtered_origins if filtered_origins else ["http://localhost:3000", "http://127.0.0.1:3000"]
    allow_creds = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_creds,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


# --- STARTUP LIFECYCLE HOOK & ANOMALY TRIGGER ---
@app.on_event("startup")
async def startup_event():
    """Launches the background event-driven factory anomaly generator loop."""
    print(" [Server Startup] Launching Factory Simulator background anomaly generator...")
    asyncio.create_task(run_factory_simulation_loop(interval_seconds=40))

# Include API Routers
app.include_router(api_router)
app.include_router(ws_router)
app.include_router(database_router)
app.include_router(action_router)
app.include_router(policy_router)
app.include_router(authorization_router)
app.include_router(audit_router)
app.include_router(transaction_router)
app.include_router(ontology_router)

# BOOT SEQUENCE
if __name__ == "__main__":
    print(" Firing up the SageCommand V3 server...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
