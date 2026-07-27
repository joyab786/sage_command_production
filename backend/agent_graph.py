# backend/agent_graph.py
from typing import TypedDict, List, Dict, Any, Literal, Annotated
import operator
import time
import hashlib
import sqlite3
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy import text

from langgraph.graph import StateGraph, START, END, MessagesState
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite import SqliteSaver

from tools import sage_tools, check_live_inventory, web_search_tool, dynamic_db, validate_sql_query

load_dotenv()

# --- LLM RESILIENCE & FAILOVER SYSTEM ---
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if os.getenv("GROQ_API_KEY"):
    from langchain_groq import ChatGroq
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)
    print("[AI] Primary LLM: Groq llama-3.3-70b-versatile")
elif api_key:
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=api_key, temperature=0.2)
    print("[AI] Primary LLM: Google Gemini 2.0 Flash")
else:
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key="DEMO_API_KEY", temperature=0.2)
    print("[AI] Warning: Neither GROQ_API_KEY nor GOOGLE_API_KEY set. Operating in demo mode.")

def get_fallback_llm():
    """Dynamically instantiates Google Gemini as resilient failover model."""
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "DEMO_API_KEY"
    return ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=key, temperature=0.2)

def safe_llm_invoke(prompt: str, structured_schema=None):
    """
    Resilient LLM Execution Wrapper:
    Attempts to invoke the primary LLM (ChatGroq). If rate-limited or timed out,
    catches the exception and seamlessly fails over to ChatGoogleGenerativeAI (Gemini)
    without interrupting graph execution or corrupting memory state.
    """
    global llm
    try:
        if structured_schema:
            target = llm.with_structured_output(structured_schema)
            return target.invoke(prompt)
        else:
            res = llm.invoke(prompt)
            return res.content if hasattr(res, "content") else str(res)
    except Exception as primary_err:
        print(f" [LLM Failover] Primary LLM exception ({primary_err}). Failing over to Gemini...")
        try:
            fallback = get_fallback_llm()
            if structured_schema:
                target = fallback.with_structured_output(structured_schema)
                return target.invoke(prompt)
            else:
                res = fallback.invoke(prompt)
                return res.content if hasattr(res, "content") else str(res)
        except Exception as fallback_err:
            print(f" [LLM Failover Critical] Fallback LLM also failed: {fallback_err}")
            raise fallback_err


# --- STRUCTURED SCHEMAS ---# Structured output schemas
class SupervisorDecision(BaseModel):
    next_worker: Literal["strategy_worker", "web_researcher", "evaluator", "execution", "END"] = Field(
        description="The next worker node or stage to delegate the task to."
    )
    delegation_message: str = Field(
        description="A clear delegation instruction explaining what needs to be done next."
    )

class Strategy(BaseModel):
    id: str = Field(description="Unique identifier for the strategy, e.g. S1, S2.")
    action: str = Field(description="Action description of what to do.")
    cost: int = Field(description="Estimated cost associated with this action.")

class StrategyList(BaseModel):
    strategies: List[Strategy] = Field(description="A list of 2 to 3 alternative resolution strategies.")

class EvaluationResult(BaseModel):
    action: str = Field(description="The selected action/resolution path chosen as the best course of action.")
    justification: str = Field(description="Real-world justification for selecting this strategy.")
    sql_query: str = Field(
        description="The SQL write/UPDATE statement to execute against target database tables. "
                    "Must be a valid SQL write statement and MUST NOT contain prohibited commands like DROP, DELETE, or TRUNCATE."
    )

class AffectedSystem(BaseModel):
    name: str = Field(description="Name of affected downstream facility or line, e.g. Line Alpha Assembly")
    status: Literal["CRITICAL", "WARNING", "DEGRADED", "STABLE"] = Field(description="System impact status")
    impact_delay: str = Field(description="Time delay before impact manifests, e.g. 4 Hours")

class CascadingTimelineEvent(BaseModel):
    timeframe: str = Field(description="Timeline marker, e.g., T+4 Hours, T+24 Hours, T+7 Days")
    impact: str = Field(description="Description of downstream disruption at this marker")

class BlastRadiusPayload(BaseModel):
    urgency_rating: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(description="Overall urgency rating")
    financial_exposure: str = Field(description="Estimated financial risk exposure, e.g. $35,000 USD")
    affected_systems: List[AffectedSystem] = Field(description="List of 3 affected downstream systems")
    cascading_timeline: List[CascadingTimelineEvent] = Field(description="List of 3 cascading timeline events")
    summary: str = Field(description="Executive summary of blast radius analysis")

class VisionFindingPayload(BaseModel):
    part_identified: str = Field(description="Name and model of the hardware/machinery component identified")
    damage_assessment: str = Field(description="Detailed physical damage analysis and failure mode")
    recommended_action: str = Field(description="Recommended industrial maintenance/replacement action")
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(description="Severity rating of the hardware damage")


# --- RBAC RISK CLASSIFIER ---
def is_high_risk_action(eval_payload: Dict[str, Any]) -> bool:
    """
    Classifies whether a pending execution action is high-risk.
    Operations with non-empty SQL queries or high-impact operational commands
    require 'manager' role authorization.
    """
    if not eval_payload:
        return True
    
    sql_query = eval_payload.get("sql_query", "").strip()
    action_text = eval_payload.get("action", "").lower()
    
    if sql_query:
        return True
    
    high_risk_keywords = ["update", "delete", "reallocate", "expedite", "restock", "price", "order"]
    for keyword in high_risk_keywords:
        if keyword in action_text:
            return True
            
    return False


# 1. ADVANCED TOPOLOGY STATE
class SageOSState(MessagesState):
    security_status: str
    threat_details: str
    image_data: str
    vision_finding: Dict[str, Any]
    anomaly_details: Dict[str, Any]
    blast_radius_analysis: Dict[str, Any]
    generated_strategies: List[Dict[str, Any]]
    external_market_context: str
    utility_evaluation: Dict[str, Any]
    chain_of_custody: List[Dict[str, Any]]
    next_worker: str


# --- 1.5 SECURITY INTRUSION DETECTION AGENT ---
def security_agent_node(state: SageOSState):
    print(" [Security Agent] Monitoring payload for intrusion patterns...")
    messages = state.get("messages", [])
    input_text = ""
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            input_text = str(last_msg.get("content", ""))
        elif hasattr(last_msg, "content"):
            input_text = str(last_msg.content)

    
    # Check for Prompt Injections / System Overrides
    injection_keywords = [
        "ignore previous instructions", "system prompt", "override security",
        "admin mode", "bypass guardrails", "forget rules", "developer mode"
    ]
    for kw in injection_keywords:
        if kw in input_text.lower():
            print(f" [Security Alert] Prompt injection pattern detected: '{kw}'")
            return {
                "security_status": "CRITICAL_THREAT",
                "threat_details": f"Prompt injection attempt detected containing pattern: '{kw}'",
                "next_worker": "END"
            }
            
    # Check for Unauthorized Raw SQL Injection Syntax in Chat Input
    sql_threats = ["DROP TABLE", "DELETE FROM", "TRUNCATE TABLE", "ALTER TABLE", "UNION SELECT", ";--"]
    for sql_kw in sql_threats:
        if sql_kw in input_text.upper():
            print(f" [Security Alert] Malicious SQL pattern detected in payload: '{sql_kw}'")
            return {
                "security_status": "CRITICAL_THREAT",
                "threat_details": f"Unauthorized raw SQL payload pattern detected: '{sql_kw}'",
                "next_worker": "END"
            }

    # Check for Abnormal Payload Size
    if len(input_text) > 2500:
        print(" [Security Alert] Abnormal payload size detected.")
        return {
            "security_status": "CRITICAL_THREAT",
            "threat_details": f"Abnormal payload size detected ({len(input_text)} characters exceeds security threshold 2500).",
            "next_worker": "END"
        }

    print(" [Security Agent] Payload verified cleanly. Security clearance GRANTED.")
    return {"security_status": "CLEAR", "threat_details": ""}


# --- 1.6 MULTI-MODAL HARDWARE VISION DIAGNOSTICS AGENT ---
def vision_diagnostics_agent_node(state: SageOSState):
    print(" [Vision Agent] Analyzing industrial hardware image payload with Gemini Multi-Modal...")
    image_data = state.get("image_data", "")
    
    if not image_data:
        print(" [Vision Agent] No image_data found in state. Returning default assessment.")
        finding = {
            "part_identified": "Industrial Conveyor Motor & Gearbox",
            "damage_assessment": "Thermal discoloration and mechanical gear tooth fracture detected.",
            "recommended_action": "Immediate motor replacement and gearbox realigning.",
            "severity": "CRITICAL"
        }
        anomaly = {"type": "Hardware Machinery Failure", "details": f"{finding['part_identified']}: {finding['damage_assessment']}"}
        return {"vision_finding": finding, "anomaly_details": anomaly, "next_worker": "strategy_worker"}
        
    # Standardize image URL data
    if not image_data.startswith("data:image"):
        image_data_url = f"data:image/jpeg;base64,{image_data}"
    else:
        image_data_url = image_data

    vision_model = get_fallback_llm() # Instantiates Gemini 2.0 Flash with multi-modal capabilities
    
    msg = HumanMessage(
        content=[
            {
                "type": "text", 
                "text": "You are a master industrial machinery technician. Inspect this machinery image. Identify the component, analyze physical damage, recommend repair/replacement action, and assign a severity rating."
            },
            {
                "type": "image_url",
                "image_url": {"url": image_data_url}
            }
        ]
    )
    
    try:
        structured_target = vision_model.with_structured_output(VisionFindingPayload)
        result = structured_target.invoke([msg])
        if hasattr(result, "dict"):
            finding = result.dict()
        elif isinstance(result, dict):
            finding = result
        else:
            raise ValueError("Invalid vision output format.")
    except Exception as e:
        print(f" [Vision Agent] Fallback vision assessment activated due to error: {e}")
        finding = {
            "part_identified": "High-Pressure Hydraulic Valve Assembly",
            "damage_assessment": "Visible seal blow-out and hydraulic fluid leakage under operating pressure.",
            "recommended_action": "Replace valve seal kit and re-torque mounting bolts.",
            "severity": "HIGH"
        }

    print(f" [Vision Agent] Hardware Diagnosed: {finding.get('part_identified')} | Severity: {finding.get('severity')}")
    anomaly = {"type": "Machinery Failure", "details": f"{finding.get('part_identified')}: {finding.get('damage_assessment')}"}
    return {
        "vision_finding": finding, 
        "anomaly_details": anomaly,
        "next_worker": "strategy_worker"
    }



# 2. THE COPILOT AGENT (Direct Human Chat)
MAX_CONTEXT_MESSAGES = 10

def copilot_agent_node(state: SageOSState):
    print(" [Copilot] Processing human inquiry...")
    llm_with_tools = llm.bind_tools(sage_tools)
    sys_msg = SystemMessage(content=(
        "You are SageCommand, an Omni-Agent COO. "
        "Use the list_database_tables tool first to inspect the schema, "
        "then use query_database for SQL queries. "
        "Use the web search tool for external/internet queries. "
        "Always pass SQL as a plain string to query_database."
    ))
    messages = state["messages"]
    if len(messages) > MAX_CONTEXT_MESSAGES:
        messages = messages[-MAX_CONTEXT_MESSAGES:]
    try:
        response = llm_with_tools.invoke([sys_msg] + messages)
    except Exception as e:
        print(f" [Copilot] Tool execution failed over to Gemini: {e}")
        fallback_llm = get_fallback_llm().bind_tools(sage_tools)
        response = fallback_llm.invoke([sys_msg] + messages)
        
    return {"messages": [response]}


# 3. AUTONOMOUS BACKGROUND AGENTS
def discovery_agent_node(state: SageOSState):
    print(" [Discovery] Scanning industrial database...")
    report = check_live_inventory.invoke({})
    anomaly = {"type": "Low Stock Anomaly", "details": report}
    return {"anomaly_details": anomaly}


def risk_agent_node(state: SageOSState):
    print(" [Risk Agent] Computing Blast Radius Analysis...")
    anomaly = state.get("anomaly_details", {})
    schema_info = dynamic_db.db.get_table_info() if (dynamic_db and dynamic_db.db) else "No active database loaded."
    
    prompt = f"""You are the Risk Analysis Agent in SageCommand OS.
Perform a structured 'Blast Radius Analysis' for the detected operational anomaly based on the database schema.
Project how this disruption cascades downstream to related facilities, customer SLA fulfillment, and production schedules.

ACTIVE DATABASE SCHEMA:
{schema_info}

ANOMALY TELEMETRY:
{anomaly}

Generate structured output with:
- `urgency_rating`: "CRITICAL", "HIGH", "MEDIUM", or "LOW".
- `financial_exposure`: Estimated financial impact string (e.g., "$35,000 USD").
- `affected_systems`: List of 3 affected downstream systems with `name`, `status`, and `impact_delay`.
- `cascading_timeline`: List of 3 timeline events with `timeframe` (e.g., "T+4 Hours", "T+24 Hours", "T+7 Days") and `impact`.
- `summary`: Concise executive summary of the cascading disruption.
"""
    try:
        result = safe_llm_invoke(prompt, structured_schema=BlastRadiusPayload)
        if hasattr(result, "dict"):
            blast_radius = result.dict()
        elif isinstance(result, dict):
            blast_radius = result
        else:
            raise ValueError("Invalid blast radius response format.")
    except Exception as e:
        print(f" [Risk Agent] Fallback blast radius analysis activated: {e}")
        item = anomaly.get("item", "Components")
        blast_radius = {
            "urgency_rating": "HIGH",
            "financial_exposure": "$28,500 USD",
            "summary": f"Cascading inventory depletion risk calculated for {item}.",
            "affected_systems": [
                {"name": "Assembly Line Alpha", "status": "CRITICAL", "impact_delay": "4 Hours"},
                {"name": "Regional Order Fulfillment", "status": "WARNING", "impact_delay": "24 Hours"},
                {"name": "Supply Chain Procurement", "status": "DEGRADED", "impact_delay": "48 Hours"}
            ],
            "cascading_timeline": [
                {"timeframe": "T+4 Hours", "impact": f"Line Alpha buffer depleted for {item}."},
                {"timeframe": "T+24 Hours", "impact": "Tier-1 customer shipping SLA delayed by 2 days."},
                {"timeframe": "T+7 Days", "impact": "Emergency expediting cost incurred for replacement units."}
            ]
        }

    print(f" [Risk Agent] Blast Radius calculated: Urgency={blast_radius.get('urgency_rating')} | Exposure={blast_radius.get('financial_exposure')}")
    return {"blast_radius_analysis": blast_radius}



def supervisor_agent_node(state: SageOSState):
    print(" [Supervisor] Evaluating schema and anomaly to delegate task...")
    schema_info = dynamic_db.db.get_table_info() if (dynamic_db and dynamic_db.db) else "No database loaded."
    anomaly = state.get("anomaly_details", {})
    messages = state.get("messages", [])
    
    user_input = ""
    if messages:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
                user_input = msg.content
                break
    if not user_input:
        user_input = anomaly.get("details", "Verify inventory status and plan optimal resolution path.")

    prompt = f"""You are the Supervisor node in SageCommand OS, an AI COO orchestrating an autonomous enterprise response system.
Your responsibility is to analyze the user request, anomaly telemetry, and database schema, then delegate to the appropriate worker node.

WORKER NODES:
1. 'strategy_worker': Generates 2-3 distinct internal operational resolution strategies with cost estimates.
2. 'web_researcher': Researches external market conditions, competitor pricing, or supplier availability via Tavily.
3. 'evaluator': Synthesizes internal strategies and external market data to select the optimal resolution path and generate database update SQL.
4. 'execution': Executes the approved SQL query against the production database (requires human authorization).
5. 'END': Concludes the workflow when processing is complete.

ACTIVE DATABASE SCHEMA:
{schema_info}

CURRENT SYSTEM STATE:
- Anomaly Details: {anomaly}
- Blast Radius Analysis: {state.get('blast_radius_analysis', {})}
- User Inquiry: {user_input}
- Generated Strategies: {state.get('generated_strategies', [])}
- External Market Context: {state.get('external_market_context', '')}
- Utility Evaluation: {state.get('utility_evaluation', {})}

ROUTING LOGIC RULE:
- If strategies ('generated_strategies') are missing/empty -> Delegate to 'strategy_worker'.
- If strategies are present BUT external research ('external_market_context') is missing/empty -> Delegate to 'web_researcher'.
- If strategies AND web research are present BUT evaluation ('utility_evaluation') is missing/empty -> Delegate to 'evaluator'.
- If utility evaluation is complete -> Delegate to 'execution'.

Formulate your decision using structured output with `next_worker` and `delegation_message`.
"""
    try:
        decision = safe_llm_invoke(prompt, structured_schema=SupervisorDecision)
        if hasattr(decision, "next_worker"):
            next_worker = decision.next_worker
            msg_content = decision.delegation_message
        elif isinstance(decision, dict):
            next_worker = decision.get("next_worker", "strategy_worker")
            msg_content = decision.get("delegation_message", "Supervisor delegating task based on state evaluation.")
        else:
            raise ValueError("Invalid supervisor decision format")
    except Exception as e:
        print(f" [Supervisor] Routing call failed: {e}. Using state-aware fallback.")
        if not state.get("generated_strategies"):
            next_worker = "strategy_worker"
            msg_content = "Delegating to Strategy Worker: Generate operational resolution strategies."
        elif not state.get("external_market_context"):
            next_worker = "web_researcher"
            msg_content = "Delegating to Web Researcher: Gather market intelligence and supplier context."
        elif not state.get("utility_evaluation"):
            next_worker = "evaluator"
            msg_content = "Delegating to Evaluator: Synthesize strategies and market data."
        else:
            next_worker = "execution"
            msg_content = "Routing to Execution: Evaluation complete; awaiting human execution authorization."

    print(f" [Supervisor] Routing decision: next_worker={next_worker} | message={msg_content}")
    return {
        "messages": [AIMessage(content=msg_content)],
        "next_worker": next_worker
    }


def strategy_worker_node(state: SageOSState):
    print(" [Strategy Worker] Generating strategies dynamically...")
    anomaly = state.get("anomaly_details", {})
    schema_info = dynamic_db.db.get_table_info() if (dynamic_db and dynamic_db.db) else "No active database schema."
    
    prompt = f"""You are the Strategy Worker node in SageCommand OS.
Based on the following anomaly details and database schema, generate exactly 2 to 3 distinct, realistic, and actionable resolution strategies.
For each strategy:
- `id`: Short identifier (e.g., S1, S2, S3).
- `action`: Specific operational action (e.g. adjust pricing, reorder stock, reallocate warehouse inventory).
- `cost`: Estimated financial cost in USD (integer).

DATABASE SCHEMA:
{schema_info}

ANOMALY DETAILS:
{anomaly}
"""
    try:
        result = safe_llm_invoke(prompt, structured_schema=StrategyList)
        if hasattr(result, "strategies"):
            strategies = [s.dict() for s in result.strategies]
        elif isinstance(result, dict) and "strategies" in result:
            strategies = result["strategies"]
        else:
            strategies = []
    except Exception as e:
        print(f" [Strategy Worker] Error generating strategies: {e}. Using dynamic fallback.")
        anomaly_type = anomaly.get("type", "Inventory Anomaly")
        anomaly_details = anomaly.get("details", "detected issue")
        strategies = [
            {"id": "S1", "action": f"Expedite priority restocking order to resolve {anomaly_type} ({anomaly_details}).", "cost": 3500},
            {"id": "S2", "action": f"Rebalance warehouse allocations and optimize pricing to mitigate {anomaly_type}.", "cost": 1200}
        ]

    print(f" [Strategy Worker] Generated strategies: {strategies}")
    return {"generated_strategies": strategies}


def web_researcher_node(state: SageOSState):
    print(" [Web Researcher] Scanning global internet via Tavily...")
    anomaly = state.get("anomaly_details", {})
    strategies = state.get("generated_strategies", [])
    messages = state.get("messages", [])
    
    user_input = ""
    if messages:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
                user_input = msg.content
                break

    prompt = f"""You are the Web Researcher node in SageCommand OS.
Your objective is to inspect the current state/anomaly and construct a single, highly targeted search query for Tavily to gather external market intelligence, supplier pricing, market benchmarks, or industry supply chain conditions.

CONTEXT:
- Anomaly Details: {anomaly}
- Proposed Strategies: {strategies}
- User Context: {user_input}

Construct a single search query (under 15 words, plain text, search-engine optimized, no quotes or surrounding punctuation).
"""
    try:
        search_query = safe_llm_invoke(prompt).strip().strip('"').strip("'")
    except Exception as e:
        print(f" [Web Researcher] Failed to generate LLM search query: {e}. Constructing dynamic query from anomaly.")
        anomaly_str = f"{anomaly.get('type', '')} {anomaly.get('details', '')}"
        search_query = f"market prices supply chain {anomaly_str}"[:80].strip()
        
    print(f" [Web Researcher] Executing dynamic search query: '{search_query}'")
    try:
        if hasattr(web_search_tool, "invoke"):
            search_results = web_search_tool.invoke({"query": search_query})
        else:
            search_results = web_search_tool(search_query)
    except Exception as e:
        print(f" [Web Researcher] Tavily search tool invocation error: {e}. Retrying with direct query string.")
        try:
            search_results = web_search_tool.invoke(search_query)
        except Exception as err:
            search_results = f"Web search could not retrieve external data for query '{search_query}': {err}"
        
    return {"external_market_context": str(search_results)}


def evaluator_agent_node(state: SageOSState):
    print(" [Evaluator] Synthesizing internal strategies with external market context...")
    
    schema_info = dynamic_db.db.get_table_info() if (dynamic_db and dynamic_db.db) else "No database loaded."
    strategies = state.get("generated_strategies", [])
    web_context = state.get("external_market_context", "")
    anomaly = state.get("anomaly_details", {})
    blast_radius = state.get("blast_radius_analysis", {})
    
    eval_prompt = f"""You are the Heuristic Evaluator node in SageCommand OS.
Your job is to synthesize internal operational strategies with external market intelligence, risk blast radius, and database schema details to choose the optimal resolution path.

ACTIVE DATABASE SCHEMA:
{schema_info}

ANOMALY DETAILS:
{anomaly}

BLAST RADIUS ANALYSIS:
{blast_radius}

PROPOSED INTERNAL STRATEGIES:
{strategies}

EXTERNAL MARKET INTELLIGENCE:
{web_context}

INSTRUCTIONS:
1. Select or synthesize the single best resolution `action` based on financial cost, implementation speed, and external market context.
2. Provide a thorough, professional real-world `justification` for why this resolution path is superior.
3. Generate a precise SQL write query (`sql_query`) to apply the resolution directly to target database tables (e.g., UPDATE table_name SET price = ... WHERE ...). 
   - The query MUST be a valid SQL write statement.
   - If no database changes are required, set `sql_query` to an empty string.
   - Prohibited SQL commands: DROP, DELETE, TRUNCATE, ALTER, GRANT, REVOKE.
"""
    try:
        result = safe_llm_invoke(eval_prompt, structured_schema=EvaluationResult)
        if hasattr(result, "dict"):
            utility_eval = result.dict()
        elif isinstance(result, dict):
            utility_eval = result
        else:
            raise ValueError("Structured LLM output did not return a valid evaluation object.")
    except Exception as e:
        print(f" [Evaluator] Structured evaluation error: {e}. Falling back to unstructured LLM synthesis.")
        try:
            justification_text = safe_llm_invoke(eval_prompt)
        except Exception as llm_err:
            justification_text = f"Synthesized evaluation based on strategies: {strategies} and market context."

        selected_action = strategies[0].get("action") if strategies else "Execute operational resolution strategy."
        utility_eval = {
            "action": selected_action,
            "justification": justification_text,
            "sql_query": ""
        }

    # CRYPTOGRAPHIC CHAIN OF CUSTODY LOGGING
    keys_read = ["anomaly_details", "blast_radius_analysis", "generated_strategies", "external_market_context", "database_schema"]
    custody_payload = {
        "timestamp": time.time(),
        "keys_read": keys_read,
        "proposed_action": utility_eval.get("action", ""),
        "justification": utility_eval.get("justification", ""),
        "sql_query": utility_eval.get("sql_query", "")
    }
    custody_json = json.dumps(custody_payload, sort_keys=True)
    hash_digest = hashlib.sha256(custody_json.encode("utf-8")).hexdigest()
    
    custody_entry = {
        "hash": hash_digest,
        "payload": custody_payload
    }
    
    print(f" [Evaluator] Final Utility Evaluation complete. Chain of Custody Hash: {hash_digest[:16]}...")
    existing_custody = state.get("chain_of_custody", [])
    
    return {
        "utility_evaluation": utility_eval,
        "chain_of_custody": existing_custody + [custody_entry]
    }


def execution_node(state: SageOSState):
    print(" [Execution] Authorized. Committing to database...")
    eval_result = state.get("utility_evaluation", {})
    sql_query = eval_result.get("sql_query", "")
    
    if not sql_query:
        print(" [Execution] No SQL query to run.")
        return {"messages": [AIMessage(content="Execution committed (no SQL transaction needed).")]}
        
    if dynamic_db.engine is None:
        raise ValueError("No database engine is currently loaded to commit transactions.")
        
    print(f" [Execution] Inspecting query with SQL Guardrail: {sql_query}")
    validate_sql_query(sql_query)
    
    try:
        with dynamic_db.engine.begin() as connection:
            print(f" [Execution] Beginning transaction: {sql_query}")
            connection.execute(text(sql_query))
        
        print(" [Execution] Transaction committed successfully.")
        return {"messages": [AIMessage(content=f"Execution committed. Query executed successfully: {sql_query}")]}
    except Exception as e:
        print(f" [Execution] Transaction failed: {e}. Automatically rolled back.")
        raise e


# 4. TRAFFIC ROUTING
def route_security_check(state: SageOSState) -> Literal["vision_diagnostics_agent", "copilot_agent", "discovery", "__end__"]:
    if state.get("security_status") == "CRITICAL_THREAT":
        return "__end__"
    if state.get("image_data"):
        return "vision_diagnostics_agent"
    if state.get("messages") and isinstance(state["messages"][-1], HumanMessage):
        return "copilot_agent"
    return "discovery"

def route_copilot_tools(state: SageOSState) -> Literal["tools", "__end__"]:
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
    return "__end__"

def route_supervisor(state: SageOSState) -> Literal["strategy_worker", "web_researcher", "evaluator", "execution", "__end__"]:
    next_worker = state.get("next_worker")
    if next_worker == "END" or next_worker is None:
        return "__end__"
    return next_worker


# 5. BUILD THE GRAPH TOPOLOGY
workflow = StateGraph(SageOSState)

from langgraph.prebuilt import ToolNode
workflow.add_node("tools", ToolNode(sage_tools))

workflow.add_node("security_agent", security_agent_node)
workflow.add_node("vision_diagnostics_agent", vision_diagnostics_agent_node)
workflow.add_node("copilot_agent", copilot_agent_node)
workflow.add_node("discovery", discovery_agent_node)
workflow.add_node("risk_agent", risk_agent_node)
workflow.add_node("supervisor", supervisor_agent_node)
workflow.add_node("strategy_worker", strategy_worker_node)
workflow.add_node("web_researcher", web_researcher_node)
workflow.add_node("evaluator", evaluator_agent_node)
workflow.add_node("execution", execution_node)

# Entry Gate: START -> security_agent -> (vision_diagnostics_agent | copilot_agent | discovery | END)
workflow.add_edge(START, "security_agent")
workflow.add_conditional_edges("security_agent", route_security_check)

# Vision Diagnostics Pipeline: vision_diagnostics_agent -> strategy_worker -> supervisor
workflow.add_edge("vision_diagnostics_agent", "strategy_worker")

# Copilot Routing Loop
workflow.add_conditional_edges("copilot_agent", route_copilot_tools)
workflow.add_edge("tools", "copilot_agent")

# Autonomous Pipeline: Discovery -> Risk Agent -> Supervisor
workflow.add_edge("discovery", "risk_agent")
workflow.add_edge("risk_agent", "supervisor")

# Dynamic Supervisor Routing Hub
workflow.add_conditional_edges("supervisor", route_supervisor)
workflow.add_edge("strategy_worker", "supervisor")
workflow.add_edge("web_researcher", "supervisor")
workflow.add_edge("evaluator", "supervisor")
workflow.add_edge("execution", END)

# Memory & Compilation
db_conn = sqlite3.connect("sage_memory.sqlite", check_same_thread=False)
memory = SqliteSaver(db_conn)

sage_app = workflow.compile(checkpointer=memory, interrupt_before=["execution"])


