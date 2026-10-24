# 🚀 SageCommand V3 — Production Deployment & Infrastructure Guide

> **System**: SageCommand V3 Enterprise Autonomous & Operational Intelligence OS  
> **Target Environments**: Docker Swarm, Kubernetes, Bare Metal Linux, Railway, AWS ECS / EC2, Vercel  
> **Audience**: DevSecOps Engineers, Site Reliability Engineers (SRE), and Infrastructure Architects  

---

## 📋 1. Infrastructure Prerequisites

| Component | Minimum Specification | Recommended Production Specification |
|:---|:---|:---|
| **CPU** | 4 vCPU cores | 8–16 vCPU cores (x86_64 or ARM64) |
| **Memory** | 8 GB RAM | 16–32 GB RAM |
| **Disk Storage** | 20 GB SSD | 100+ GB NVMe SSD (Persistent Volume) |
| **Python** | Python 3.10+ | Python 3.11+ |
| **Node.js** | Node.js v18.x | Node.js v20.x LTS |
| **Network** | Outbound HTTPS (Port 443) | Outbound HTTPS with strict egress proxies |
| **External LLM Access** | Groq API Key / Google Gemini API Key | Groq Enterprise Tier + Google Gemini Vertex AI |

---

## ⚙️ 2. Comprehensive Environment Variable Specification

Create a secure `.env` file in the `/backend` directory:

```bash
# ==============================================================================
# 1. CORE ENVIRONMENT & SYSTEM SETTINGS
# ==============================================================================
SAGE_ENV=production                               # 'development', 'test', or 'production' (defaults to production fail-closed)
SAGE_DEBUG=false                                  # Must be false in production
SAGE_MAX_REQUEST_SIZE=10485760                    # 10 MB maximum request payload
SAGE_RATE_LIMIT=120                               # Requests per minute per IP

# ==============================================================================
# 2. CORS & NETWORK SECURITY
# ==============================================================================
# Explicitly allowlisted web origins (Never use '*' with credentials in production)
SAGE_ALLOWED_ORIGINS=https://sage.yourdomain.com,https://console.yourdomain.com
SAGE_ALLOWED_HOSTS=api.yourdomain.com,localhost,127.0.0.1

# ==============================================================================
# 3. AUTHENTICATION & ZERO-TRUST JWT
# ==============================================================================
SAGE_AUTH_ENABLED=true                            # Enforces fail-closed authentication (mandatory in production)
SAGE_AUTH_PROVIDER=jwt                            # Must be 'jwt' in production (dev_auth refuses to boot in production)
SAGE_SECRET_KEY=generate_a_cryptographically_secure_64_char_key_here # Must not be default and >= 32 bytes
SAGE_AUTH_ISSUER=https://auth.yourdomain.com      # Required in production
SAGE_AUTH_AUDIENCE=sagecommand_api                # Required in production
SAGE_JWT_ALGORITHMS=HS256                         # HS256 only in production (RS256 removed until JWKS implemented; 'none' prohibited)
SAGE_AUTH_SESSION_CLAIM=session_id                # Configurable session claim name; falls back to 'sid' if omitted

# ==============================================================================
# 4. DATABASE GATEWAY SECURITY & NETWORK POLICIES
# ==============================================================================
SAGE_DB_NETWORK_POLICY=RESTRICTED                 # 'OPEN' or 'RESTRICTED'
# SAGE_DB_ALLOWED_HOSTS defaults to empty (deny). Private IP ranges and loopbacks are blocked in production unless explicitly listed here:
SAGE_DB_ALLOWED_HOSTS=db-prod.internal,db-replica.internal,10.0.1.15
SAGE_DB_ALLOWED_PORTS=5432,3306,1433
SAGE_DB_SSL_POLICY=REQUIRED                       # 'REQUIRED', 'VERIFY_CA', 'OPTIONAL'
SAGE_DB_CONNECTION_TIMEOUT=15
SAGE_DB_POOL_SIZE=10
SAGE_DB_IDLE_TIMEOUT=1800                         # 30 minutes
SAGE_DB_MAX_LIFETIME=86400                        # 24 hours
SAGE_DB_MAX_SAMPLE_ROWS=5

# ==============================================================================
# 5. LLM PROVIDERS & EXTERNAL INTELLIGENCE
# ==============================================================================
GROQ_API_KEY=gsk_your_groq_production_key_here
GEMINI_API_KEY=AIzaSy_your_gemini_production_key_here
GOOGLE_API_KEY=AIzaSy_your_gemini_production_key_here
TAVILY_API_KEY=tvly-your_tavily_search_api_key_here

# ==============================================================================
# 6. PERSISTENT STORAGE PATHS (Mount to NVMe Volume)
# ==============================================================================
DEFAULT_DB_PATH=/var/data/sage/dynamic_datacore.sqlite
MEMORY_DB_PATH=/var/data/sage/sage_memory.sqlite
SAGE_AUDIT_LEDGER_DB_PATH=/var/data/sage/sage_audit_ledger.sqlite
SAGE_TRANSACTIONS_DB_PATH=/var/data/sage/sage_transactions.sqlite
SAGE_ONTOLOGY_DB_PATH=/var/data/sage/sage_ontology.sqlite
SAGE_KNOWLEDGE_GRAPH_DB_PATH=/var/data/sage/sage_knowledge_graph.sqlite
SAGE_DIGITAL_TWIN_DB_PATH=/var/data/sage/sage_digital_twin.sqlite
SAGE_DATA_QUALITY_DB_PATH=/var/data/sage/sage_data_quality.sqlite
SAGE_EVENT_DELIVERY_DB_PATH=/var/data/sage/sage_event_delivery.sqlite
SAGE_INCIDENT_DB_PATH=/var/data/sage/sage_incidents.sqlite
SAGE_RCA_DB_PATH=/var/data/sage/sage_rca.sqlite
SAGE_BLAST_RADIUS_DB_PATH=/var/data/sage/sage_blast_radius.sqlite
SAGE_PREDICTIVE_MAINTENANCE_DB_PATH=/var/data/sage/sage_predictive_maintenance.sqlite
SAGE_DEMAND_FORECASTING_DB_PATH=/var/data/sage/sage_demand_forecasting.sqlite
SAGE_SUPPLIER_RISK_DB_PATH=/var/data/sage/sage_supplier_risk.sqlite
SAGE_SLA_CUSTOMER_RISK_DB_PATH=/var/data/sage/sage_sla_customer_risk.sqlite
SAGE_FINANCIAL_IMPACT_DB_PATH=/var/data/sage/sage_financial_impact.sqlite
SAGE_SUSTAINABILITY_DB_PATH=/var/data/sage/sage_sustainability.sqlite
SAGE_SENSOR_FUSION_DB_PATH=/var/data/sage/sage_sensor_fusion.sqlite
SAGE_WHAT_IF_SIMULATION_DB_PATH=/var/data/sage/sage_what_if_simulation.sqlite
SAGE_OPTIMIZATION_DB_PATH=/var/data/sage/sage_optimization.sqlite
SAGE_DECISION_ENGINE_DB_PATH=/var/data/sage/sage_decision_engine.sqlite
SAGE_EVIDENCE_EXPLAINABILITY_DB_PATH=/var/data/sage/sage_evidence_explainability.sqlite
SAGE_CONFIDENCE_UNCERTAINTY_DB_PATH=/var/data/sage/sage_confidence_uncertainty.sqlite
SAGE_SOP_RAG_DB_PATH=/var/data/sage/sage_sop_rag.sqlite
SAGE_ORGANIZATIONAL_MEMORY_DB_PATH=/var/data/sage/sage_organizational_memory.sqlite
SAGE_MISSION_DB_PATH=/var/data/sage/sage_missions.sqlite
SAGE_VERIFICATION_DB_PATH=/var/data/sage/sage_verification.sqlite
SAGE_AUTONOMY_DB_PATH=/var/data/sage/sage_autonomy.sqlite

# ==============================================================================
# 7. CLOSED-LOOP LEARNING & EVENT BUS SETTINGS
# ==============================================================================
SAGE_EVENT_BUS_ENABLED=true
SAGE_EVENT_BUS_QUEUE_SIZE=5000
SAGE_EVENT_BUS_MAX_WORKERS=8
SAGE_EVENT_BUS_MAX_RETRIES=3
SAGE_CLOSED_LOOP_ENABLED=true
SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED=true
SAGE_CLOSED_LOOP_SUBSCRIPTION_SCOPES=tenant_prod:workspace_main:plant_01,tenant_prod:workspace_main:plant_02
SAGE_OUTCOME_EVALUATION_ENABLED=true
```

---

## 🐳 3. Containerized Deployment (Docker & Compose)

### Backend Containerization (`Dockerfile.backend`)
```dockerfile
FROM python:3.11-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim AS runner
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY . .

# Create volume mount directory for SQLite databases
RUN mkdir -p /var/data/sage && chown -R 1000:1000 /var/data/sage

USER 1000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers"]
```

### Production Docker Compose (`docker-compose.prod.yml`)
```yaml
version: '3.8'

services:
  cortex-backend:
    build:
      context: ./backend
      dockerfile: Dockerfile.backend
    container_name: sage_cortex_backend
    restart: always
    env_file: ./backend/.env
    volumes:
      - sage_storage:/var/data/sage
    ports:
      - "8000:8000"
    networks:
      - sage_internal

  command-frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.frontend
    container_name: sage_command_frontend
    restart: always
    environment:
      - NEXT_PUBLIC_WS_URL=wss://api.sagecommand.com/ws/sage
      - NEXT_PUBLIC_API_URL=https://api.sagecommand.com
    ports:
      - "3000:3000"
    networks:
      - sage_internal

volumes:
  sage_storage:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /mnt/sage_nvme_data

networks:
  sage_internal:
    driver: bridge
```

---

## 🌐 4. Nginx Reverse Proxy & WebSocket Configuration

To ensure uninterrupted WebSocket connections (`/ws/sage`) and enforce strict transport security, configure Nginx:

```nginx
# /etc/nginx/sites-available/sagecommand.conf

upstream fastapi_cortex {
    server 127.0.0.1:8000;
    keepalive 64;
}

upstream nextjs_frontend {
    server 127.0.0.1:3000;
    keepalive 64;
}

server {
    listen 80;
    server_name api.sagecommand.com sage.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.sagecommand.com;

    ssl_certificate /etc/letsencrypt/live/api.sagecommand.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.sagecommand.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Maximum payload size (matches SAGE_MAX_REQUEST_SIZE)
    client_max_body_size 10M;

    # WebSocket nervous system endpoint
    location /ws/ {
        proxy_pass http://fastapi_cortex;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Keepalive timeouts for persistent industrial telemetry
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # REST API endpoints
    location / {
        proxy_pass http://fastapi_cortex;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 🔍 5. Verification & Post-Deployment Health Checks

After launching the infrastructure, run these verification steps:

1. **Verify API Health**:
   ```bash
   curl -I https://api.sagecommand.com/health
   # Expected: HTTP/2 200 OK
   ```

2. **Verify Security Headers**:
   ```bash
   curl -I https://api.sagecommand.com/health | grep -E "(X-Frame-Options|Content-Security-Policy|Strict-Transport-Security)"
   ```

3. **Verify WebSocket Handshake**:
   ```bash
   wscat -c "wss://api.sagecommand.com/ws/sage?token=manager_token&session_id=test_session"
   # Expected: Connected (press CTRL+C to quit)
   ```

4. **Verify Database WAL Mode**:
   ```bash
   sqlite3 /var/data/sage/dynamic_datacore.sqlite "PRAGMA journal_mode;"
   # Expected output: wal
   ```
