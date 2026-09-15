# backend/graph/checkpointer.py
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

try:
    from core.config import MEMORY_DB_PATH
except (ImportError, ModuleNotFoundError):
    from backend.core.config import MEMORY_DB_PATH

db_conn = sqlite3.connect(MEMORY_DB_PATH, check_same_thread=False)
memory = SqliteSaver(db_conn)
