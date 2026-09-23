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
    from api.knowledge_graph_routes import router as knowledge_graph_router
    from api.digital_twin_routes import router as digital_twin_router
    from api.data_quality_routes import router as data_quality_router
    from api.anomaly_routes import router as anomaly_router
    from api.event_routes import router as event_router
    from api.event_bus_routes import router as event_bus_router
    from api.incident_routes import router as incident_router
    from api.rca_routes import router as rca_router
    from api.blast_radius_routes import router as blast_radius_router
    from api.predictive_maintenance_routes import router as predictive_maintenance_router
    from api.demand_forecasting_routes import router as demand_forecasting_router
    from api.supplier_risk_routes import router as supplier_risk_router
    from api.sla_customer_risk_routes import router as sla_customer_risk_router
    from services.event_bus import get_event_bus
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
    from backend.api.knowledge_graph_routes import router as knowledge_graph_router
    from backend.api.digital_twin_routes import router as digital_twin_router
    from backend.api.data_quality_routes import router as data_quality_router
    from backend.api.anomaly_routes import router as anomaly_router
    from backend.api.event_routes import router as event_router
    from backend.api.event_bus_routes import router as event_bus_router
    from backend.api.incident_routes import router as incident_router
    from backend.api.rca_routes import router as rca_router
    from backend.api.blast_radius_routes import router as blast_radius_router
    from backend.api.predictive_maintenance_routes import router as predictive_maintenance_router
    from backend.api.demand_forecasting_routes import router as demand_forecasting_router
    from backend.api.supplier_risk_routes import router as supplier_risk_router
    from backend.api.sla_customer_risk_routes import router as sla_customer_risk_router
    from backend.services.event_bus import get_event_bus

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


# --- STARTUP/SHUTDOWN LIFECYCLE HOOKS ---
@app.on_event("startup")
async def startup_event():
    """Launches the background event-driven factory anomaly generator loop and internal event bus."""
    print(" [Server Startup] Launching Internal Event Bus workers...")
    event_bus = get_event_bus()
    event_bus.start()
    print(" [Server Startup] Launching Factory Simulator background anomaly generator...")
    asyncio.create_task(run_factory_simulation_loop(interval_seconds=40))

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shuts down background services."""
    print(" [Server Shutdown] Stopping Internal Event Bus workers...")
    event_bus = get_event_bus()
    await event_bus.stop()

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
app.include_router(knowledge_graph_router)
app.include_router(digital_twin_router)
app.include_router(data_quality_router)
app.include_router(anomaly_router)
app.include_router(event_router)
app.include_router(event_bus_router)
app.include_router(incident_router)
app.include_router(rca_router)
app.include_router(blast_radius_router)
app.include_router(predictive_maintenance_router)
app.include_router(demand_forecasting_router)
app.include_router(supplier_risk_router)
app.include_router(sla_customer_risk_router)

# BOOT SEQUENCE
if __name__ == "__main__":
    print(" Firing up the SageCommand V3 server...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
