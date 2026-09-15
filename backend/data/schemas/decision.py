# backend/data/schemas/decision.py
import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

try:
    from data.schemas.incident import IncidentState, ActionState
except ModuleNotFoundError:
    from backend.data.schemas.incident import IncidentState, ActionState


class DecisionObject(BaseModel):
    """
    SageCommand V3 Comprehensive Decision Object Contract.
    Captures complete context, evidence, proposed strategies, policy results, and audit trails.
    """
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique decision UUID")
    incident_id: Optional[str] = Field(default=None, description="Associated incident ID")
    mission_id: Optional[str] = Field(default=None, description="Associated mission ID")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="ISO-8601 creation timestamp")
    
    problem: str = Field(description="Problem statement / anomaly description")
    objective: str = Field(description="Resolution objective")
    constraints: List[str] = Field(default_factory=list, description="Operational constraints")
    
    evidence: List[Dict[str, Any]] = Field(default_factory=list, description="Telemetry & market evidence data")
    strategies: List[Dict[str, Any]] = Field(default_factory=list, description="Generated operational resolution strategies")
    selected_strategy: Optional[Dict[str, Any]] = Field(default=None, description="Optimal strategy selected by evaluator")
    
    confidence: float = Field(default=0.9, ge=0.0, le=1.0, description="Confidence score")
    uncertainty: float = Field(default=0.1, ge=0.0, le=1.0, description="Uncertainty score")
    
    risk: str = Field(default="MEDIUM", description="Assessed risk level")
    cost: float = Field(default=0.0, description="Estimated financial impact in USD")
    time: str = Field(default="Immediate", description="Estimated execution duration")
    sla_impact: str = Field(default="None", description="Impact on customer SLAs")
    financial_impact: str = Field(default="$0 USD", description="Projected exposure / savings")
    
    policy_result: Dict[str, Any] = Field(default_factory=dict, description="Policy Engine & SQL Guardrail validation result")
    approval_status: str = Field(default="PENDING", description="Human-in-the-loop approval status")
    execution_status: ActionState = Field(default=ActionState.PROPOSED, description="Current execution state")
    verification_status: str = Field(default="UNVERIFIED", description="Post-execution verification state")
    outcome: Optional[Dict[str, Any]] = Field(default=None, description="Final outcome report & learning feedback")
