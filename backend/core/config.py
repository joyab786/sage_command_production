# backend/core/config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- SYSTEM & ENVIRONMENT SETTINGS ---
SAGE_ENV = os.getenv("SAGE_ENV", "development").lower()
IS_PRODUCTION = (SAGE_ENV == "production")
SAGE_DEBUG = os.getenv("SAGE_DEBUG", "false").lower() in ("true", "1", "yes") if IS_PRODUCTION else True

# --- CORS & NETWORK SECURITY ---
DEFAULT_DEV_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000"
raw_origins = os.getenv("SAGE_ALLOWED_ORIGINS", DEFAULT_DEV_ORIGINS)
SAGE_ALLOWED_ORIGINS = [o.strip() for o in raw_origins.split(",") if o.strip()]

raw_hosts = os.getenv("SAGE_ALLOWED_HOSTS", "localhost,127.0.0.1")
SAGE_ALLOWED_HOSTS = [h.strip() for h in raw_hosts.split(",") if h.strip()]

# --- AUTHENTICATION CONFIGURATION ---
SAGE_AUTH_ENABLED = os.getenv("SAGE_AUTH_ENABLED", "false" if not IS_PRODUCTION else "true").lower() in ("true", "1", "yes")
SAGE_AUTH_PROVIDER = os.getenv("SAGE_AUTH_PROVIDER", "development" if not IS_PRODUCTION else "jwt").lower()
SAGE_AUTH_ISSUER = os.getenv("SAGE_AUTH_ISSUER", "https://auth.sagecommand.io")
SAGE_AUTH_AUDIENCE = os.getenv("SAGE_AUTH_AUDIENCE", "sagecommand_api")
SAGE_SECRET_KEY = os.getenv("SAGE_SECRET_KEY", "sagecommand_default_dev_secret_key_change_in_production")

# --- REQUEST & RESOURCE BOUNDARIES ---
SAGE_MAX_REQUEST_SIZE = int(os.getenv("SAGE_MAX_REQUEST_SIZE", 10 * 1024 * 1024))  # 10 MB default limit
SAGE_RATE_LIMIT = int(os.getenv("SAGE_RATE_LIMIT", 60))  # 60 requests per minute
SAGE_DB_CONNECTION_TIMEOUT = int(os.getenv("SAGE_DB_CONNECTION_TIMEOUT", 10))  # 10 seconds
SAGE_DB_POOL_SIZE = int(os.getenv("SAGE_DB_POOL_SIZE", 5))

# --- DATABASE GATEWAY SECURITY CONFIGURATION ---
SAGE_DB_NETWORK_POLICY = os.getenv("SAGE_DB_NETWORK_POLICY", "RESTRICTED").upper()
raw_allowed_db_hosts = os.getenv("SAGE_DB_ALLOWED_HOSTS") or os.getenv("SAGE_ALLOWED_DB_HOSTS") or ("localhost,127.0.0.1" if not IS_PRODUCTION else "")
SAGE_DB_ALLOWED_HOSTS = [h.strip().lower() for h in raw_allowed_db_hosts.split(",") if h.strip()]
raw_allowed_db_ports = os.getenv("SAGE_DB_ALLOWED_PORTS", "5432,3306,1433")
SAGE_DB_ALLOWED_PORTS = [int(p.strip()) for p in raw_allowed_db_ports.split(",") if p.strip().isdigit()]
SAGE_DB_SSL_POLICY = os.getenv("SAGE_DB_SSL_POLICY", "REQUIRED").upper()
SAGE_DB_MAX_SAMPLE_ROWS = int(os.getenv("SAGE_DB_MAX_SAMPLE_ROWS", 5))
SAGE_DB_IDLE_TIMEOUT = int(os.getenv("SAGE_DB_IDLE_TIMEOUT", 1800))  # 30 minutes
SAGE_DB_MAX_LIFETIME = int(os.getenv("SAGE_DB_MAX_LIFETIME", 86400))  # 24 hours

# --- SENSITIVE DATA & LOGGING ---
SAGE_LOG_SENSITIVE_DATA = os.getenv("SAGE_LOG_SENSITIVE_DATA", "false").lower() in ("true", "1", "yes")

# --- LLM API KEYS ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# --- DATABASE & LEDGER PATHS ---
DEFAULT_DB_PATH = "./dynamic_datacore.sqlite"
MEMORY_DB_PATH = "sage_memory.sqlite"
SAGE_AUDIT_LEDGER_DB_PATH = os.getenv("SAGE_AUDIT_LEDGER_DB_PATH", "sage_audit_ledger.sqlite")
SAGE_AUDIT_MAX_PAYLOAD_SIZE = int(os.getenv("SAGE_AUDIT_MAX_PAYLOAD_SIZE", 65536))  # 64 KB

# --- TRANSACTION & ROLLBACK CONFIGURATION ---
SAGE_TRANSACTIONS_DB_PATH = os.getenv("SAGE_TRANSACTIONS_DB_PATH", "sage_transactions.sqlite")
SAGE_TRANSACTION_DEFAULT_TTL_SECONDS = int(os.getenv("SAGE_TRANSACTION_DEFAULT_TTL_SECONDS", 3600))  # 1 hour
SAGE_TRANSACTION_MAX_PAYLOAD_SIZE = int(os.getenv("SAGE_TRANSACTION_MAX_PAYLOAD_SIZE", 65536))  # 64 KB

