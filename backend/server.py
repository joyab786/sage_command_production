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
    from core.config import SAGE_ALLOWED_ORIGINS
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
except (ImportError, ModuleNotFoundError):
    from backend.core.config import SAGE_ALLOWED_ORIGINS
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

app = FastAPI(title="SageCommand V3 Industrial Operations AI OS")

# Production Exception Handler (Prevents internal tracebacks/credentials in 500 error responses)
app.add_exception_handler(Exception, safe_production_exception_handler)

# Security Middleware Pipeline
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimiterMiddleware)

# CORS Configuration
origins = SAGE_ALLOWED_ORIGINS if isinstance(SAGE_ALLOWED_ORIGINS, list) else [SAGE_ALLOWED_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
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

# BOOT SEQUENCE
if __name__ == "__main__":
    print(" Firing up the SageCommand V3 server...")
    uvicorn.run(app, host="127.0.0.1", port=8000)

