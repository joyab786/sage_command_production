# SageCommand V3 — Production Security Migration Guide

## 1. Overview
This guide provides step-by-step instructions for migrating existing SageCommand V2 or V3 pre-hardening deployments to the **V3 Hardened Production Security Architecture**.

---

## 2. Pre-Migration Checklist

- [x] Verify backend environment running Python 3.10+ in `backend/venv`.
- [x] Ensure all unit test suites pass prior to configuration updates (`python -m unittest test_suite.py test_v3_architecture.py test_v3_schemas.py test_v3_security.py`).
- [x] Obtain production JWT Issuer / Audience details if migrating to production authentication.

---

## 3. Step-by-Step Migration Process

### Step 1: Update Environment Variables (`backend/.env`)
Create or update `backend/.env` with production settings:

```env
# System & Environment
SAGE_ENV=production
SAGE_DEBUG=false

# Authentication
SAGE_AUTH_ENABLED=true
SAGE_AUTH_PROVIDER=jwt
SAGE_AUTH_ISSUER=https://auth.yourorganization.com
SAGE_AUTH_AUDIENCE=sagecommand_api
SAGE_SECRET_KEY=your_strong_random_secret_key_here

# CORS & Network Restrictions
SAGE_ALLOWED_ORIGINS=https://sage.yourorganization.com
SAGE_ALLOWED_HOSTS=sage.yourorganization.com,api.yourorganization.com

# Request & Resource Ceilings
SAGE_MAX_REQUEST_SIZE=10485760
SAGE_RATE_LIMIT=60
SAGE_DB_CONNECTION_TIMEOUT=10
```

### Step 2: Update REST API Client Authorization Headers
In client applications (e.g. Next.js 16 frontend), attach Bearer tokens to all REST API requests:

```typescript
const response = await fetch("http://localhost:8000/trigger-anomaly", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${userToken}`,
  },
  body: JSON.stringify({ anomaly_type: "OVERHEAT" }),
});
```

### Step 3: Update WebSocket Nervous System Handshake
In WebSocket client connections, pass the authentication token as a query parameter or connection header:

```typescript
const ws = new WebSocket(`ws://localhost:8000/ws/sage?token=${encodeURIComponent(userToken)}`);
```

### Step 4: Verify Database Connection Strings
Ensure all database connection strings use approved schemes (`postgresql://`, `mysql://`, `sqlite://`). Unapproved schemes (`file://`, `ftp://`) will be rejected with HTTP 400 Bad Request.

---

## 4. Rollback & Troubleshooting

### Temporary Dev Mode Fallback
If deployment issues occur during initial OAuth/JWT identity provider setup, fallback to development authentication mode in `backend/.env`:

```env
SAGE_ENV=development
SAGE_AUTH_ENABLED=false
SAGE_AUTH_PROVIDER=development
```

This restores dev identity handling without modifying code logic.
