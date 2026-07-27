# Maintenance & Troubleshooting Guide

## 1. Database Locks (`database is locked` error)
**Symptom:** LangGraph throws a `sqlite3.OperationalError: database is locked`.
**Cause:** Two threads or processes are attempting to write to `sage_memory.sqlite` or `dynamic_datacore.sqlite` concurrently.
**Resolution:**
- The FastAPI server runs the graph invocation inside `asyncio.to_thread()`. Ensure that you are passing `connect_args={"check_same_thread": False}` when creating your SQLAlchemy engine in `tools.py`.
- If memory corruption occurs, safely delete the `sage_memory.sqlite` file. The `SqliteSaver` will automatically regenerate it on the next run.

## 2. LLM Inference Timeouts
**Symptom:** The graph freezes during execution, and the UI hangs.
**Cause:** The primary LLM provider (e.g., Groq) is rate-limiting the request or experiencing an outage.
**Resolution:**
- Check the console logs. You should see a `[LLM Failover]` print statement.
- Ensure that your `.env` contains the backup `GEMINI_API_KEY`. The resilience wrapper in `agent_graph.py` requires a valid fallback key to function.

## 3. WebSocket Disconnections
**Symptom:** The frontend UI stops updating, and the console shows `WebSocket connection closed`.
**Cause:** Development servers frequently restart upon file changes, severing the connection.
**Resolution:**
- The frontend features automatic reconnection logic. Hard-refresh the page (Ctrl+F5).
- If running in production, ensure your load balancer (e.g., Nginx) is configured to proxy `Upgrade: websocket` headers correctly.

## 4. Resetting the Application State
To clear all memory, time-travel checkpoints, and mounted databases for a fresh start:
1. Stop the backend server.
2. Delete `/backend/sage_memory.sqlite*` files.
3. Delete `/backend/dynamic_datacore.sqlite`.
4. Restart the server.
