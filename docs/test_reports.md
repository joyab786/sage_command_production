# System Test Reports

## Test Scope
Testing was conducted on the V2.0 architecture to ensure LangGraph state persistence, UI interactivity, and backend fallback resilience. Tests were executed via automated headless browser subagents and manual UI verification.

## 1. UI & Visual Component Verification
| Component | Status | Notes |
|:---|:---:|:---|
| **React Flow Graph** | PASS | Nodes render correctly; edges glow conditionally based on websocket `node_active` state. |
| **Blast Radius Metrics** | PASS | CSS pulse rings and cascading cards trigger dynamically upon anomaly detection. |
| **RBAC Toggle** | PASS | Framer Motion sliding highlight active. Manager/Operator states properly mutate React Context. |
| **Modals (Time Travel / Uplink)** | PASS | Spring-physics entry/exit functional. Backdrop blur persists. |

## 2. Agent Graph Logic & Checkpointing
| System | Status | Notes |
|:---|:---:|:---|
| **SQLite Memory Persistence** | PASS | `SqliteSaver` successfully writes threaded checkpoints. Re-running queries correctly fetches past state. |
| **LLM Failover** | PASS | Simulated a Groq rate-limit. `try/except` successfully initialized Gemini 2.0 Flash as the fallback. |
| **Guardrail HITL Intercept** | PASS | `interrupt_before=["execution"]` successfully halts graph. Approval payload correctly triggers `resume_execution`. |
| **DEFCON 1 Security Node** | PASS | Injected prompt payload caught by Security Agent; triggers UI red lock-down sequence and aborts run. |

## 3. API & Communication
| Test | Status | Notes |
|:---|:---:|:---|
| **WebSocket Connectivity** | PASS | Frontend successfully maintains persistent duplex connection. Heartbeat active. |
| **Dynamic Datacore Mount** | PASS | Uploading `.csv` successfully converts to `.sqlite` in the background and mounts via SQLAlchemy without crashing FastAPI. |

***
**Test Date:** July 2026
**Tester:** AI Systems Diagnostic Subagent
