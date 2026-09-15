# backend/database.py
"""
SageCommand V3 Database Module (Backward Compatibility Wrapper)
"""

try:
    from services.db_service import default_engine as engine, DEFAULT_DB_PATH
except ModuleNotFoundError:
    from backend.services.db_service import default_engine as engine, DEFAULT_DB_PATH

DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"

print(f"[OK] Secure tether established to {DATABASE_URL}")