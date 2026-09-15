# backend/data/schemas/authorization_contract.py
"""
SageCommand V3 — Canonical Authorization Domain Schemas
Defines core models, enums, contexts, and decision contracts for RBAC + ABAC.
Follows fail-closed security invariants:
- Authentication != Authorization != Policy != Approval != Execution
- Clear separation between administrative privileges and operational authority
- Tenant, workspace, session, and plant scoping with deterministic hash verification
"""

import hashlib
import json
import time
import uuid
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, validator


class UserStatus(str, Enum):
    """Lifecycle status of an authenticated user."""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    PENDING = "PENDING"


class RoleScopeType(str, Enum):
    """Scope boundaries where a role applies."""
    SYSTEM = "SYSTEM"
    TENANT = "TENANT"
    WORKSPACE = "WORKSPACE"
    PLANT = "PLANT"


class AuthzDecisionEffect(str, Enum):
    """Deterministic authorization decision outcome."""
    ALLOW = "ALLOW"
    DENY = "DENY"


class AuthzReasonCode(str, Enum):
    """Standardized machine-readable reason codes for authorization decisions."""
    ALLOWED = "ALLOWED"
    IDENTITY_NOT_ACTIVE = "IDENTITY_NOT_ACTIVE"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    SESSION_INVALID = "SESSION_INVALID"
    PLANT_SCOPE_DENIED = "PLANT_SCOPE_DENIED"
    INSUFFICIENT_ROLE_PERMISSIONS = "INSUFFICIENT_ROLE_PERMISSIONS"
    CLEARANCE_LEVEL_INSUFFICIENT = "CLEARANCE_LEVEL_INSUFFICIENT"
    SEPARATION_OF_DUTIES_VIOLATION = "SEPARATION_OF_DUTIES_VIOLATION"
    DATA_MODE_RESTRICTED = "DATA_MODE_RESTRICTED"
    MAINTENANCE_WINDOW_RESTRICTED = "MAINTENANCE_WINDOW_RESTRICTED"
    ADMIN_OPERATIONAL_OVERRIDE_DISALLOWED = "ADMIN_OPERATIONAL_OVERRIDE_DISALLOWED"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    EVALUATION_ERROR = "EVALUATION_ERROR"
    UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"


class Permission(BaseModel):
    """Canonical permission object representing a discrete capability."""
    permission_id: str = Field(..., description="Namespaced capability key e.g. action.create")
    resource: str = Field(..., description="Target resource domain e.g. action, database, policy")
    action: str = Field(..., description="Action capability e.g. create, read, manage")
    description: str = Field(default="", description="Human-readable explanation of capability")
    is_sensitive: bool = Field(default=False, description="Flag indicating high-impact or privileged capability")

    @validator("permission_id")
    def validate_namespaced_id(cls, v: str) -> str:
        if "." not in v or len(v.strip()) < 3:
            raise ValueError(f"permission_id must be namespaced with resource.action notation, got '{v}'")
        return v.strip().lower()


class Role(BaseModel):
    """Canonical role definition supporting acyclic inheritance."""
    role_id: str = Field(..., description="Unique role identifier e.g. OPERATOR")
    name: str = Field(..., description="Display name of the role")
    scope_type: RoleScopeType = Field(default=RoleScopeType.SYSTEM, description="Scope boundary of the role")
    permissions: List[str] = Field(default_factory=list, description="Direct permissions assigned to this role")
    inherits_from: List[str] = Field(default_factory=list, description="Parent roles inherited by this role")
    description: str = Field(default="", description="Description of role responsibilities")
    is_system_role: bool = Field(default=True, description="Flag indicating built-in system role")

    @validator("role_id")
    def validate_role_id(cls, v: str) -> str:
        return v.strip().upper()


class UserIdentity(BaseModel):
    """Rich authorization identity model carrying RBAC and ABAC attributes."""
    user_id: str = Field(..., description="Unique user identifier")
    tenant_id: str = Field(default="tenant_default", description="Authoritative tenant identifier")
    workspace_id: str = Field(default="workspace_default", description="Authoritative workspace identifier")
    session_id: Optional[str] = Field(default=None, description="Optional session correlation identifier")
    status: UserStatus = Field(default=UserStatus.ACTIVE, description="Account lifecycle status")
    roles: List[str] = Field(default_factory=list, description="List of role IDs assigned to user")
    assigned_plants: List[str] = Field(
        default_factory=lambda: ["*"],
        description="Assigned plant identifiers or '*' for all plants"
    )
    clearance_level: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Security clearance level (1=Standard, 2=Elevated, 3=Confidential, 4=Secret, 5=Top Secret)"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary user metadata")

    @validator("roles", each_item=True)
    def normalize_roles(cls, v: str) -> str:
        return v.strip().upper()


class AuthorizationScope(BaseModel):
    """Hierarchical resource scope boundary for authorization checks."""
    tenant_id: str = Field(..., description="Target resource tenant ID")
    workspace_id: Optional[str] = Field(default=None, description="Target resource workspace ID")
    session_id: Optional[str] = Field(default=None, description="Session ID if session-scoped")
    plant_id: Optional[str] = Field(default=None, description="Industrial plant identifier")
    line_id: Optional[str] = Field(default=None, description="Production line identifier")
    machine_id: Optional[str] = Field(default=None, description="Machine/equipment identifier")
    sensor_id: Optional[str] = Field(default=None, description="Sensor/tag identifier")


class AuthorizationContext(BaseModel):
    """Complete evaluation context passed to AuthorizationService."""
    identity: UserIdentity = Field(..., description="User identity with ABAC/RBAC attributes")
    required_permission: str = Field(..., description="Required capability e.g. action.create")
    scope: AuthorizationScope = Field(..., description="Target resource scope")
    action_id: Optional[str] = Field(default=None, description="Optional action correlation ID")
    target_resource: Optional[str] = Field(default=None, description="Target resource identifier or table")
    data_mode: str = Field(default="LIVE", description="Data mode: LIVE, SIMULATION, or HISTORICAL")
    proposer_id: Optional[str] = Field(default=None, description="Proposer user ID for separation of duties")
    required_clearance: int = Field(default=1, description="Minimum clearance level required for action")
    environment_attributes: Dict[str, Any] = Field(default_factory=dict, description="Contextual environment flags")

    @validator("required_permission")
    def normalize_permission(cls, v: str) -> str:
        return v.strip().lower()


class AuthorizationDecision(BaseModel):
    """Deterministic authorization decision record with cryptographic tamper-resistance."""
    decision_id: str = Field(default_factory=lambda: f"authz_{uuid.uuid4().hex[:12]}")
    effect: AuthzDecisionEffect = Field(..., description="ALLOW or DENY")
    reason_code: AuthzReasonCode = Field(..., description="Machine-readable decision reason")
    reason: str = Field(..., description="Human-readable decision explanation")
    required_permission: str = Field(..., description="Permission checked")
    matched_role: Optional[str] = Field(default=None, description="Role that granted the permission if allowed")
    resolved_permissions: List[str] = Field(default_factory=list, description="Effective permissions resolved for user")
    evaluated_at: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        description="UTC timestamp of evaluation"
    )
    decision_hash: str = Field(..., description="SHA-256 tamper-evident fingerprint of decision fields")

    @classmethod
    def create(
        cls,
        effect: AuthzDecisionEffect,
        reason_code: AuthzReasonCode,
        reason: str,
        required_permission: str,
        matched_role: Optional[str] = None,
        resolved_permissions: Optional[List[str]] = None,
        decision_id: Optional[str] = None,
        evaluated_at: Optional[str] = None
    ) -> "AuthorizationDecision":
        d_id = decision_id or f"authz_{uuid.uuid4().hex[:12]}"
        t_str = evaluated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        res_perms = sorted(list(set(resolved_permissions or [])))

        # Canonical hash calculation
        payload = {
            "decision_id": d_id,
            "effect": effect.value,
            "reason_code": reason_code.value,
            "required_permission": required_permission.lower().strip(),
            "matched_role": matched_role or "",
            "evaluated_at": t_str
        }
        raw_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        computed_hash = hashlib.sha256(raw_bytes).hexdigest()

        return cls(
            decision_id=d_id,
            effect=effect,
            reason_code=reason_code,
            reason=reason,
            required_permission=required_permission.lower().strip(),
            matched_role=matched_role,
            resolved_permissions=res_perms,
            evaluated_at=t_str,
            decision_hash=computed_hash
        )


# --- API REQUEST / RESPONSE MODELS ---

class AuthorizationCheckRequest(BaseModel):
    """Payload for POST /api/v3/authorization/check."""
    required_permission: str = Field(..., description="Capability to evaluate e.g. action.create")
    target_scope: AuthorizationScope = Field(..., description="Resource scope boundary")
    action_id: Optional[str] = Field(default=None, description="Action ID if checking action-specific scope")
    target_resource: Optional[str] = Field(default=None, description="Resource identifier")
    data_mode: str = Field(default="LIVE", description="LIVE, SIMULATION, or HISTORICAL")
    proposer_id: Optional[str] = Field(default=None, description="Proposer user ID for separation of duties")
    required_clearance: int = Field(default=1, description="Minimum clearance required")
    context_attributes: Dict[str, Any] = Field(default_factory=dict, description="Additional context attributes")


class AuthorizationCheckResponse(BaseModel):
    """Response envelope for POST /api/v3/authorization/check."""
    success: bool
    request_id: str
    decision: AuthorizationDecision


class RoleListResponse(BaseModel):
    """Response envelope for GET /api/v3/authorization/roles."""
    success: bool
    request_id: str
    roles: List[Role]


class RoleDetailResponse(BaseModel):
    """Response envelope for GET /api/v3/authorization/roles/{role_id}."""
    success: bool
    request_id: str
    role: Role
    effective_permissions: List[str]


class PermissionListResponse(BaseModel):
    """Response envelope for GET /api/v3/authorization/permissions."""
    success: bool
    request_id: str
    permissions: List[Permission]
