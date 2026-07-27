# System Architecture Document

## Overview
SageCommand OS V2.0 bridges high-performance multi-agent AI orchestration with real-time industrial telemetry. The backend is powered by a stateful graph (LangGraph) running on FastAPI, communicating via WebSockets to a React/Next.js frontend.

## 1. Multi-Agent Topology (LangGraph)
The core intelligence runs as a directed cyclic graph consisting of specialized nodes:
- **Supervisor (`supervisor`):** The orchestrator. Determines whether to delegate to the strategy worker, web researcher, or evaluator based on the incoming state.
- **Discovery Agent (`discovery_agent`):** Connects to the active SQL database, scanning for anomalies or inventory thresholds.
- **Strategy Worker (`strategy_worker`):** Ingests anomaly details and generates a list of 2-3 potential resolution strategies with associated costs.
- **Web Researcher (`web_researcher`):** Uses Tavily API to gather external real-world context (e.g., global shipping delays, weather events).
- **Evaluator (`evaluator`):** Cross-references strategies against external context to select the most optimal path, formatting the final SQL execution query.
- **Security Agent (`security_agent`):** Runs heuristic checks for prompt injections or malicious requests, capable of halting execution and emitting a `CRITICAL_THREAT` event.
- **Vision Diagnostics (`vision_diagnostics_agent`):** Processes Base64 image payloads using Google Gemini 2.0 Flash to diagnose physical hardware damage.

## 2. Asynchronous Event Pipeline (WebSockets)
To prevent UI blocking during complex agent chains (which can take 5-15 seconds), the system utilizes a WebSocket nervous system (`ws/sage`). 
- As LangGraph executes in a background thread, it yields `stream_mode="updates"`.
- The FastAPI server intercepts these events and pushes lightweight JSON payloads (e.g., `{"type": "node_active", "node": "evaluator"}`) to the frontend.
- The React frontend dynamically updates the glowing edges in the `React Flow` map without polling.

## 3. Resilience and Failover Mechanism
The LLM inference engine (`safe_llm_invoke`) is wrapped in a try/catch block.
- **Primary:** Attempts inference via Groq (Llama-3.3-70b-versatile) for ultra-low latency reasoning.
- **Secondary:** If Groq rate-limits or times out, it seamlessly falls back to Google Gemini 2.0 Flash.
- **Demo Mode:** If no keys are present, the system defaults to a `DEMO_API_KEY` placeholder to prevent catastrophic crashing.

## 4. State Checkpointing & Time Travel
State is persisted to a local `sage_memory.sqlite` file using LangGraph's `SqliteSaver`. This provides true checkpointing, allowing the frontend to query historical thread histories and "Time Travel" to previous decision states.
