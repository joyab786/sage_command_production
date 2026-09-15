# backend/core/state.py
from enum import Enum
from typing import Dict, Any, List, Optional
from langgraph.graph import MessagesState


class IndustrialStage(str, Enum):
    OBSERVE = "OBSERVE"
    UNDERSTAND = "UNDERSTAND"
    DETECT = "DETECT"
    PREDICT = "PREDICT"
    ANALYZE = "ANALYZE"
    SIMULATE = "SIMULATE"
    OPTIMIZE = "OPTIMIZE"
    GOVERN = "GOVERN"
    GET_APPROVAL = "GET_APPROVAL"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    LEARN = "LEARN"


class SageOSState(MessagesState):
    """
    Unified SageCommand V3 Industrial Operations Agent State.
    Maintains full backward compatibility with V2 state while supporting 
    the 12-stage continuous operational loop.
    """
    # V2 Compatibility Fields
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

    # V3 Operational Lifecycle Extensions
    current_stage: Optional[IndustrialStage]
    proposed_action: Optional[Dict[str, Any]]
    verification_result: Optional[Dict[str, Any]]
    learn_entry: Optional[Dict[str, Any]]

    # V3 Session-Scoped Database Context Identifiers (Safe for Checkpointing)
    tenant_id: Optional[str]
    workspace_id: Optional[str]
    session_id: Optional[str]
    connection_id: Optional[str]
    access_mode: Optional[str]
    data_mode: Optional[str]
