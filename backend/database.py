from sqlalchemy import create_engine, text
import sqlite3
import os

# The default fallback database file
DEFAULT_DB_PATH = "./dynamic_datacore.sqlite"
DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"

def _ensure_valid_sqlite(path: str):
    """
    Checks if the file at `path` is a valid SQLite database.
    If it's corrupted or empty (not a real SQLite file), deletes it
    so SQLAlchemy can create a fresh one.
    """
    if not os.path.exists(path):
        return  # File doesn't exist yet — SQLAlchemy will create it
    
    try:
        conn = sqlite3.connect(path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
        conn.close()
    except sqlite3.DatabaseError:
        print(f"[WARNING] Corrupted database detected at '{path}'. Resetting to a clean state.")
        conn.close()
        os.remove(path)

# Validate before connecting
_ensure_valid_sqlite(DEFAULT_DB_PATH)

# If the file doesn't exist, this will create an empty valid SQLite DB on boot
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

print(f"[OK] Secure tether established to {DATABASE_URL}")