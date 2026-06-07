import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine
import pandas as pd
import shutil
import json
import os

# Import your dynamic database wrapper (assuming it's in tools.py)
from tools import dynamic_db

# Import the compiled LangGraph agent
from agent_graph import sage_app
from langchain_core.messages import HumanMessage

app = FastAPI()

# Allow Next.js frontend to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. LIVE DB URI TETHER ---
class LiveDBConnection(BaseModel):
    connection_string: str

@app.post("/connect-live-db")
async def connect_live_db(payload: LiveDBConnection):
    """Takes a live database URI, verifies it, and hot-swaps the AI's brain."""
    try:
        new_engine = create_engine(payload.connection_string)
        
        # Test the connection
        with new_engine.connect() as conn:
            pass 
        
        # Hot-Swap the AI's internal tools
        dynamic_db.update_engine(new_engine)
        table_names = dynamic_db.db.get_usable_table_names()
        
        return {
            "status": "success", 
            "message": f"Live tether established. Detected {len(table_names)} tables.",
            "tables": table_names
        }
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}

# --- 2. UNIVERSAL DATACORE UPLINK (Supports SQLite & CSV) ---
@app.post("/upload-db")
async def upload_database(file: UploadFile = File(...)):
    """Receives a file, compiles it to SQL if it's a CSV, and hot-swaps the brain."""
    try:
        file_location = f"./dynamic_datacore.sqlite"
        
        # Handle CSV Files
        if file.filename.endswith(".csv"):
            df = pd.read_csv(file.file)
            table_name = file.filename.rsplit('.', 1)[0].replace(" ", "_").replace("-", "_").lower()
            
            new_engine = create_engine(f"sqlite:///{file_location}", connect_args={"check_same_thread": False})
            df.to_sql(table_name, con=new_engine, if_exists="replace", index=False)
            
            dynamic_db.update_engine(new_engine)
            return {"status": "success", "message": f"CSV compiled to SQL. Table '{table_name}' mounted successfully."}

        # Handle SQLite/DB Files
        elif file.filename.endswith((".sqlite", ".db")):
            with open(file_location, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            new_engine = create_engine(f"sqlite:///{file_location}", connect_args={"check_same_thread": False})
            dynamic_db.update_engine(new_engine)
            return {"status": "success", "message": f"Datacore {file.filename} mounted successfully."}
            
        else:
            return {"status": "error", "message": "Unsupported file format. Please upload .csv, .db, or .sqlite"}

    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- 3. THE WEBSOCKET NERVOUS SYSTEM ---
@app.websocket("/ws/sage")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # Unique thread ID per session for LangGraph memory
    thread_id = id(websocket)
    config = {"configurable": {"thread_id": str(thread_id)}}
    
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            command = payload.get("command")
            
            if command == "chat":
                user_input = payload.get("text")
                
                # Send a processing update to the UI
                await websocket.send_text(json.dumps({"type": "node_update", "node": "Strategic Copilot"}))
                
                # --- INVOKE THE REAL LANGGRAPH AGENT ---
                try:
                    input_state = {"messages": [HumanMessage(content=user_input)]}
                    result = sage_app.invoke(input_state, config=config)
                    
                    # Extract the last AI message from the result
                    messages = result.get("messages", [])
                    final_text = "No response generated."
                    for msg in reversed(messages):
                        if hasattr(msg, 'content') and msg.content and not hasattr(msg, 'tool_calls'):
                            final_text = msg.content
                            break
                        elif hasattr(msg, 'content') and msg.content:
                            # It might be an AI message with tool results
                            if not getattr(msg, 'tool_calls', None):
                                final_text = msg.content
                                break
                    
                    await websocket.send_text(json.dumps({
                        "type": "chat_response", 
                        "text": final_text
                    }))
                except Exception as e:
                    error_msg = f"Agent error: {str(e)}"
                    print(f" Agent invocation error: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "chat_response",
                        "text": error_msg
                    }))
                    
            elif command == "scan":
                # Trigger Guardrail Intercept
                await websocket.send_text(json.dumps({
                    "type": "node_update", "node": "Discovery Agent"
                }))
                try:
                    # Run the autonomous discovery pipeline
                    input_state = {"messages": []}
                    result = sage_app.invoke(input_state, config={"configurable": {"thread_id": f"scan-{thread_id}"}})
                    
                    anomaly = result.get("anomaly_details", {})
                    strategies = result.get("generated_strategies", [])
                    best = result.get("utility_evaluation", {})
                    
                    await websocket.send_text(json.dumps({
                        "type": "guardrail_interrupt",
                        "payload": {
                            "action": best.get("action", strategies[0]["action"] if strategies else "No action determined"),
                            "justification": best.get("justification", anomaly.get("details", "Anomaly detected during scan."))
                        }
                    }))
                except Exception as e:
                    print(f" Scan pipeline error: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "guardrail_interrupt",
                        "payload": {
                            "action": "Manual Inspection Required",
                            "justification": f"Autonomous scan encountered an error: {str(e)}"
                        }
                    }))
                
            elif command == "approve":
                await websocket.send_text(json.dumps({"type": "log", "message": "[AGENT] > Human authorization granted. Resuming execution pipeline..."}))
                try:
                    # Resume the LangGraph agent past the interrupt point
                    scan_config = {"configurable": {"thread_id": f"scan-{thread_id}"}}
                    result = sage_app.invoke(None, config=scan_config)
                    await websocket.send_text(json.dumps({"type": "status", "status": "ONLINE"}))
                    await websocket.send_text(json.dumps({"type": "log", "message": "[SUCCESS] > Execution committed to database."}))
                except Exception as e:
                    await websocket.send_text(json.dumps({"type": "status", "status": "ONLINE"}))

    except WebSocketDisconnect:
        print("UI Disconnected from Cortex.")

# --- BOOT SEQUENCE ---
if __name__ == "__main__":
    print(" Firing up the SageCommand server...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
