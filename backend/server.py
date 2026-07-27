import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine
import pandas as pd
import shutil
import json
import os
import asyncio

# Import your dynamic database wrapper (assuming it's in tools.py)
from tools import dynamic_db

# Import the compiled LangGraph agent
from agent_graph import sage_app, is_high_risk_action

from langchain_core.messages import HumanMessage

# Import Factory Anomaly Simulator
from simulate_factory import run_factory_simulation_loop, inject_random_anomaly

app = FastAPI()

# Allow Next.js frontend to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.post("/trigger-anomaly")
async def trigger_manual_anomaly():
    """Triggers an immediate factory anomaly for manual hands-free testing."""
    anomaly = inject_random_anomaly()
    return {"status": "success", "anomaly": anomaly}


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

# --- HELPER: Run sync LangGraph operations in a thread ---
def _invoke_graph(input_state, config):
    """Runs sage_app.invoke() synchronously in a background thread."""
    return sage_app.invoke(input_state, config=config)

def _get_state(config):
    """Runs sage_app.get_state() synchronously in a background thread."""
    return sage_app.get_state(config)

async def _emit_scan_telemetry(websocket: WebSocket, result: dict):
    """Emits node_active events based on which state fields were populated."""
    pipeline = []
    if result.get("anomaly_details"):
        pipeline.append("discovery")
    if result.get("blast_radius_analysis"):
        pipeline.append("risk_agent")
    if result.get("generated_strategies") is not None:
        pipeline.append("supervisor")
        pipeline.append("strategy_worker")
    if result.get("external_market_context"):
        pipeline.append("supervisor")
        pipeline.append("web_researcher")
    if result.get("utility_evaluation"):
        pipeline.append("supervisor")
        pipeline.append("evaluator")
    if result.get("next_worker") == "execution":
        pipeline.append("supervisor")

    
    for node_name in pipeline:
        await websocket.send_text(json.dumps({
            "type": "node_active",
            "node": node_name
        }))
        await asyncio.sleep(0.05)  # Small delay for UI animation

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
                await websocket.send_text(json.dumps({"type": "node_active", "node": "copilot_agent"}))
                
                # --- INVOKE THE LANGGRAPH AGENT IN A BACKGROUND THREAD ---
                try:
                    input_state = {"messages": [HumanMessage(content=user_input)]}
                    result = await asyncio.to_thread(_invoke_graph, input_state, config)
                    
                    # Intercept Security Intrusion Threat Detection
                    if result and result.get("security_status") == "CRITICAL_THREAT":
                        threat_details = result.get("threat_details", "Malicious input pattern detected.")
                        print(f" [Security Alert] Broadcasting intrusion alert: {threat_details}")
                        await websocket.send_text(json.dumps({
                            "type": "security_alert",
                            "threat_level": "CRITICAL",
                            "details": threat_details
                        }))
                        await websocket.send_text(json.dumps({
                            "type": "log",
                            "message": f"[SECURITY ALERT] > Graph execution halted by Security Agent: {threat_details}"
                        }))
                    else:
                        # Emit tool node telemetry if tools were called
                        messages = result.get("messages", [])
                        for msg in messages:
                            if getattr(msg, 'tool_calls', None):
                                await websocket.send_text(json.dumps({"type": "node_active", "node": "tools"}))
                                await asyncio.sleep(0.05)
                                await websocket.send_text(json.dumps({"type": "node_active", "node": "copilot_agent"}))
                                await asyncio.sleep(0.05)
                        
                        # Extract the last AI message from the result
                        final_text = "No response generated."
                        for msg in reversed(messages):
                            if hasattr(msg, 'content') and msg.content and not getattr(msg, 'tool_calls', None):
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

            elif command == "diagnostics_upload":
                image_data = payload.get("image_data")
                await websocket.send_text(json.dumps({"type": "node_update", "node": "Vision Diagnostics Agent"}))
                await websocket.send_text(json.dumps({"type": "node_active", "node": "vision_diagnostics_agent"}))
                
                try:
                    diag_config = {"configurable": {"thread_id": f"diag-{thread_id}"}}
                    input_state = {"image_data": image_data, "messages": []}
                    
                    def _stream_diag():
                        return list(sage_app.stream(input_state, config=diag_config, stream_mode="updates"))

                    events = await asyncio.to_thread(_stream_diag)
                    for event in events:
                        for node_name in event.keys():
                            await websocket.send_text(json.dumps({
                                "type": "node_active",
                                "node": node_name
                            }))
                            await asyncio.sleep(0.05)

                    state_snapshot = await asyncio.to_thread(_get_state, diag_config)
                    final_state = state_snapshot.values if state_snapshot else {}
                    
                    vision_result = final_state.get("vision_finding", {})
                    strategies = final_state.get("generated_strategies", [])
                    best = final_state.get("utility_evaluation", {})

                    if vision_result:
                        await websocket.send_text(json.dumps({
                            "type": "vision_result",
                            "data": vision_result
                        }))

                    if state_snapshot and state_snapshot.next and "execution" in state_snapshot.next:
                        await websocket.send_text(json.dumps({
                            "type": "graph_status",
                            "status": "INTERRUPTED",
                            "node": "execution"
                        }))
                        await websocket.send_text(json.dumps({
                            "type": "guardrail_interrupt",
                            "payload": {
                                "action": best.get("action", strategies[0]["action"] if strategies else "Order hardware replacement part."),
                                "justification": best.get("justification", f"Vision finding: {vision_result.get('part_identified')} - {vision_result.get('damage_assessment')}")
                            }
                        }))
                except Exception as e:
                    print(f" Vision diagnostics error: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "log",
                        "message": f"[ERROR] > Multi-modal hardware diagnostics failed: {str(e)}"
                    }))


                    
            elif command == "scan":
                # Trigger Autonomous Pipeline Telemetry
                await websocket.send_text(json.dumps({
                    "type": "node_update", "node": "Discovery Agent"
                }))
                try:
                    scan_config = {"configurable": {"thread_id": f"scan-{thread_id}"}}
                    input_state = {"messages": []}
                    
                    # Stream LangGraph node updates in real-time
                    def _stream_graph():
                        return list(sage_app.stream(input_state, config=scan_config, stream_mode="updates"))

                    events = await asyncio.to_thread(_stream_graph)
                    
                    # Broadcast active node telemetry events to frontend
                    for event in events:
                        for node_name in event.keys():
                            await websocket.send_text(json.dumps({
                                "type": "node_active",
                                "node": node_name
                            }))
                            await asyncio.sleep(0.05)  # Small delay for UI animation

                    # Check for Human-in-the-Loop interrupt gate before execution
                    state_snapshot = await asyncio.to_thread(_get_state, scan_config)
                    if state_snapshot.next and "execution" in state_snapshot.next:
                        await websocket.send_text(json.dumps({
                            "type": "graph_status",
                            "status": "INTERRUPTED",
                            "node": "execution"
                        }))
                        
                    final_state = state_snapshot.values if state_snapshot else {}
                    
                    if final_state.get("security_status") == "CRITICAL_THREAT":
                        threat_details = final_state.get("threat_details", "Malicious telemetry or scan anomaly pattern detected.")
                        print(f" [Security Alert] Autonomous scan halted by intrusion detection: {threat_details}")
                        await websocket.send_text(json.dumps({
                            "type": "security_alert",
                            "threat_level": "CRITICAL",
                            "details": threat_details
                        }))
                        await websocket.send_text(json.dumps({
                            "type": "log",
                            "message": f"[SECURITY ALERT] > Autonomous scan halted by Security Agent: {threat_details}"
                        }))
                        return

                    anomaly = final_state.get("anomaly_details", {})
                    blast_radius = final_state.get("blast_radius_analysis", {})
                    strategies = final_state.get("generated_strategies", [])
                    best = final_state.get("utility_evaluation", {})
                    
                    # Emit standardized Blast Radius Data event
                    if blast_radius:
                        await websocket.send_text(json.dumps({
                            "type": "blast_radius_data",
                            "data": blast_radius
                        }))


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
                user_role = payload.get("user_role", "operator").lower()
                scan_config = {"configurable": {"thread_id": f"scan-{thread_id}"}}
                
                # Retrieve current state snapshot to inspect pending action risk level
                state_snapshot = await asyncio.to_thread(_get_state, scan_config)
                final_state = state_snapshot.values if state_snapshot else {}
                eval_payload = final_state.get("utility_evaluation", {})
                
                high_risk = is_high_risk_action(eval_payload)
                
                if high_risk and user_role != "manager":
                    print(f" [RBAC Denied] Operator role attempted approval on high-risk action: {eval_payload.get('action')}")
                    await websocket.send_text(json.dumps({
                        "type": "unauthorized",
                        "message": "[RBAC DENIED] > Authorization rejected. High-risk database operations require Manager role clearance.",
                        "required_role": "manager",
                        "current_role": user_role
                    }))
                    await websocket.send_text(json.dumps({
                        "type": "log",
                        "message": f"[SECURITY WARNING] > Blocked approval attempt by role '{user_role.upper()}'. Manager role required."
                    }))
                else:
                    await websocket.send_text(json.dumps({"type": "log", "message": f"[AGENT] > Authorized by {user_role.upper()}. Resuming execution pipeline..."}))
                    await websocket.send_text(json.dumps({"type": "node_active", "node": "execution"}))
                    try:
                        # Resume the LangGraph agent past the interrupt point
                        result = await asyncio.to_thread(_invoke_graph, None, scan_config)
                        
                        await websocket.send_text(json.dumps({"type": "status", "status": "ONLINE"}))
                        await websocket.send_text(json.dumps({"type": "log", "message": "[SUCCESS] > Execution committed to database."}))
                    except Exception as e:
                        await websocket.send_text(json.dumps({"type": "status", "status": "ONLINE"}))
                        await websocket.send_text(json.dumps({"type": "log", "message": f"[ERROR] > Execution failed: {str(e)}"}))


            elif command == "get_history":
                try:
                    scan_config = {"configurable": {"thread_id": f"scan-{thread_id}"}}
                    def _fetch_history():
                        history = []
                        for snapshot in sage_app.get_state_history(scan_config):
                            ckpt_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
                            if ckpt_id:
                                next_nodes = list(snapshot.next) if snapshot.next else []
                                history.append({
                                    "checkpoint_id": ckpt_id,
                                    "next": next_nodes,
                                    "created_at": snapshot.metadata.get("created_at") if snapshot.metadata else None,
                                    "step": snapshot.metadata.get("step") if snapshot.metadata else None
                                })
                        return history

                    history_data = await asyncio.to_thread(_fetch_history)
                    await websocket.send_text(json.dumps({
                        "type": "checkpoint_history",
                        "history": history_data
                    }))
                except Exception as e:
                    print(f" Error fetching checkpoint history: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "log",
                        "message": f"[ERROR] > Failed to fetch checkpoint history: {str(e)}"
                    }))

            elif command == "rollback":
                target_checkpoint_id = payload.get("checkpoint_id")
                if not target_checkpoint_id:
                    await websocket.send_text(json.dumps({
                        "type": "log",
                        "message": "[ERROR] > No checkpoint_id provided for rollback."
                    }))
                else:
                    try:
                        scan_config = {"configurable": {"thread_id": f"scan-{thread_id}", "checkpoint_id": target_checkpoint_id}}
                        await websocket.send_text(json.dumps({
                            "type": "log",
                            "message": f"[SYSTEM] > Reverting graph state to checkpoint '{target_checkpoint_id[:8]}...'..."
                        }))

                        result = await asyncio.to_thread(_invoke_graph, None, scan_config)
                        
                        await websocket.send_text(json.dumps({
                            "type": "status",
                            "status": "ONLINE"
                        }))
                        await websocket.send_text(json.dumps({
                            "type": "log",
                            "message": f"[SUCCESS] > State successfully reverted to checkpoint {target_checkpoint_id[:8]}."
                        }))
                    except Exception as e:
                        print(f" Rollback error: {e}")
                        await websocket.send_text(json.dumps({
                            "type": "log",
                            "message": f"[ERROR] > Reversion to checkpoint failed: {str(e)}"
                        }))




    except WebSocketDisconnect:
        print("UI Disconnected from Cortex.")

# --- BOOT SEQUENCE ---
if __name__ == "__main__":
    print(" Firing up the SageCommand server...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
