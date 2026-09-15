# backend/api/websocket.py
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage

try:
    from core.config import SAGE_AUTH_ENABLED, IS_PRODUCTION, SAGE_MAX_REQUEST_SIZE, DEFAULT_DB_PATH
    from core.auth import get_auth_provider, Identity
    from governance.audit import log_security_event
    from governance.redaction import sanitize_log_message
    from graph.builder import sage_app
    from governance.rbac import is_high_risk_action
    from services.connection_manager import db_manager
except (ImportError, ModuleNotFoundError):
    from backend.core.config import SAGE_AUTH_ENABLED, IS_PRODUCTION, SAGE_MAX_REQUEST_SIZE, DEFAULT_DB_PATH
    from backend.core.auth import get_auth_provider, Identity
    from backend.governance.audit import log_security_event
    from backend.governance.redaction import sanitize_log_message
    from backend.graph.builder import sage_app
    from backend.governance.rbac import is_high_risk_action
    from backend.services.connection_manager import db_manager

router = APIRouter()

def _invoke_graph(input_state, config):
    """Runs sage_app.invoke() synchronously in a background thread."""
    return sage_app.invoke(input_state, config=config)

def _get_state(config):
    """Runs sage_app.get_state() synchronously in a background thread."""
    return sage_app.get_state(config)


@router.websocket("/ws/sage")
async def websocket_endpoint(websocket: WebSocket):
    # Handshake Auth Token Inspection
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization") or websocket.headers.get("sec-websocket-protocol")
        if auth_header and "Bearer " in auth_header:
            token = auth_header.split("Bearer ")[-1].strip()
        elif auth_header:
            token = auth_header.strip()

    provider = get_auth_provider()
    try:
        if token:
            identity = provider.authenticate_token(token)
        elif not SAGE_AUTH_ENABLED and not IS_PRODUCTION:
            identity = Identity(user_id="dev_ws_user", roles=["operator", "manager"])
        else:
            identity = provider.authenticate_token("")
    except Exception as auth_err:
        log_security_event("WEBSOCKET_AUTH_FAILURE", {
            "reason": str(auth_err),
            "client": str(websocket.client)
        }, severity="WARNING")
        # Reject connection with Policy Violation code
        await websocket.close(code=1008)
        return

    await websocket.accept()
    websocket.state.identity = identity
    
    # Initialize session database connection in DatabaseConnectionManager
    db_manager.create_connection(
        tenant_id=identity.tenant_id,
        workspace_id="workspace_default",
        session_id=identity.session_id,
        connection_string=f"sqlite:///{DEFAULT_DB_PATH}",
        connection_id="sqlite_main"
    )

    log_security_event("WEBSOCKET_CONNECT", {
        "user_id": identity.user_id,
        "roles": identity.roles,
        "client": str(websocket.client)
    })

    # Unique thread ID per session for LangGraph memory
    thread_id = id(websocket)
    config = {"configurable": {"thread_id": str(thread_id)}}
    
    try:
        while True:
            data = await websocket.receive_text()

            # Message Payload Size Limit Validation
            if len(data) > SAGE_MAX_REQUEST_SIZE:
                log_security_event("WEBSOCKET_PAYLOAD_TOO_LARGE", {
                    "user_id": identity.user_id,
                    "payload_size": len(data),
                    "max_allowed": SAGE_MAX_REQUEST_SIZE
                }, severity="WARNING")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Message payload exceeds maximum allowed size ({SAGE_MAX_REQUEST_SIZE} bytes)."
                }))
                continue

            payload = json.loads(data)
            command = payload.get("command")
            
            if command == "chat":
                user_input = payload.get("text")
                
                # Send a processing update to the UI
                await websocket.send_text(json.dumps({"type": "node_update", "node": "Strategic Copilot"}))
                await websocket.send_text(json.dumps({"type": "node_active", "node": "copilot_agent"}))
                
                # --- INVOKE THE LANGGRAPH AGENT IN A BACKGROUND THREAD ---
                try:
                    input_state = {
                        "messages": [HumanMessage(content=user_input)],
                        "tenant_id": identity.tenant_id,
                        "workspace_id": "workspace_default",
                        "session_id": identity.session_id,
                        "connection_id": "sqlite_main"
                    }
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
                    error_msg = f"Agent error: {sanitize_log_message(str(e))}"
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
                                "justification": best.get("justification", f"Vision finding: {vision_result.get('part_identified')} - {vision_result.get('damage_assessment')}"),
                                "proposed_action": final_state.get("proposed_action")
                            }
                        }))
                except Exception as e:
                    print(f" Vision diagnostics error: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "log",
                        "message": f"[ERROR] > Multi-modal hardware diagnostics failed: {sanitize_log_message(str(e))}"
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

                    # Evaluate policy for proposed action
                    prop_action_data = final_state.get("proposed_action")
                    policy_decision_data = None
                    if prop_action_data and isinstance(prop_action_data, dict):
                        try:
                            from services.policy_service import policy_service
                            from services.action_store import action_store
                            from data.schemas.policy_contract import PolicyEvaluationContext
                            
                            act_id = prop_action_data.get("action_id")
                            stored_act = action_store.get(act_id) if act_id else None
                            if stored_act:
                                pol_ctx = PolicyEvaluationContext(
                                    tenant_id=identity.tenant_id,
                                    workspace_id="workspace_default",
                                    session_id=identity.session_id,
                                    user_id=identity.user_id,
                                    plant_id=stored_act.target.plant_id,
                                    roles=identity.roles,
                                    data_mode=stored_act.data_mode
                                )
                                pol_dec = policy_service.evaluate(stored_act, pol_ctx, persist_decision=True)
                                policy_decision_data = pol_dec.model_dump()
                        except Exception as pol_err:
                            print(f"Policy evaluation notice in websocket: {pol_err}")

                    await websocket.send_text(json.dumps({
                        "type": "guardrail_interrupt",
                        "payload": {
                            "action": best.get("action", strategies[0]["action"] if strategies else "No action determined"),
                            "justification": best.get("justification", anomaly.get("details", "Anomaly detected during scan.")),
                            "proposed_action": final_state.get("proposed_action"),
                            "policy_decision": policy_decision_data
                        }
                    }))

                    if policy_decision_data:
                        await websocket.send_text(json.dumps({
                            "type": "policy_decision",
                            "decision": policy_decision_data
                        }))

                except Exception as e:
                    print(f" Scan pipeline error: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "guardrail_interrupt",
                        "payload": {
                            "action": "Manual Inspection Required",
                            "justification": f"Autonomous scan encountered an error: {sanitize_log_message(str(e))}"
                        }
                    }))
                
            elif command == "approve":
                user_role = payload.get("user_role", identity.roles[0] if identity.roles else "operator").lower()
                scan_config = {"configurable": {"thread_id": f"scan-{thread_id}"}}
                
                # Retrieve current state snapshot to inspect pending action risk level
                state_snapshot = await asyncio.to_thread(_get_state, scan_config)
                final_state = state_snapshot.values if state_snapshot else {}
                eval_payload = final_state.get("utility_evaluation", {})
                
                high_risk = is_high_risk_action(eval_payload)
                
                # RBAC Clearance Validation: Check identity roles and requested role for high-risk approval
                if high_risk and ("manager" not in identity.roles or user_role != "manager"):
                    log_security_event("WEBSOCKET_RBAC_DENIED", {
                        "user_id": identity.user_id,
                        "action": eval_payload.get("action"),
                        "roles": identity.roles
                    }, severity="WARNING")
                    print(f" [RBAC Denied] Identity '{identity.user_id}' with roles {identity.roles} attempted approval on high-risk action: {eval_payload.get('action')}")
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
                        await websocket.send_text(json.dumps({"type": "log", "message": f"[ERROR] > Execution failed: {sanitize_log_message(str(e))}"}))

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
                        "message": f"[ERROR] > Failed to fetch checkpoint history: {sanitize_log_message(str(e))}"
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
                            "message": f"[ERROR] > Reversion to checkpoint failed: {sanitize_log_message(str(e))}"
                        }))

    except WebSocketDisconnect:
        log_security_event("WEBSOCKET_DISCONNECT", {
            "user_id": identity.user_id,
            "client": str(websocket.client)
        })
        print(f"UI Disconnected from Cortex (User: {identity.user_id}).")

