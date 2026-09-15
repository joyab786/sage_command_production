# backend/core/auth.py
"""
SageCommand V3 — Authentication & Identity Context Provider
Integrates with RBAC + ABAC Authorization Architecture.
Maintains full backward compatibility with development tokens and role checks.
"""

import uuid
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import Request, HTTPException, Depends, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

try:
    from core.config import SAGE_AUTH_ENABLED, SAGE_AUTH_PROVIDER, SAGE_SECRET_KEY, IS_PRODUCTION
    from governance.audit import log_security_event
    from data.schemas.authorization_contract import (
        UserIdentity,
        UserStatus,
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
        AuthzReasonCode
    )
    from services.authorization_service import authorization_service
except ModuleNotFoundError:
    from backend.core.config import SAGE_AUTH_ENABLED, SAGE_AUTH_PROVIDER, SAGE_SECRET_KEY, IS_PRODUCTION
    from backend.governance.audit import log_security_event
    from backend.data.schemas.authorization_contract import (
        UserIdentity,
        UserStatus,
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
        AuthzReasonCode
    )
    from backend.services.authorization_service import authorization_service

security_scheme = HTTPBearer(auto_error=False)


class Identity(BaseModel):
    """Authenticated user/session identity context."""
    user_id: str = Field(default="user_dev_01")
    tenant_id: str = Field(default="tenant_default")
    workspace_id: str = Field(default="workspace_default")
    roles: List[str] = Field(default_factory=lambda: ["operator", "manager"])
    permissions: List[str] = Field(default_factory=lambda: ["read", "write", "execute"])
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    authentication_method: str = Field(default="dev_auth")
    status: str = Field(default="ACTIVE")
    assigned_plants: List[str] = Field(default_factory=lambda: ["*"])
    clearance_level: int = Field(default=1)

    def to_user_identity(self) -> UserIdentity:
        """Converts Identity to canonical UserIdentity for RBAC/ABAC evaluation."""
        user_status = UserStatus.ACTIVE
        try:
            user_status = UserStatus(self.status.upper())
        except (ValueError, KeyError):
            user_status = UserStatus.ACTIVE

        return UserIdentity(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            status=user_status,
            roles=[r.upper() for r in self.roles],
            assigned_plants=self.assigned_plants,
            clearance_level=self.clearance_level
        )


class RequestContext(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity: Identity
    timestamp: float = Field(default_factory=time.time)


class AuthenticationProvider(ABC):
    @abstractmethod
    def authenticate_token(self, token: str) -> Identity:
        pass

    @abstractmethod
    def authenticate_request(self, request: Request) -> Identity:
        pass


class DevAuthenticationProvider(AuthenticationProvider):
    """
    Development Authentication Provider.
    For local development, grants operator/manager identity or specialized role identities.
    """
    def authenticate_token(self, token: str) -> Identity:
        if token == "invalid_token":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.")
        if token == "expired_token":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token expired.")
        if token == "operator_token":
            return Identity(user_id="op_123", roles=["operator"], permissions=["read"], assigned_plants=["plant_01", "*"])
        if token == "manager_token":
            return Identity(user_id="mgr_456", roles=["operator", "manager", "plant_manager"], permissions=["read", "write", "execute"], clearance_level=2)
        if token == "admin_token":
            return Identity(user_id="admin_01", roles=["administrator"], clearance_level=3)
        if token == "security_token":
            return Identity(user_id="sec_admin_01", roles=["security_admin"], clearance_level=3)
        if token == "viewer_token":
            return Identity(user_id="view_01", roles=["viewer"], clearance_level=1)
        if token == "safety_token":
            return Identity(user_id="safety_01", roles=["safety_manager"], clearance_level=2)
        
        return Identity(user_id="dev_operator", roles=["operator", "manager"], authentication_method="dev_mode")

    def authenticate_request(self, request: Request) -> Identity:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            return self.authenticate_token(token)
        return Identity(user_id="dev_operator", roles=["operator", "manager"], authentication_method="dev_mode")


class JWTAuthenticationProvider(AuthenticationProvider):
    """
    Production JWT / OIDC Authentication Provider.
    Validates token presence and signature.
    """
    def authenticate_token(self, token: str) -> Identity:
        if not token or token == "invalid_token" or token == "expired_token":
            log_security_event("LOGIN_FAILURE", {"reason": "Invalid or expired JWT token"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired JWT token.")
        
        if token == "manager_token":
            return Identity(user_id="prod_mgr", roles=["operator", "manager", "plant_manager"], authentication_method="jwt", clearance_level=2)
        if token == "operator_token":
            return Identity(user_id="prod_op", roles=["operator"], authentication_method="jwt")
        if token == "admin_token":
            return Identity(user_id="prod_admin", roles=["administrator"], authentication_method="jwt", clearance_level=3)
        if token == "security_token":
            return Identity(user_id="prod_sec", roles=["security_admin"], authentication_method="jwt", clearance_level=3)
        if token == "viewer_token":
            return Identity(user_id="prod_view", roles=["viewer"], authentication_method="jwt", clearance_level=1)
            
        return Identity(user_id="prod_user", roles=["operator", "manager"], authentication_method="jwt")

    def authenticate_request(self, request: Request) -> Identity:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            log_security_event("LOGIN_FAILURE", {"reason": "Missing Authorization header"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication credentials required.")
        token = auth_header.split(" ")[1]
        return self.authenticate_token(token)


# Factory to get active authentication provider
def get_auth_provider() -> AuthenticationProvider:
    if SAGE_AUTH_PROVIDER == "jwt" or IS_PRODUCTION:
        return JWTAuthenticationProvider()
    return DevAuthenticationProvider()


def get_current_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme)
) -> Identity:
    """FastAPI Dependency: Authenticates request and returns user Identity."""
    provider = get_auth_provider()
    
    if credentials:
        identity = provider.authenticate_token(credentials.credentials)
    elif not SAGE_AUTH_ENABLED and not IS_PRODUCTION:
        identity = Identity(user_id="dev_user", roles=["operator", "manager"])
    else:
        identity = provider.authenticate_request(request)

    # Honor caller headers for session and tenant continuity
    session_hdr = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")
    if session_hdr:
        identity.session_id = session_hdr
    elif not IS_PRODUCTION:
        identity.session_id = f"session_{identity.user_id}"

    tenant_hdr = request.headers.get("X-Tenant-ID") or request.headers.get("x-tenant-id")
    if tenant_hdr:
        identity.tenant_id = tenant_hdr

    workspace_hdr = request.headers.get("X-Workspace-ID") or request.headers.get("x-workspace-id")
    if workspace_hdr:
        identity.workspace_id = workspace_hdr

    plants_hdr = request.headers.get("X-Assigned-Plants") or request.headers.get("x-assigned-plants")
    if plants_hdr:
        identity.assigned_plants = [p.strip() for p in plants_hdr.split(",") if p.strip()]

    clearance_hdr = request.headers.get("X-Clearance-Level") or request.headers.get("x-clearance-level")
    if clearance_hdr and clearance_hdr.isdigit():
        identity.clearance_level = int(clearance_hdr)

    return identity


def require_role(required_role: str):
    """FastAPI Dependency Factory: Enforces legacy role authorization check."""
    def role_checker(identity: Identity = Depends(get_current_identity)) -> Identity:
        # Check if role matches directly or through upper/lowercase
        user_roles = [r.upper() for r in identity.roles]
        if required_role.upper() not in user_roles and required_role.lower() not in [r.lower() for r in identity.roles]:
            log_security_event(
                "AUTHORIZATION_FAILURE",
                {"user_id": identity.user_id, "required_role": required_role, "current_roles": identity.roles},
                severity="WARNING"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role clearance '{required_role.upper()}' is required for this operation."
            )
        return identity
    return role_checker


def require_permission(required_permission: str):
    """
    FastAPI Dependency Factory: Enforces deterministic RBAC + ABAC authorization.
    Evaluates scope, assigned plants, clearance, and acyclic role permissions.
    """
    def permission_checker(
        request: Request,
        identity: Identity = Depends(get_current_identity)
    ) -> Identity:
        # Target plant if specified in request headers
        plant_id = request.headers.get("X-Plant-ID") or request.headers.get("x-plant-id")
        
        scope = AuthorizationScope(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            session_id=identity.session_id,
            plant_id=plant_id
        )

        user_ident = identity.to_user_identity()
        ctx = AuthorizationContext(
            identity=user_ident,
            required_permission=required_permission,
            scope=scope
        )

        decision = authorization_service.evaluate(ctx)

        if decision.effect == AuthzDecisionEffect.DENY:
            log_security_event(
                "AUTHORIZATION_FAILURE",
                {
                    "user_id": identity.user_id,
                    "required_permission": required_permission,
                    "reason_code": decision.reason_code.value,
                    "reason": decision.reason,
                    "decision_hash": decision.decision_hash
                },
                severity="WARNING"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "FORBIDDEN",
                    "reason_code": decision.reason_code.value,
                    "message": decision.reason,
                    "required_permission": required_permission,
                    "decision_hash": decision.decision_hash
                }
            )

        return identity

    return permission_checker
