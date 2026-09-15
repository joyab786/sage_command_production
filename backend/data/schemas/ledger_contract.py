# backend/data/schemas/ledger_contract.py
"""
SageCommand V3 — Audit & Decision Ledger Canonical Domain Schemas
Defines core models, event taxonomy, actor classifications, provenance metadata,
and tamper-evident decision records for historical operational auditability.

Invariants:
- The ledger is append-only and observational; it does not execute or mutate physical systems.
- Authentication != Authorization != Policy != Approval != Execution != Ledger
- Server-authoritative context only; untrusted clients cannot forge audit events.
"""

import hashlib
import json
import time
import uuid
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, validator


class ActorType(str, Enum):
    """Categorization of an entity acting within SageCommand."""
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    SCHEDULER = "SCHEDULER"
    SIMULATOR = "SIMULATOR"
    INTEGRATION = "INTEGRATION"
    ADMIN = "ADMIN"
    UNKNOWN = "UNKNOWN"


class EventCategory(str, Enum):
    """Broad domain classification of ledger events."""
    SECURITY = "SECURITY"
    DATA = "DATA"
    INTELLIGENCE = "INTELLIGENCE"
    ACTION = "ACTION"
    POLICY = "POLICY"
    AUTHORIZATION = "AUTHORIZATION"
    APPROVAL = "APPROVAL"
    SIMULATION = "SIMULATION"
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"
    INCIDENT = "INCIDENT"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    TRANSACTION = "TRANSACTION"


class EventStatus(str, Enum):
    """Status or outcome of the logged event."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class DataMode(str, Enum):
    """Operational data provenance mode."""
    REAL = "REAL"
    SIMULATION = "SIMULATION"
    HYBRID = "HYBRID"


class EvidenceProvenance(str, Enum):
    """Origin and trustworthiness classification of decision evidence."""
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    GENERATED = "GENERATED"
    USER_PROVIDED = "USER_PROVIDED"
    SIMULATED = "SIMULATED"


class EventType(str, Enum):
    """Authoritative event taxonomy for SageCommand V3."""
    # Authentication Events
    AUTHENTICATION_SUCCEEDED = "AUTHENTICATION_SUCCEEDED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    LOGOUT = "LOGOUT"

    # Authorization Events
    AUTHORIZATION_REQUESTED = "AUTHORIZATION_REQUESTED"
    AUTHORIZATION_ALLOWED = "AUTHORIZATION_ALLOWED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    AUTHORIZATION_SCOPE_DENIED = "AUTHORIZATION_SCOPE_DENIED"

    # Database & Gateway Events
    DATABASE_CONNECTION_REQUESTED = "DATABASE_CONNECTION_REQUESTED"
    DATABASE_CONNECTION_ESTABLISHED = "DATABASE_CONNECTION_ESTABLISHED"
    DATABASE_CONNECTION_FAILED = "DATABASE_CONNECTION_FAILED"
    DATABASE_CONNECTION_DISCONNECTED = "DATABASE_CONNECTION_DISCONNECTED"
    DATABASE_CONNECTION_REVOKED = "DATABASE_CONNECTION_REVOKED"
    DATABASE_HEALTH_CHANGED = "DATABASE_HEALTH_CHANGED"
    DATABASE_QUERY_EXECUTED = "DATABASE_QUERY_EXECUTED"

    # Structured Action Events
    ACTION_PROPOSED = "ACTION_PROPOSED"
    ACTION_VALIDATION_STARTED = "ACTION_VALIDATION_STARTED"
    ACTION_VALIDATED = "ACTION_VALIDATED"
    ACTION_VALIDATION_FAILED = "ACTION_VALIDATION_FAILED"
    ACTION_SIMULATION_REQUESTED = "ACTION_SIMULATION_REQUESTED"
    ACTION_SIMULATION_COMPLETED = "ACTION_SIMULATION_COMPLETED"
    ACTION_CANCELLED = "ACTION_CANCELLED"

    # Policy Enforcement Events
    POLICY_EVALUATION_STARTED = "POLICY_EVALUATION_STARTED"
    POLICY_EVALUATION_COMPLETED = "POLICY_EVALUATION_COMPLETED"
    POLICY_ALLOWED = "POLICY_ALLOWED"
    POLICY_DENIED = "POLICY_DENIED"
    POLICY_HOLD = "POLICY_HOLD"
    POLICY_APPROVAL_REQUIRED = "POLICY_APPROVAL_REQUIRED"
    POLICY_CONFLICT_DETECTED = "POLICY_CONFLICT_DETECTED"

    # Transaction & Rollback Architecture Events (Prompt 09)
    TRANSACTION_PLANNED = "TRANSACTION_PLANNED"
    TRANSACTION_VALIDATION_STARTED = "TRANSACTION_VALIDATION_STARTED"
    TRANSACTION_VALIDATED = "TRANSACTION_VALIDATED"
    TRANSACTION_INVALID = "TRANSACTION_INVALID"
    TRANSACTION_EXPIRED = "TRANSACTION_EXPIRED"
    TRANSACTION_CANCELLED = "TRANSACTION_CANCELLED"
    TRANSACTION_CONFLICT_DETECTED = "TRANSACTION_CONFLICT_DETECTED"
    ROLLBACK_PLAN_CREATED = "ROLLBACK_PLAN_CREATED"
    ROLLBACK_CAPABILITY_CHECKED = "ROLLBACK_CAPABILITY_CHECKED"

    # Human Governance Events (Future-Ready / Deferred)
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"

    # AI Agent Events
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_TOOL_CALLED = "AGENT_TOOL_CALLED"
    AGENT_TOOL_REJECTED = "AGENT_TOOL_REJECTED"

    # Simulation & Anomaly Events
    SIMULATION_STARTED = "SIMULATION_STARTED"
    SIMULATION_COMPLETED = "SIMULATION_COMPLETED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    SIMULATION_ANOMALY_TRIGGERED = "SIMULATION_ANOMALY_TRIGGERED"

    # Incident Management Events (Future-Ready)
    INCIDENT_DETECTED = "INCIDENT_DETECTED"
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_UPDATED = "INCIDENT_UPDATED"
    INCIDENT_RESOLVED = "INCIDENT_RESOLVED"

    # Future Execution Boundary Events (Deferred - No physical actions executed in Prompt 08)
    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_ROLLED_BACK = "EXECUTION_ROLLED_BACK"

    # Audit Administration & Self-Audit
    AUDIT_LOG_ACCESSED = "AUDIT_LOG_ACCESSED"
    AUDIT_QUERY_EXECUTED = "AUDIT_QUERY_EXECUTED"
    AUDIT_EXPORT_REQUESTED = "AUDIT_EXPORT_REQUESTED"


class LedgerActor(BaseModel):
    """Identifies the initiator or executor of an event."""
    actor_type: ActorType = Field(default=ActorType.USER, description="Type of actor: USER, AGENT, SYSTEM, etc.")
    actor_id: str = Field(..., description="Unique identifier of the actor (e.g. user_id or agent_id)")
    acting_user_id: Optional[str] = Field(default=None, description="Authenticated human user when an agent acts on their behalf")
    roles: List[str] = Field(default_factory=list, description="Roles held by the actor during event execution")


class ModelProvenance(BaseModel):
    """Metadata describing AI models and prompt versions involved in reasoning."""
    model_provider: Optional[str] = Field(default=None, description="e.g. Groq, Google, Anthropic")
    model_name: Optional[str] = Field(default=None, description="e.g. llama-3.3-70b-versatile, gemini-1.5-pro")
    model_version: Optional[str] = Field(default=None, description="Model release version or checkpoint")
    agent_name: Optional[str] = Field(default=None, description="Cognitive agent identifier")
    agent_version: Optional[str] = Field(default=None, description="Agent code version")
    prompt_version: Optional[str] = Field(default=None, description="System prompt template version")
    tool_version: Optional[str] = Field(default=None, description="Invoked tool version")


class LedgerEvent(BaseModel):
    """
    Canonical Immutable Audit Ledger Event.
    Represents an atomic, tamper-evident record of a significant operational or security fact.
    """
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:16]}", description="Unique immutable event identifier")
    event_type: str = Field(..., description="Machine-readable event type string from EventType")
    event_version: str = Field(default="v1", description="Event schema version to ensure future backwards compatibility")
    category: EventCategory = Field(default=EventCategory.SYSTEM, description="Domain category")
    event_status: EventStatus = Field(default=EventStatus.SUCCESS, description="Status/outcome of the logged fact")
    
    occurred_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        description="UTC timestamp when the event occurred in the system"
    )
    recorded_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        description="UTC timestamp when the event was committed to the ledger"
    )

    # Scoping Boundaries
    tenant_id: str = Field(default="tenant_default", description="Authoritative tenant identifier")
    workspace_id: str = Field(default="workspace_default", description="Authoritative workspace identifier")
    session_id: Optional[str] = Field(default=None, description="Optional session correlation identifier")
    plant_id: Optional[str] = Field(default=None, description="Industrial plant identifier")

    # Identity & Context
    actor: LedgerActor = Field(..., description="Entity responsible for initiating or generating the event")
    request_id: Optional[str] = Field(default=None, description="HTTP or API correlation request ID")
    trace_id: Optional[str] = Field(default=None, description="Distributed execution trace ID")
    correlation_id: Optional[str] = Field(default=None, description="Business workflow or incident correlation ID")

    # Resource & Workflow References
    resource_type: Optional[str] = Field(default=None, description="Target resource type (e.g. action, database, machine)")
    resource_id: Optional[str] = Field(default=None, description="Target resource identifier")
    action_id: Optional[str] = Field(default=None, description="Associated Action ID if applicable")
    mission_id: Optional[str] = Field(default=None, description="Associated Mission ID if applicable")
    incident_id: Optional[str] = Field(default=None, description="Associated Incident ID if applicable")

    data_mode: str = Field(default="REAL", description="Operational data mode: REAL, SIMULATION, or HYBRID")
    
    # Redacted Structured Payload & Metadata
    payload: Dict[str, Any] = Field(default_factory=dict, description="Redacted, structured event details")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Environmental and diagnostic context")

    # Provenance Tracking
    model_provenance: Optional[ModelProvenance] = Field(default=None, description="AI model provenance if generated by agent")
    policy_version: Optional[str] = Field(default=None, description="Governing policy ID and version at evaluation time")
    authorization_version: Optional[str] = Field(default=None, description="Role or authorization config version at evaluation time")

    # Ordering & Hash Integrity Chain
    previous_event_id: Optional[str] = Field(default=None, description="Event ID of immediately preceding event in sequence")
    sequence_number: Optional[int] = Field(default=None, description="Monotonically increasing sequence number within partition")
    event_hash: str = Field(default="", description="Deterministic SHA-256 tamper-evident fingerprint of canonical event fields")

    @classmethod
    def compute_hash(
        cls,
        event_id: str,
        event_type: str,
        occurred_at: str,
        tenant_id: str,
        workspace_id: str,
        actor_id: str,
        payload: Dict[str, Any],
        previous_event_id: Optional[str] = None
    ) -> str:
        """Calculates a deterministic SHA-256 fingerprint over canonical event fields."""
        data = {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "actor_id": actor_id,
            "payload": payload,
            "previous_event_id": previous_event_id or ""
        }
        raw_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()

    def finalize_hash(self) -> str:
        """Sets self.event_hash based on current model attributes."""
        self.event_hash = self.compute_hash(
            event_id=self.event_id,
            event_type=self.event_type,
            occurred_at=self.occurred_at,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            actor_id=self.actor.actor_id,
            payload=self.payload,
            previous_event_id=self.previous_event_id
        )
        return self.event_hash


class DecisionRecord(BaseModel):
    """
    High-Level Decision Graph Aggregation.
    Assembles the complete historical lineage of an operational decision:
    Observation -> Evidence -> AI Reasoning -> Action Proposal -> Authorization -> Policy -> Human Approval -> Execution (Deferred) -> Verification (Deferred).
    """
    decision_id: str = Field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:12]}", description="Unique decision correlation ID")
    decision_type: str = Field(default="ACTION_PROPOSAL", description="Type of decision record")
    subject_type: str = Field(default="ACTION", description="Domain subject e.g. ACTION, INCIDENT")
    subject_id: str = Field(..., description="Identifier of the governed subject (e.g. action_id)")

    tenant_id: str = Field(..., description="Tenant boundary")
    workspace_id: str = Field(default="workspace_default", description="Workspace boundary")
    session_id: Optional[str] = Field(default=None, description="Session boundary")
    plant_id: Optional[str] = Field(default=None, description="Plant boundary")

    actor: LedgerActor = Field(..., description="Initiating actor (User or Agent)")
    action_id: Optional[str] = Field(default=None, description="Associated action identifier")
    incident_id: Optional[str] = Field(default=None, description="Associated incident identifier if triggered by anomaly")
    mission_id: Optional[str] = Field(default=None, description="Associated mission identifier")

    # Decision Lineage References
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list, description="Telemetry, sensor, and anomaly evidence items")
    authorization_decision_id: Optional[str] = Field(default=None, description="Authorization decision correlation ID")
    policy_decision_id: Optional[str] = Field(default=None, description="Policy decision correlation ID")
    approval_id: Optional[str] = Field(default="NOT_AVAILABLE", description="Approval ID (Prompt 08 marks as NOT_AVAILABLE / DEFERRED)")
    execution_id: Optional[str] = Field(default="NOT_AVAILABLE", description="Execution ID (strictly NOT_AVAILABLE in Prompt 08)")
    verification_id: Optional[str] = Field(default="NOT_AVAILABLE", description="Verification ID (strictly NOT_AVAILABLE in Prompt 08)")

    decision: str = Field(default="PROPOSED", description="Overall decision outcome e.g. PROPOSED, ALLOWED, HELD")
    reason: str = Field(default="", description="Structured rationale for decision")
    risk_level: str = Field(default="LOW", description="Risk classification: LOW, MEDIUM, HIGH, CRITICAL")
    data_mode: str = Field(default="REAL", description="REAL or SIMULATION")

    model_provenance: Optional[ModelProvenance] = Field(default=None, description="Model provenance if AI-proposed")
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# =====================================================================
# API REQUEST & RESPONSE ENVELOPES
# =====================================================================

class LedgerEventResponse(BaseModel):
    """Response envelope for single event lookup."""
    success: bool
    request_id: str
    event: LedgerEvent


class LedgerEventListResponse(BaseModel):
    """Paginated response envelope for audit event queries."""
    success: bool
    request_id: str
    total_count: int
    limit: int
    offset: int
    events: List[LedgerEvent]


class TimelineResponse(BaseModel):
    """Chronologically ordered timeline response for correlation or action reconstruction."""
    success: bool
    request_id: str
    correlation_id: Optional[str] = None
    action_id: Optional[str] = None
    total_events: int
    timeline: List[LedgerEvent]


class DecisionRecordResponse(BaseModel):
    """Response envelope for structured DecisionRecord lookup."""
    success: bool
    request_id: str
    decision_record: DecisionRecord
