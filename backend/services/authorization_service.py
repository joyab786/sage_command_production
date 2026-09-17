# backend/services/authorization_service.py
"""
SageCommand V3 — RBAC + ABAC Authorization Service
Implements deterministic capability evaluation, acyclic role inheritance,
hierarchical scope containment, and separation of duties.
Invariants:
- Fail-closed by default (missing/invalid context yields DENY)
- Administrative privilege != operational authority (no admin backdoor for operational writes)
- Cryptographic decision hash (SHA-256) on every evaluation
- SQLite persistence for roles with synchronized thread-safe caching
"""

import json
import sqlite3
import threading
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

try:
    from core.config import MEMORY_DB_PATH
    from governance.audit import log_security_event
    from data.schemas.authorization_contract import (
        UserStatus,
        RoleScopeType,
        AuthzDecisionEffect,
        AuthzReasonCode,
        Permission,
        Role,
        UserIdentity,
        AuthorizationScope,
        AuthorizationContext,
        AuthorizationDecision,
    )
except ModuleNotFoundError:
    from backend.core.config import MEMORY_DB_PATH
    from backend.governance.audit import log_security_event
    from backend.data.schemas.authorization_contract import (
        UserStatus,
        RoleScopeType,
        AuthzDecisionEffect,
        AuthzReasonCode,
        Permission,
        Role,
        UserIdentity,
        AuthorizationScope,
        AuthorizationContext,
        AuthorizationDecision,
    )


# =====================================================================
# 1. CANONICAL PERMISSION REGISTRY
# =====================================================================

CANONICAL_PERMISSIONS: List[Permission] = [
    # Telemetry & Monitoring
    Permission(permission_id="telemetry.read", resource="telemetry", action="read", description="View real-time and simulated telemetry stream"),
    Permission(permission_id="machine.status.read", resource="machine", action="status.read", description="Read machine health and operational status"),
    
    # Database Operations
    Permission(permission_id="database.read", resource="database", action="read", description="Execute read-only SQL queries and read schema metadata"),
    Permission(permission_id="sql.analyze", resource="sql", action="analyze", description="Run query analysis and schema profiling"),
    Permission(permission_id="database.connection.create", resource="database", action="connection.create", description="Register new database connection target", is_sensitive=True),
    Permission(permission_id="database.connection.admin", resource="database", action="connection.admin", description="Administer gateway connection pool and credentials", is_sensitive=True),
    
    # Structured Actions
    Permission(permission_id="action.create", resource="action", action="create", description="Propose structured operational action"),
    Permission(permission_id="action.read", resource="action", action="read", description="View action proposals, status, and audits"),
    Permission(permission_id="action.simulate", resource="action", action="simulate", description="Request deterministic simulation preview of action"),
    Permission(permission_id="action.cancel", resource="action", action="cancel", description="Cancel pending action proposal"),
    Permission(permission_id="action.approve", resource="action", action="approve", description="Approve action awaiting human verification", is_sensitive=True),
    Permission(permission_id="action.execute", resource="action", action="execute", description="Execute approved or authorized operational action", is_sensitive=True),
    
    # Transaction & Rollback Architecture
    Permission(permission_id="transaction.plan", resource="transaction", action="plan", description="Propose and create transaction plan from action"),
    Permission(permission_id="transaction.read", resource="transaction", action="read", description="View transaction plan and status"),
    Permission(permission_id="transaction.validate", resource="transaction", action="validate", description="Trigger validation or revalidation on transaction plan"),
    Permission(permission_id="transaction.cancel", resource="transaction", action="cancel", description="Cancel planned transaction before execution"),
    Permission(permission_id="transaction.execute", resource="transaction", action="execute", description="Execute approved multi-action transaction plan", is_sensitive=True),
    Permission(permission_id="transaction.rollback", resource="transaction", action="rollback", description="Rollback executed multi-action transaction plan", is_sensitive=True),
    
    # Operational Domain Controls
    Permission(permission_id="production.propose", resource="production", action="propose", description="Propose changes to production schedule or line rates"),
    Permission(permission_id="production.schedule", resource="production", action="schedule", description="Approve or adjust factory production schedule", is_sensitive=True),
    Permission(permission_id="maintenance.propose", resource="maintenance", action="propose", description="Propose machine maintenance lockout or inspection"),
    Permission(permission_id="setpoint.adjust", resource="setpoint", action="adjust", description="Request machine operational setpoint change", is_sensitive=True),
    Permission(permission_id="inventory.adjust", resource="inventory", action="adjust", description="Propose inventory or component count modification"),
    Permission(permission_id="order.expedite", resource="order", action="expedite", description="Request order expediting or priority override"),
    
    # Safety & Emergency Controls
    Permission(permission_id="safety.hold", resource="safety", action="hold", description="Declare safety hold on manufacturing line or equipment", is_sensitive=True),
    Permission(permission_id="emergency.declare", resource="emergency", action="declare", description="Declare emergency condition or safe shutdown sequence", is_sensitive=True),
    
    # Policy & Governance
    Permission(permission_id="policy.read", resource="policy", action="read", description="View deterministic safety policy rules"),
    Permission(permission_id="policy.manage", resource="policy", action="manage", description="Create, update, or archive policy rules", is_sensitive=True),
    Permission(permission_id="audit.read", resource="audit", action="read", description="Inspect security event audit logs", is_sensitive=True),
    Permission(permission_id="security.audit", resource="security", action="audit", description="Conduct security compliance analysis and verification", is_sensitive=True),
    
    # Reporting & Enterprise
    Permission(permission_id="report.generate", resource="report", action="generate", description="Generate executive operational and compliance reports"),
    Permission(permission_id="enterprise.view", resource="enterprise", action="view", description="Enterprise-wide cross-plant operational visibility"),
    
    # Industrial Ontology Architecture (Prompt 11)
    Permission(permission_id="ontology.read", resource="ontology", action="read", description="View canonical entities, relationships, external IDs, and taxonomy"),
    Permission(permission_id="ontology.manage", resource="ontology", action="manage", description="Create, update, and manage canonical entities, relationships, and external mappings", is_sensitive=True),

    # Operational Knowledge Graph Architecture (Prompt 12)
    Permission(permission_id="knowledge_graph.read", resource="knowledge_graph", action="read", description="View operational knowledge graph facts, context, neighbors, history, and traversals"),
    Permission(permission_id="knowledge_graph.manage", resource="knowledge_graph", action="manage", description="Create, update, ingest, and manage operational knowledge graph facts and edges", is_sensitive=True),

    # Digital Twin Architecture (Prompt 13)
    Permission(permission_id="digital_twin.read", resource="digital_twin", action="read", description="View Digital Twin entity state, history, snapshots, and scenarios"),
    Permission(permission_id="digital_twin.manage", resource="digital_twin", action="manage", description="Ingest state, create snapshots, and manage Digital Twin entities", is_sensitive=True),
    Permission(permission_id="digital_twin.scenario", resource="digital_twin", action="scenario", description="Create and manage simulation scenarios"),

    # Data Quality Engine (Prompt 14)
    Permission(permission_id="data_quality.read", resource="data_quality", action="read", description="View data quality rules, issues, and assessments"),
    Permission(permission_id="data_quality.assess", resource="data_quality", action="assess", description="Trigger deterministic data quality assessments"),
    Permission(permission_id="data_quality.manage", resource="data_quality", action="manage", description="Create and manage data quality rules", is_sensitive=True),

    # Incident Management Architecture (Prompt 18)
    Permission(permission_id="incidents.read", resource="incidents", action="read", description="View operational incidents, timelines, evidence, and notes"),
    Permission(permission_id="incidents.create", resource="incidents", action="create", description="Create new operational incident records"),
    Permission(permission_id="incidents.update", resource="incidents", action="update", description="Update incident metadata (severity, priority) and associate events"),
    Permission(permission_id="incidents.assign", resource="incidents", action="assign", description="Assign or reassign incident owners and teams"),
    Permission(permission_id="incidents.acknowledge", resource="incidents", action="acknowledge", description="Acknowledge operational incidents"),
    Permission(permission_id="incidents.transition", resource="incidents", action="transition", description="Transition incident lifecycle states"),
    Permission(permission_id="incidents.evidence.write", resource="incidents", action="evidence.write", description="Attach evidence references to incidents"),
    Permission(permission_id="incidents.notes.write", resource="incidents", action="notes.write", description="Add operator notes to incidents"),
    Permission(permission_id="incidents.admin", resource="incidents", action="admin", description="Full administrative authority over incidents", is_sensitive=True),

    # Root-Cause Analysis Foundation (Prompt 19)
    Permission(permission_id="rca.read", resource="rca", action="read", description="View Root-Cause Analysis candidates, evidence, and deterministic reasoning traces"),
    Permission(permission_id="rca.analyze", resource="rca", action="analyze", description="Trigger deterministic Root-Cause Analysis for an incident"),
    Permission(permission_id="rca.admin", resource="rca", action="admin", description="Full administrative authority over RCA rules and settings", is_sensitive=True),

    # System Administration (Strictly Non-Operational)
    Permission(permission_id="user.manage", resource="user", action="manage", description="Create, update, or suspend user identities", is_sensitive=True),
    Permission(permission_id="system.config", resource="system", action="config", description="Configure platform infrastructure and endpoints", is_sensitive=True),
    Permission(permission_id="tenant.admin", resource="tenant", action="admin", description="Tenant configuration and quota administration", is_sensitive=True),
    Permission(permission_id="role.assign", resource="role", action="assign", description="Assign roles to identities", is_sensitive=True),
    Permission(permission_id="role.manage", resource="role", action="manage", description="Define or modify role permission templates", is_sensitive=True),
]


class PermissionRegistry:
    """Registry maintaining canonical system permissions."""

    def __init__(self):
        self._permissions: Dict[str, Permission] = {
            p.permission_id: p for p in CANONICAL_PERMISSIONS
        }

    def get_permission(self, permission_id: str) -> Optional[Permission]:
        return self._permissions.get(permission_id.strip().lower())

    def list_permissions(self) -> List[Permission]:
        return list(self._permissions.values())

    def is_valid(self, permission_id: str) -> bool:
        return permission_id.strip().lower() in self._permissions


# =====================================================================
# 2. CANONICAL SYSTEM ROLES & PERSISTENT ROLE REGISTRY
# =====================================================================

SYSTEM_ROLES: List[Role] = [
    Role(
        role_id="VIEWER",
        name="Viewer",
        scope_type=RoleScopeType.SYSTEM,
        permissions=["telemetry.read", "database.read", "action.read", "policy.read", "transaction.read", "ontology.read", "knowledge_graph.read", "digital_twin.read", "data_quality.read", "incidents.read", "rca.read"],
        inherits_from=[],
        description="Read-only observer access to telemetry, action states, and policy rules.",
        is_system_role=True
    ),
    Role(
        role_id="ANALYST",
        name="Analyst",
        scope_type=RoleScopeType.SYSTEM,
        permissions=["sql.analyze", "action.simulate", "transaction.validate", "digital_twin.scenario", "data_quality.assess"],
        inherits_from=["VIEWER"],
        description="Analytical access including query analysis, simulation preview, and data exploration.",
        is_system_role=True
    ),
    Role(
        role_id="OPERATOR",
        name="Operator",
        scope_type=RoleScopeType.PLANT,
        permissions=[
            "action.create", "action.cancel", "production.propose", "machine.status.read",
            "transaction.plan", "transaction.cancel", "action.execute", "transaction.execute",
            "incidents.create", "incidents.acknowledge", "incidents.transition", "incidents.update",
            "incidents.assign", "incidents.evidence.write", "incidents.notes.write", "rca.analyze"
        ],
        inherits_from=["ANALYST"],
        description="Line operator authorized to propose and execute structured operational actions on assigned plant lines.",
        is_system_role=True
    ),
    Role(
        role_id="MAINTENANCE_ENGINEER",
        name="Maintenance Engineer",
        scope_type=RoleScopeType.PLANT,
        permissions=["maintenance.propose", "setpoint.adjust"],
        inherits_from=["OPERATOR"],
        description="Maintenance specialist capable of proposing maintenance holds and machine setpoint adjustments.",
        is_system_role=True
    ),
    Role(
        role_id="SUPPLY_CHAIN_MANAGER",
        name="Supply Chain Manager",
        scope_type=RoleScopeType.TENANT,
        permissions=["inventory.adjust", "order.expedite"],
        inherits_from=["ANALYST"],
        description="Logistics and supply chain authority over inventory adjustments and order expediting.",
        is_system_role=True
    ),
    Role(
        role_id="SAFETY_MANAGER",
        name="Safety Manager",
        scope_type=RoleScopeType.SYSTEM,
        permissions=["safety.hold", "emergency.declare", "audit.read", "transaction.rollback"],
        inherits_from=["VIEWER"],
        description="Safety officer with immediate authority to declare safety holds, emergency stops, and emergency rollback.",
        is_system_role=True
    ),
    Role(
        role_id="PLANT_MANAGER",
        name="Plant Manager",
        scope_type=RoleScopeType.PLANT,
        permissions=["action.approve", "production.schedule", "transaction.rollback", "ontology.manage", "knowledge_graph.manage", "digital_twin.manage", "data_quality.manage", "incidents.admin", "rca.admin"],
        inherits_from=["OPERATOR", "SAFETY_MANAGER", "SUPPLY_CHAIN_MANAGER"],
        description="Senior plant authority responsible for approving high-risk actions, production schedules, and transaction rollbacks.",
        is_system_role=True
    ),
    Role(
        role_id="EXECUTIVE",
        name="Executive",
        scope_type=RoleScopeType.SYSTEM,
        permissions=["report.generate", "enterprise.view", "audit.read"],
        inherits_from=["VIEWER"],
        description="Enterprise oversight with cross-plant visibility and executive audit reporting.",
        is_system_role=True
    ),
    Role(
        role_id="ADMINISTRATOR",
        name="System Administrator",
        scope_type=RoleScopeType.SYSTEM,
        permissions=[
            "user.manage", "system.config", "tenant.admin", "role.assign",
            "database.connection.create", "database.connection.admin", "ontology.manage", "knowledge_graph.manage", "digital_twin.manage", "data_quality.manage", "incidents.admin", "rca.admin"
        ],
        inherits_from=["VIEWER"],
        description="Platform administrator. Strictly non-operational; cannot propose or approve factory actions.",
        is_system_role=True
    ),
    Role(
        role_id="SECURITY_ADMIN",
        name="Security Administrator",
        scope_type=RoleScopeType.SYSTEM,
        permissions=["policy.manage", "security.audit", "role.manage", "audit.read", "data_quality.manage", "incidents.admin"],
        inherits_from=["VIEWER"],
        description="Security and governance officer responsible for policy rules and authorization role definitions.",
        is_system_role=True
    )
]


class RoleRegistry:
    """
    Persistent Role Repository with In-Memory Write-Through Cache.
    Guarantees cycle-free inheritance resolution and SQLite durability.
    """

    def __init__(self, db_path: str = MEMORY_DB_PATH):
        self._lock = threading.RLock()
        self._db_path = db_path
        self._roles: Dict[str, Role] = {}
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes SQLite roles_v3 schema and seeds default system roles."""
        try:
            with self._lock:
                conn = self._get_connection()
                try:
                    with conn:
                        conn.execute("""
                            CREATE TABLE IF NOT EXISTS roles_v3 (
                                role_id TEXT PRIMARY KEY,
                                name TEXT NOT NULL,
                                scope_type TEXT NOT NULL,
                                permissions TEXT NOT NULL,
                                inherits_from TEXT NOT NULL,
                                description TEXT,
                                is_system_role INTEGER NOT NULL
                            )
                        """)
                    
                    # Seed or update canonical roles
                    for role in SYSTEM_ROLES:
                        row = conn.execute("SELECT role_id, is_system_role FROM roles_v3 WHERE role_id = ?", (role.role_id,)).fetchone()
                        if not row:
                            with conn:
                                conn.execute("""
                                    INSERT INTO roles_v3 (role_id, name, scope_type, permissions, inherits_from, description, is_system_role)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    role.role_id,
                                    role.name,
                                    role.scope_type.value,
                                    json.dumps(role.permissions),
                                    json.dumps(role.inherits_from),
                                    role.description,
                                    1 if role.is_system_role else 0
                                ))
                        elif row["is_system_role"]:
                            with conn:
                                conn.execute("""
                                    UPDATE roles_v3 SET permissions = ?, inherits_from = ? WHERE role_id = ?
                                """, (
                                    json.dumps(role.permissions),
                                    json.dumps(role.inherits_from),
                                    role.role_id
                                ))

                    # Load all roles into in-memory cache
                    rows = conn.execute("SELECT * FROM roles_v3").fetchall()
                    for r in rows:
                        self._roles[r["role_id"]] = Role(
                            role_id=r["role_id"],
                            name=r["name"],
                            scope_type=RoleScopeType(r["scope_type"]),
                            permissions=json.loads(r["permissions"]),
                            inherits_from=json.loads(r["inherits_from"]),
                            description=r["description"] or "",
                            is_system_role=bool(r["is_system_role"])
                        )
                finally:
                    conn.close()
        except Exception as e:
            # Fallback to in-memory system roles if SQLite is inaccessible
            for r in SYSTEM_ROLES:
                self._roles[r.role_id] = r

    def get_role(self, role_id: str) -> Optional[Role]:
        with self._lock:
            return self._roles.get(role_id.strip().upper())

    def list_roles(self) -> List[Role]:
        with self._lock:
            return list(self._roles.values())

    def register_role(self, role: Role) -> Role:
        """Registers or updates a role after verifying acyclic inheritance."""
        with self._lock:
            # Test cycle detection before applying
            test_graph = {rid: r.inherits_from[:] for rid, r in self._roles.items()}
            test_graph[role.role_id] = role.inherits_from[:]
            self._check_cycles(test_graph)

            self._roles[role.role_id] = role

            # Persist to SQLite
            try:
                conn = self._get_connection()
                try:
                    with conn:
                        conn.execute("""
                            INSERT INTO roles_v3 (role_id, name, scope_type, permissions, inherits_from, description, is_system_role)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(role_id) DO UPDATE SET
                                name=excluded.name,
                                scope_type=excluded.scope_type,
                                permissions=excluded.permissions,
                                inherits_from=excluded.inherits_from,
                                description=excluded.description,
                                is_system_role=excluded.is_system_role
                        """, (
                            role.role_id,
                            role.name,
                            role.scope_type.value,
                            json.dumps(role.permissions),
                            json.dumps(role.inherits_from),
                            role.description,
                            1 if role.is_system_role else 0
                        ))
                finally:
                    conn.close()
            except Exception:
                pass
            return role

    def _check_cycles(self, graph: Dict[str, List[str]]):
        """Graph cycle detection via DFS."""
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str):
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    raise ValueError(f"Cycle detected in role inheritance hierarchy involving '{neighbor}'.")
            rec_stack.remove(node)

        for n in graph:
            if n not in visited:
                dfs(n)

    def resolve_effective_permissions(
        self,
        role_ids: List[str]
    ) -> Tuple[List[str], Dict[str, str]]:
        """
        Resolves transitive permissions across assigned roles.
        Returns (effective_permissions_list, permission_to_granting_role_map).
        Raises ValueError if circular inheritance is encountered.
        """
        with self._lock:
            # Build inheritance graph and check for cycles
            graph = {rid: r.inherits_from[:] for rid, r in self._roles.items()}
            self._check_cycles(graph)

            effective_perms: Set[str] = set()
            perm_to_role: Dict[str, str] = {}

            def traverse_role(rid: str, visited_roles: Set[str]):
                if rid in visited_roles:
                    return
                visited_roles.add(rid)
                role = self._roles.get(rid)
                if not role:
                    return
                for p in role.permissions:
                    p_norm = p.strip().lower()
                    effective_perms.add(p_norm)
                    if p_norm not in perm_to_role:
                        perm_to_role[p_norm] = rid
                for parent_rid in role.inherits_from:
                    traverse_role(parent_rid.strip().upper(), visited_roles)

            visited_roles: Set[str] = set()
            for r_id in role_ids:
                traverse_role(r_id.strip().upper(), visited_roles)

            return sorted(list(effective_perms)), perm_to_role


# =====================================================================
# 3. SCOPE MATCHER (HIERARCHICAL RESOURCE BOUNDARIES)
# =====================================================================

class ScopeMatcher:
    """Validates hierarchical tenant, workspace, plant, and equipment boundaries."""

    @staticmethod
    def check_scope(
        identity: UserIdentity,
        scope: AuthorizationScope
    ) -> Tuple[bool, Optional[AuthzReasonCode], str]:
        # 1. Tenant Isolation
        if identity.tenant_id != scope.tenant_id:
            return False, AuthzReasonCode.TENANT_MISMATCH, (
                f"Tenant mismatch: identity tenant '{identity.tenant_id}' cannot access resource tenant '{scope.tenant_id}'."
            )

        # 2. Workspace Isolation
        if scope.workspace_id and scope.workspace_id != "*":
            # Wildcard workspace or matching workspace required
            if identity.workspace_id != "*" and identity.workspace_id != scope.workspace_id:
                return False, AuthzReasonCode.WORKSPACE_MISMATCH, (
                    f"Workspace mismatch: identity workspace '{identity.workspace_id}' cannot access target workspace '{scope.workspace_id}'."
                )

        # 3. Plant Scope (Hierarchical containment)
        if scope.plant_id:
            user_plants = identity.assigned_plants or []
            if "*" not in user_plants and scope.plant_id not in user_plants:
                return False, AuthzReasonCode.PLANT_SCOPE_DENIED, (
                    f"Plant access denied: user '{identity.user_id}' is assigned to {user_plants}, but operation targets plant '{scope.plant_id}'."
                )

        return True, None, "Scope validated successfully."


# =====================================================================
# 4. AUTHORIZATION SERVICE (RBAC + ABAC EVALUATION ENGINE)
# =====================================================================

class AuthorizationService:
    """
    Production Authorization Service.
    Deterministically evaluates incoming authorization requests combining:
    - User account lifecycle status
    - Hierarchical scope containment (Tenant -> Workspace -> Plant)
    - Separation of duties (Proposer != Approver)
    - Security clearance levels
    - Operational write protection against non-operational administrative roles
    - Acyclic RBAC permission resolution
    """

    def __init__(
        self,
        permission_registry: Optional[PermissionRegistry] = None,
        role_registry: Optional[RoleRegistry] = None
    ):
        self.permission_registry = permission_registry or PermissionRegistry()
        self.role_registry = role_registry or RoleRegistry()
        self.scope_matcher = ScopeMatcher()

    def evaluate(self, context: AuthorizationContext) -> AuthorizationDecision:
        """
        Evaluates AuthorizationContext and returns a tamper-evident AuthorizationDecision.
        Follows strict fail-closed evaluation.
        """
        try:
            req_perm = context.required_permission.strip().lower()
            identity = context.identity
            scope = context.scope

            # Rule 1: Identity Active Status Check
            if identity.status != UserStatus.ACTIVE:
                return AuthorizationDecision.create(
                    effect=AuthzDecisionEffect.DENY,
                    reason_code=AuthzReasonCode.IDENTITY_NOT_ACTIVE,
                    reason=f"Identity '{identity.user_id}' account status is '{identity.status.value}'. Only ACTIVE identities are authorized.",
                    required_permission=req_perm
                )

            # Rule 2: Scope Containment (Tenant, Workspace, Plant)
            scope_ok, scope_err_code, scope_msg = self.scope_matcher.check_scope(identity, scope)
            if not scope_ok:
                return AuthorizationDecision.create(
                    effect=AuthzDecisionEffect.DENY,
                    reason_code=scope_err_code or AuthzReasonCode.TENANT_MISMATCH,
                    reason=scope_msg,
                    required_permission=req_perm
                )

            # Rule 3: Separation of Duties (Approver != Proposer)
            if req_perm == "action.approve" or "approve" in req_perm:
                if context.proposer_id and context.proposer_id == identity.user_id:
                    return AuthorizationDecision.create(
                        effect=AuthzDecisionEffect.DENY,
                        reason_code=AuthzReasonCode.SEPARATION_OF_DUTIES_VIOLATION,
                        reason=f"Separation of duties violation: user '{identity.user_id}' proposed action '{context.action_id or 'UNKNOWN'}' and cannot approve it.",
                        required_permission=req_perm
                    )

            # Rule 4: Clearance Level Attribute Check (ABAC)
            if identity.clearance_level < context.required_clearance:
                return AuthorizationDecision.create(
                    effect=AuthzDecisionEffect.DENY,
                    reason_code=AuthzReasonCode.CLEARANCE_LEVEL_INSUFFICIENT,
                    reason=f"Identity clearance level {identity.clearance_level} is lower than required clearance {context.required_clearance}.",
                    required_permission=req_perm
                )

            # Rule 5: Data Mode Guard (ABAC)
            # Mutating operations are disallowed in HISTORICAL mode
            mutating_prefixes = ["action.create", "action.approve", "production.", "setpoint.", "inventory."]
            if context.data_mode.upper() == "HISTORICAL" and any(req_perm.startswith(p) for p in mutating_prefixes):
                return AuthorizationDecision.create(
                    effect=AuthzDecisionEffect.DENY,
                    reason_code=AuthzReasonCode.DATA_MODE_RESTRICTED,
                    reason=f"Capability '{req_perm}' is disallowed in HISTORICAL data mode.",
                    required_permission=req_perm
                )

            # Rule 6: RBAC Role & Effective Permission Resolution
            try:
                effective_perms, perm_to_role = self.role_registry.resolve_effective_permissions(identity.roles)
            except ValueError as cycle_err:
                return AuthorizationDecision.create(
                    effect=AuthzDecisionEffect.DENY,
                    reason_code=AuthzReasonCode.CYCLE_DETECTED,
                    reason=str(cycle_err),
                    required_permission=req_perm
                )

            # Rule 7: Privileged Operation Protection
            # Administrators and Security Admins strictly do NOT have operational write authority
            operational_actions = {"action.create", "production.propose", "setpoint.adjust", "action.approve"}
            if req_perm in operational_actions:
                has_admin_role = any(r.upper() in {"ADMINISTRATOR", "SECURITY_ADMIN"} for r in identity.roles)
                has_op_role = any(r.upper() in {"OPERATOR", "MAINTENANCE_ENGINEER", "PLANT_MANAGER", "SUPPLY_CHAIN_MANAGER"} for r in identity.roles)
                if has_admin_role and not has_op_role:
                    return AuthorizationDecision.create(
                        effect=AuthzDecisionEffect.DENY,
                        reason_code=AuthzReasonCode.ADMIN_OPERATIONAL_OVERRIDE_DISALLOWED,
                        reason=f"Administrative roles {identity.roles} lack operational execution authority for '{req_perm}'.",
                        required_permission=req_perm,
                        resolved_permissions=effective_perms
                    )

            # Rule 8: Permission Match Check
            if req_perm in effective_perms:
                granting_role = perm_to_role.get(req_perm)
                decision = AuthorizationDecision.create(
                    effect=AuthzDecisionEffect.ALLOW,
                    reason_code=AuthzReasonCode.ALLOWED,
                    reason=f"Access granted for capability '{req_perm}' via role '{granting_role}'.",
                    required_permission=req_perm,
                    matched_role=granting_role,
                    resolved_permissions=effective_perms
                )
            else:
                decision = AuthorizationDecision.create(
                    effect=AuthzDecisionEffect.DENY,
                    reason_code=AuthzReasonCode.INSUFFICIENT_ROLE_PERMISSIONS,
                    reason=f"User '{identity.user_id}' with roles {identity.roles} lacks required capability '{req_perm}'.",
                    required_permission=req_perm,
                    resolved_permissions=effective_perms
                )

            # Audit Logging for security visibility
            log_security_event(
                event_name="AUTHORIZATION_EVALUATION",
                user_id=identity.user_id,
                details={
                    "decision_id": decision.decision_id,
                    "effect": decision.effect.value,
                    "reason_code": decision.reason_code.value,
                    "permission": req_perm,
                    "scope_tenant": scope.tenant_id,
                    "scope_plant": scope.plant_id,
                    "decision_hash": decision.decision_hash
                }
            )

            return decision

        except Exception as ex:
            # Absolute Fail-Closed Catch-All
            return AuthorizationDecision.create(
                effect=AuthzDecisionEffect.DENY,
                reason_code=AuthzReasonCode.EVALUATION_ERROR,
                reason=f"Internal authorization evaluation error: {str(ex)}",
                required_permission=context.required_permission
            )


# Global Singleton Instance
authorization_service = AuthorizationService()
