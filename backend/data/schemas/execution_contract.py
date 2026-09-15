# backend/data/schemas/execution_contract.py
"""
SageCommand V3 — Execution Gateway Canonical Domain Contracts
Defines typed, deterministic schemas for execution requests, execution results,
execution statuses, affected resources, and execution verification envelopes.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ExecutionStatus(str, Enum):
    """Lifecycle execution statuses."""
    PENDING = "PENDING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ALREADY_EXECUTING = "ALREADY_EXECUTING"


class ExecutionRequest(BaseModel):
    """Payload for requesting action or transaction execution."""
    model_config = ConfigDict(extra="ignore")

    action_id: Optional[str] = Field(default=None, description="Identifier of the structured action")
    transaction_id: Optional[str] = Field(default=None, description="Identifier of the transaction plan")
    idempotency_key: Optional[str] = Field(default=None, description="Optional client idempotency key")
    approval_token: Optional[str] = Field(default=None, description="Optional cryptographic approval verification token")
    dry_run: bool = Field(default=False, description="Dry-run simulation mode flag (never mutates operational state)")


class ExecutionResult(BaseModel):
    """Deterministic server-authoritative execution result contract."""
    model_config = ConfigDict(extra="ignore")

    execution_id: str = Field(..., description="Unique execution instance identifier (exec_...)")
    action_id: str = Field(..., description="Executed or evaluated action ID")
    transaction_id: Optional[str] = Field(default=None, description="Bound transaction ID if planned")
    status: ExecutionStatus = Field(..., description="Final execution outcome status")
    started_at: str = Field(..., description="ISO 8601 execution start timestamp")
    completed_at: Optional[str] = Field(default=None, description="ISO 8601 execution completion timestamp")
    actor_id: str = Field(..., description="Authoritative user ID who initiated execution")
    tenant_id: str = Field(..., description="Scoped tenant identifier")
    workspace_id: str = Field(..., description="Scoped workspace identifier")
    session_id: str = Field(..., description="Scoped session identifier")
    target: Dict[str, Any] = Field(default_factory=dict, description="Target resource definition")
    affected_resources: List[Dict[str, Any]] = Field(default_factory=list, description="Resources modified or affected")
    affected_rows: int = Field(default=0, description="Count of modified database rows")
    verification_status: str = Field(default="VERIFIED", description="VERIFIED | UNVERIFIED | FAILED | NOT_APPLICABLE")
    rollback_status: Optional[str] = Field(default=None, description="NOT_REQUESTED | SUCCEEDED | FAILED | NOT_SUPPORTED")
    error_code: Optional[str] = Field(default=None, description="Standardized error code if execution or verification failed")
    error_message: Optional[str] = Field(default=None, description="Safe human-readable error explanation")
    correlation_id: str = Field(..., description="Traceability correlation ID across Action, Transaction, and Audit")
    audit_reference: Optional[str] = Field(default=None, description="Audit ledger event sequence hash")
    data_mode: str = Field(default="REAL", description="REAL | SIMULATION | HYBRID")
    output_payload: Optional[Dict[str, Any]] = Field(default=None, description="Action-specific execution output details")


class RollbackRequest(BaseModel):
    """Payload for requesting transaction rollback."""
    model_config = ConfigDict(extra="ignore")

    reason: str = Field(default="Operator requested rollback", description="Operational justification for rollback")
    idempotency_key: Optional[str] = Field(default=None, description="Optional client idempotency key")


class ActionExecuteResponse(BaseModel):
    success: bool = True
    request_id: str
    result: ExecutionResult


class TransactionExecuteResponse(BaseModel):
    success: bool = True
    request_id: str
    result: ExecutionResult


class TransactionRollbackResponse(BaseModel):
    success: bool = True
    request_id: str
    result: ExecutionResult

