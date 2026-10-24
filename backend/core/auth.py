# backend/core/auth.py
"""
SageCommand V3 — Authentication & Identity Context Provider
Integrates with RBAC + ABAC Authorization Architecture.
Maintains full backward compatibility with development tokens and role checks.
"""

import uuid
import time
import jwt
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import Request, HTTPException, Depends, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

try:
    from core.config import (
        SAGE_ENV,
        SAGE_AUTH_ENABLED,
        SAGE_AUTH_PROVIDER,
        SAGE_SECRET_KEY,
        IS_PRODUCTION,
        SAGE_AUTH_ISSUER,
        SAGE_AUTH_AUDIENCE,
        SAGE_JWT_ALGORITHMS,
        SAGE_AUTH_SESSION_CLAIM
    )
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
    from backend.core.config import (
        SAGE_ENV,
        SAGE_AUTH_ENABLED,
        SAGE_AUTH_PROVIDER,
        SAGE_SECRET_KEY,
        IS_PRODUCTION,
        SAGE_AUTH_ISSUER,
        SAGE_AUTH_AUDIENCE,
        SAGE_JWT_ALGORITHMS,
        SAGE_AUTH_SESSION_CLAIM
    )
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

DEV_MOCK_TOKENS = {
    "operator_token",
    "manager_token",
    "admin_token",
    "security_token",
    "viewer_token",
    "safety_token",
    "test_token_tenant_a",
    "test_token_tenant_b",
}


class Identity(BaseModel):
    """Authenticated user/session identity context."""
    user_id: str = Field(default="user_dev_01")
    tenant_id: str = Field(default="tenant_default")
    workspace_id: str = Field(default="workspace_default")
    roles: List[str] = Field(default_factory=lambda: ["operator", "manager"])
    permissions: List[str] = Field(default_factory=lambda: ["read", "write", "execute"])
    session_id: Optional[str] = Field(default=None)
    authentication_method: str = Field(default="dev_auth")
    status: str = Field(default="ACTIVE")
    assigned_plants: Optional[List[str]] = Field(default_factory=lambda: ["*"])
    clearance_level: int = Field(default=1)
    is_server_authoritative: bool = Field(default=False)

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
            assigned_plants=self.assigned_plants or [],
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
    Supports server-side token profiles and delegates to JWT validation if a JWT token is supplied.
    """
    def authenticate_token(self, token: str) -> Identity:
        if IS_PRODUCTION:
            log_security_event("LOGIN_FAILURE", {"reason": "DevAuthenticationProvider invoked in production"}, severity="CRITICAL")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Development authentication provider is disabled in production.")
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token required.")
        if token == "invalid_token":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.")
        if token == "expired_token":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token expired.")

        # Fixed server-authoritative test fixture tokens
        if token == "test_token_tenant_a":
            return Identity(
                user_id="user_tenant_a",
                tenant_id="tenant_A",
                workspace_id="workspace_A",
                session_id="session_A",
                roles=["operator", "manager"],
                assigned_plants=["plant_A"],
                clearance_level=2,
                authentication_method="dev_auth",
                is_server_authoritative=True
            )
        if token == "test_token_tenant_b":
            return Identity(
                user_id="user_tenant_b",
                tenant_id="tenant_B",
                workspace_id="workspace_B",
                session_id="session_B",
                roles=["operator", "manager"],
                assigned_plants=["plant_B"],
                clearance_level=2,
                authentication_method="dev_auth",
                is_server_authoritative=True
            )

        # Standard dev role profiles
        if token == "operator_token":
            return Identity(
                user_id="op_123",
                roles=["operator"],
                permissions=["read"],
                assigned_plants=["plant_01"],
                clearance_level=1,
                authentication_method="dev_auth",
                is_server_authoritative=False
            )
        if token == "manager_token":
            return Identity(
                user_id="mgr_456",
                roles=["operator", "manager", "plant_manager"],
                permissions=["read", "write", "execute"],
                clearance_level=2,
                assigned_plants=["plant_01", "plant_mumbai", "*"],
                authentication_method="dev_auth",
                is_server_authoritative=False
            )
        if token == "admin_token":
            return Identity(user_id="admin_01", roles=["administrator"], clearance_level=3, assigned_plants=["*"], authentication_method="dev_auth", is_server_authoritative=False)
        if token == "security_token":
            return Identity(user_id="sec_admin_01", roles=["security_admin"], clearance_level=3, assigned_plants=["*"], authentication_method="dev_auth", is_server_authoritative=False)
        if token == "viewer_token":
            return Identity(user_id="view_01", roles=["viewer"], clearance_level=1, assigned_plants=["plant_01"], authentication_method="dev_auth", is_server_authoritative=False)
        if token == "safety_token":
            return Identity(user_id="safety_01", roles=["safety_manager"], clearance_level=2, assigned_plants=["plant_01"], authentication_method="dev_auth", is_server_authoritative=False)

        # If a token has standard 3-part JWT structure, validate it cryptographically
        if token and token.count(".") == 2:
            jwt_provider = JWTAuthenticationProvider()
            return jwt_provider.authenticate_token(token)

        # Unknown tokens fail closed when auth is enabled
        if SAGE_AUTH_ENABLED:
            log_security_event("LOGIN_FAILURE", {"reason": "Unknown development authentication token"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.")

        return Identity(user_id="dev_operator", roles=["operator", "manager"], authentication_method="dev_mode", is_server_authoritative=False)

    def authenticate_request(self, request: Request) -> Identity:
        if IS_PRODUCTION:
            log_security_event("LOGIN_FAILURE", {"reason": "DevAuthenticationProvider invoked in production"}, severity="CRITICAL")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Development authentication provider is disabled in production.")
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            return self.authenticate_token(token)
        if SAGE_AUTH_ENABLED:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication credentials required.")
        return Identity(user_id="dev_operator", roles=["operator", "manager"], authentication_method="dev_mode", is_server_authoritative=False)


class JWTAuthenticationProvider(AuthenticationProvider):
    """
    Production JWT / OIDC Authentication Provider.
    Enforces cryptographic signature verification, algorithm allowlists,
    token expiration, audience/issuer checks, and server-authoritative claims.
    """
    def __init__(
        self,
        secret_key: str = SAGE_SECRET_KEY,
        algorithms: Optional[List[str]] = None,
        issuer: Optional[str] = SAGE_AUTH_ISSUER,
        audience: Optional[str] = SAGE_AUTH_AUDIENCE,
        session_claim: Optional[str] = None
    ):
        self.secret_key = secret_key
        raw_algs = algorithms or SAGE_JWT_ALGORITHMS or ["HS256"]
        self.algorithms = [a.strip() for a in raw_algs if a.strip().lower() != "none"]
        self.issuer = issuer
        self.audience = audience
        self.session_claim = session_claim or SAGE_AUTH_SESSION_CLAIM or "session_id"

    def authenticate_token(self, token: str) -> Identity:
        if not token:
            log_security_event("LOGIN_FAILURE", {"reason": "Missing JWT token"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token required.")

        # Rejection of explicit invalid or expired tokens
        if token in ("invalid_token", "expired_token"):
            log_security_event("LOGIN_FAILURE", {"reason": "Explicit invalid/expired test token rejected"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired JWT token.")

        # Backward compatibility for existing unit tests running with mock tokens when NOT in production
        if not IS_PRODUCTION and SAGE_AUTH_PROVIDER != "jwt":
            if token == "manager_token":
                return Identity(user_id="prod_mgr", roles=["operator", "manager", "plant_manager"], authentication_method="jwt", clearance_level=2, is_server_authoritative=False)
            if token == "operator_token":
                return Identity(user_id="prod_op", roles=["operator"], authentication_method="jwt", clearance_level=1, is_server_authoritative=False)
            if token == "admin_token":
                return Identity(user_id="prod_admin", roles=["administrator"], authentication_method="jwt", clearance_level=3, is_server_authoritative=False)
            if token == "security_token":
                return Identity(user_id="prod_sec", roles=["security_admin"], authentication_method="jwt", clearance_level=3, is_server_authoritative=False)
            if token == "viewer_token":
                return Identity(user_id="prod_view", roles=["viewer"], authentication_method="jwt", clearance_level=1, is_server_authoritative=False)

        # Real Cryptographic JWT Verification
        try:
            unverified_header = jwt.get_unverified_header(token)
            alg = unverified_header.get("alg", "").upper()
            if not alg or alg == "NONE" or alg not in [a.upper() for a in self.algorithms]:
                log_security_event("LOGIN_FAILURE", {"reason": f"Prohibited or unsupported JWT algorithm: {alg}"}, severity="WARNING")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Unsupported or prohibited JWT algorithm: '{alg}'.")
        except jwt.DecodeError as e:
            log_security_event("LOGIN_FAILURE", {"reason": f"Malformed JWT header: {str(e)}"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed JWT token.")
        except HTTPException:
            raise
        except Exception as e:
            log_security_event("LOGIN_FAILURE", {"reason": f"JWT inspection error: {str(e)}"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT token header.")

        if IS_PRODUCTION:
            decode_options = {
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
                "require": ["exp", "iss", "aud", "sub"]
            }
        else:
            decode_options = {
                "verify_signature": True,
                "verify_exp": True,
                "require": ["exp", "sub"]
            }

        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=self.algorithms,
                issuer=self.issuer if self.issuer else None,
                audience=self.audience if self.audience else None,
                options=decode_options
            )
        except jwt.ExpiredSignatureError:
            log_security_event("LOGIN_FAILURE", {"reason": "JWT token has expired"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT token has expired.")
        except jwt.InvalidAlgorithmError as alg_err:
            log_security_event("LOGIN_FAILURE", {"reason": f"Invalid algorithm: {str(alg_err)}"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT algorithm.")
        except jwt.InvalidSignatureError:
            log_security_event("LOGIN_FAILURE", {"reason": "Cryptographic signature verification failed"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT signature.")
        except jwt.InvalidIssuerError:
            log_security_event("LOGIN_FAILURE", {"reason": "JWT issuer mismatch"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT issuer.")
        except jwt.InvalidAudienceError:
            log_security_event("LOGIN_FAILURE", {"reason": "JWT audience mismatch"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid JWT audience.")
        except jwt.DecodeError as decode_err:
            log_security_event("LOGIN_FAILURE", {"reason": f"JWT decode error: {str(decode_err)}"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or malformed JWT token.")
        except Exception as e:
            log_security_event("LOGIN_FAILURE", {"reason": f"JWT validation failed: {str(e)}"}, severity="WARNING")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT authentication failed.")

        user_id = str(payload.get("sub", ""))
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing required 'sub' claim in JWT.")

        tenant_id = str(payload.get("tenant_id", "tenant_default"))
        workspace_id = str(payload.get("workspace_id", "workspace_default"))
        # Security Hardening: Session derived strictly from configured claim name,
        # with fallback to OIDC 'sid' claim when default claim ('session_id') is used.
        session_id_val = payload.get(self.session_claim)
        if session_id_val is None and self.session_claim == "session_id":
            session_id_val = payload.get("sid")
        session_id = str(session_id_val) if session_id_val is not None else None

        roles = payload.get("roles", ["operator"])
        if isinstance(roles, str):
            roles = [roles]

        clearance_level = payload.get("clearance_level", 1)
        try:
            clearance_level = int(clearance_level)
        except (ValueError, TypeError):
            clearance_level = 1

        assigned_plants = payload.get("assigned_plants", ["plant_01"])
        if isinstance(assigned_plants, str):
            assigned_plants = [assigned_plants]

        status_val = str(payload.get("status", "ACTIVE"))

        return Identity(
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            roles=roles,
            clearance_level=clearance_level,
            assigned_plants=assigned_plants,
            status=status_val,
            authentication_method="jwt",
            is_server_authoritative=True
        )

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

    if credentials and isinstance(credentials, HTTPAuthorizationCredentials):
        identity = provider.authenticate_token(credentials.credentials)
    elif not SAGE_AUTH_ENABLED and not IS_PRODUCTION and not request.headers.get("Authorization"):
        identity = Identity(user_id="dev_user", roles=["operator", "manager"], is_server_authoritative=False)
    else:
        identity = provider.authenticate_request(request)


    # CRITICAL SECURITY INVARIANT:
    # Client headers (X-Clearance-Level, X-Assigned-Plants) must NEVER escalate privileges.
    # Logic overriding clearance_level and assigned_plants from headers is permanently REMOVED.

    # If identity is established by verified JWT claims or an authoritative token profile,
    # or if the server is running in production mode, NO client header is authoritative.
    # HARDENING RULE: A client X-Session-ID header must NOT supply a session for a JWT identity.
    # For JWT, session_id is strictly derived from the verified token claim (None if omitted).
    if IS_PRODUCTION or identity.is_server_authoritative:
        return identity

    # In development/test mode ONLY, allow session and tenant continuity for unbound generic dev tokens
    session_hdr = request.headers.get("X-Session-ID") or request.headers.get("x-session-id")
    if session_hdr:
        identity.session_id = session_hdr
    else:
        identity.session_id = None

    tenant_hdr = request.headers.get("X-Tenant-ID") or request.headers.get("x-tenant-id")
    if tenant_hdr:
        identity.tenant_id = tenant_hdr

    workspace_hdr = request.headers.get("X-Workspace-ID") or request.headers.get("x-workspace-id")
    if workspace_hdr:
        identity.workspace_id = workspace_hdr

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


def verify_production_boot_guards() -> None:
    """
    Production Startup Boot Guard.
    Refuses to boot in production unless all production auth & security invariants are satisfied:
    - Auth is enabled (SAGE_AUTH_ENABLED is True)
    - Auth provider is JWT (SAGE_AUTH_PROVIDER == "jwt")
    - SAGE_AUTH_ISSUER and SAGE_AUTH_AUDIENCE are non-empty
    - SAGE_SECRET_KEY is not the default literal and is at least 32 bytes (256 bits)
    - SAGE_JWT_ALGORITHMS is HS256 only ("none" strictly forbidden)
    - DEV_MOCK_TOKENS are unreachable
    In non-production (development/test), issues a clear startup warning.
    """
    if not IS_PRODUCTION:
        print(f" [Server Startup] WARNING: Running in non-production environment: SAGE_ENV='{SAGE_ENV}'. Security guards relaxed for development/testing only.")
        return

    # 1. Auth enabled
    if not SAGE_AUTH_ENABLED:
        raise RuntimeError("Production boot guard failed: SAGE_AUTH_ENABLED must be True in production.")

    # 2. Provider is JWT
    if SAGE_AUTH_PROVIDER != "jwt":
        raise RuntimeError("Production boot guard failed: SAGE_AUTH_PROVIDER must be 'jwt' in production.")

    # 3. Issuer and Audience set
    if not SAGE_AUTH_ISSUER or not SAGE_AUTH_ISSUER.strip():
        raise RuntimeError("Production boot guard failed: SAGE_AUTH_ISSUER must be configured non-empty in production.")
    if not SAGE_AUTH_AUDIENCE or not SAGE_AUTH_AUDIENCE.strip():
        raise RuntimeError("Production boot guard failed: SAGE_AUTH_AUDIENCE must be configured non-empty in production.")

    # 4. Effective signing key is not the default literal and is >= 32 bytes
    default_dev_key = "sagecommand_default_dev_secret_key_change_in_production"
    if not SAGE_SECRET_KEY or SAGE_SECRET_KEY == default_dev_key:
        raise RuntimeError("Production boot guard failed: SAGE_SECRET_KEY cannot use the default dev literal in production.")
    if len(SAGE_SECRET_KEY.encode("utf-8")) < 32:
        raise RuntimeError("Production boot guard failed: SAGE_SECRET_KEY must be at least 32 bytes in production.")

    # 5. Production algorithms: HS256 only, "none" never allowed
    for alg in SAGE_JWT_ALGORITHMS:
        if alg.lower() == "none":
            raise RuntimeError("Production boot guard failed: Algorithm 'none' is never allowed.")
        if alg != "HS256":
            raise RuntimeError(f"Production boot guard failed: Unsupported production algorithm '{alg}'. Production algorithms: HS256 only (RS256 deferred until JWKS).")

    # 6. DEV_MOCK_TOKENS are unreachable
    provider = get_auth_provider()
    if not isinstance(provider, JWTAuthenticationProvider):
        raise RuntimeError(f"Production boot guard failed: Active auth provider {type(provider).__name__} is not JWTAuthenticationProvider.")

    for mock_tok in DEV_MOCK_TOKENS:
        try:
            provider.authenticate_token(mock_tok)
            raise RuntimeError(f"Production boot guard failed: DEV_MOCK_TOKEN '{mock_tok}' is reachable in production.")
        except HTTPException:
            pass  # Expected rejection

