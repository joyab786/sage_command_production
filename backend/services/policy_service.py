# backend/services/policy_service.py
"""
SageCommand V3 — Deterministic Policy Enforcement Engine & Registry Service
Implements canonical policy evaluation, deterministic condition checks,
strict precedence (DENY > REQUIRE_APPROVAL > HOLD > ALLOW), conflict detection,
SQLite persistence for versioned policies, and audit logging.

Crucial Rule: LLMs reason. Deterministic systems enforce.
Policy evaluation never executes actions and creates zero operational side effects.
"""

import os
import re
import json
import sqlite3
import threading
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Set, Any
from collections import OrderedDict

try:
    from core.config import MEMORY_DB_PATH
    from governance.audit import log_security_event
    from data.schemas.action_contract import Action, ActionStatus, RiskLevel
    from data.schemas.policy_contract import (
        Policy,
        PolicyRule,
        PolicyCondition,
        PolicyEffect,
        PolicyLifecycle,
        PolicyConditionCategory,
        PolicyOperator,
        PolicyReasonCode,
        ApprovalRequirement,
        PolicyEvaluationContext,
        PolicyEvaluationTrace,
        PolicyDecision,
    )
    from services.action_store import action_store
except ModuleNotFoundError:
    from backend.core.config import MEMORY_DB_PATH
    from backend.governance.audit import log_security_event
    from backend.data.schemas.action_contract import Action, ActionStatus, RiskLevel
    from backend.data.schemas.policy_contract import (
        Policy,
        PolicyRule,
        PolicyCondition,
        PolicyEffect,
        PolicyLifecycle,
        PolicyConditionCategory,
        PolicyOperator,
        PolicyReasonCode,
        ApprovalRequirement,
        PolicyEvaluationContext,
        PolicyEvaluationTrace,
        PolicyDecision,
    )
    from backend.services.action_store import action_store


# =====================================================================
# 1. DETERMINISTIC CONDITION EVALUATOR
# =====================================================================

class PolicyConditionEvaluator:
    """
    Evaluates individual policy conditions against server-extracted action attributes.
    Zero use of eval(), exec(), or arbitrary string interpretation.
    """

    @staticmethod
    def extract_field_value(
        action: Action,
        context: PolicyEvaluationContext,
        field: PolicyConditionCategory
    ) -> Any:
        """Extracts trustworthy server-side attribute for evaluation."""
        if field == PolicyConditionCategory.ACTION_TYPE:
            return action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        
        elif field == PolicyConditionCategory.ACTION_VERSION:
            return str(action.version)
        
        elif field == PolicyConditionCategory.RISK_LEVEL:
            # AUTHORITATIVE: Never use model_estimated_risk! Always system_risk_level!
            return action.system_risk_level.value if hasattr(action.system_risk_level, "value") else str(action.system_risk_level)
        
        elif field == PolicyConditionCategory.RESOURCE_TYPE:
            return action.target.resource_type.value if hasattr(action.target.resource_type, "value") else str(action.target.resource_type)
        
        elif field == PolicyConditionCategory.RESOURCE_ID:
            return str(action.target.resource_id)
        
        elif field == PolicyConditionCategory.PLANT:
            return action.target.plant_id or context.plant_id
        
        elif field == PolicyConditionCategory.WORKSPACE:
            return action.workspace_id or context.workspace_id
        
        elif field == PolicyConditionCategory.TENANT:
            return action.tenant_id or context.tenant_id
        
        elif field == PolicyConditionCategory.DATA_MODE:
            return action.data_mode.upper() if action.data_mode else "REAL"
        
        elif field == PolicyConditionCategory.ACCESS_MODE:
            return context.resource_metadata.get("access_mode", "READ_WRITE")
        
        elif field == PolicyConditionCategory.USER_SCOPE:
            return context.user_id
        
        elif field == PolicyConditionCategory.MISSION:
            return action.mission_id
        
        elif field == PolicyConditionCategory.INCIDENT:
            return action.incident_id
        
        elif field == PolicyConditionCategory.ESTIMATED_COST:
            if action.estimated_cost and action.estimated_cost.value is not None:
                val = float(action.estimated_cost.value)
                if not math.isnan(val) and not math.isinf(val):
                    return val
            return None
        
        elif field == PolicyConditionCategory.ESTIMATED_DURATION:
            return action.estimated_duration_minutes
        
        elif field == PolicyConditionCategory.TIME_WINDOW:
            return context.current_time
        
        elif field == PolicyConditionCategory.DAY_OF_WEEK:
            if context.day_of_week:
                return context.day_of_week.upper()
            try:
                clean_time = context.current_time.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_time)
                return dt.strftime("%A").upper()
            except Exception:
                return None
        
        elif field == PolicyConditionCategory.APPROVAL_REQUIRED:
            return bool(action.requires_approval)
        
        elif field == PolicyConditionCategory.ROLLBACK_SUPPORT:
            return action.rollback_supported.value if hasattr(action.rollback_supported, "value") else str(action.rollback_supported)
        
        elif field == PolicyConditionCategory.CAPABILITY:
            return context.resource_metadata.get("capabilities", [])
        
        return None

    @classmethod
    def evaluate_condition(
        cls,
        condition: PolicyCondition,
        action: Action,
        context: PolicyEvaluationContext
    ) -> bool:
        """Evaluates a single condition deterministically. Fails closed (False) on missing/invalid data."""
        actual = cls.extract_field_value(action, context, condition.field)
        expected = condition.value
        op = condition.operator

        try:
            if op == PolicyOperator.EXISTS:
                return actual is not None

            if op == PolicyOperator.NOT_EXISTS:
                return actual is None

            # For all other operators, if actual is None, condition does not match
            if actual is None:
                return False

            if op == PolicyOperator.EQUALS:
                return str(actual).strip().lower() == str(expected).strip().lower()

            if op == PolicyOperator.NOT_EQUALS:
                return str(actual).strip().lower() != str(expected).strip().lower()

            if op == PolicyOperator.IN:
                if isinstance(expected, (list, tuple, set)):
                    exp_set = {str(x).strip().lower() for x in expected}
                    return str(actual).strip().lower() in exp_set
                return str(actual).strip().lower() == str(expected).strip().lower()

            if op == PolicyOperator.NOT_IN:
                if isinstance(expected, (list, tuple, set)):
                    exp_set = {str(x).strip().lower() for x in expected}
                    return str(actual).strip().lower() not in exp_set
                return str(actual).strip().lower() != str(expected).strip().lower()

            if op in (
                PolicyOperator.GREATER_THAN,
                PolicyOperator.GREATER_THAN_OR_EQUAL,
                PolicyOperator.LESS_THAN,
                PolicyOperator.LESS_THAN_OR_EQUAL,
            ):
                num_actual = float(actual)
                num_expected = float(expected)
                if math.isnan(num_actual) or math.isnan(num_expected) or math.isinf(num_actual) or math.isinf(num_expected):
                    return False

                if op == PolicyOperator.GREATER_THAN:
                    return num_actual > num_expected
                if op == PolicyOperator.GREATER_THAN_OR_EQUAL:
                    return num_actual >= num_expected
                if op == PolicyOperator.LESS_THAN:
                    return num_actual < num_expected
                if op == PolicyOperator.LESS_THAN_OR_EQUAL:
                    return num_actual <= num_expected

            if op == PolicyOperator.CONTAINS:
                if isinstance(actual, (list, tuple, set)):
                    return expected in actual or str(expected).lower() in [str(x).lower() for x in actual]
                return str(expected).lower() in str(actual).lower()

            if op == PolicyOperator.NOT_CONTAINS:
                if isinstance(actual, (list, tuple, set)):
                    return expected not in actual and str(expected).lower() not in [str(x).lower() for x in actual]
                return str(expected).lower() not in str(actual).lower()

            if op == PolicyOperator.MATCHES_SCOPE:
                if isinstance(expected, dict):
                    for k, v in expected.items():
                        if k == "tenant_id" and action.tenant_id != v:
                            return False
                        if k == "plant_id" and (action.target.plant_id != v and context.plant_id != v):
                            return False
                        if k == "workspace_id" and action.workspace_id != v:
                            return False
                    return True
                return str(actual).lower() == str(expected).lower()

            if op == PolicyOperator.WITHIN_TIME_WINDOW:
                # Format: "09:00-18:00"
                if isinstance(expected, str) and "-" in expected:
                    start_str, end_str = expected.split("-")
                    # Parse current hour & minute from actual (ISO-8601)
                    clean_time = str(actual).replace("Z", "+00:00")
                    dt = datetime.fromisoformat(clean_time)
                    act_time = dt.strftime("%H:%M")
                    return start_str.strip() <= act_time <= end_str.strip()
                return False

        except Exception:
            # Deterministic fail closed
            return False

        return False


# =====================================================================
# 2. PERSISTENT POLICY REPOSITORY (SQLITE + WRITE-THROUGH CACHE)
# =====================================================================

class PolicyStore:
    """
    SQLite-backed versioned Policy Repository.
    Guarantees policies and historical decisions survive process restarts.
    """

    def __init__(self, db_path: str = MEMORY_DB_PATH):
        self._lock = threading.RLock()
        self._db_path = db_path
        self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False) if db_path == ":memory:" else None
        if self._mem_conn:
            self._mem_conn.row_factory = sqlite3.Row
        # Cache keyed by "policy_id:version"
        self._policies: Dict[str, Policy] = OrderedDict()
        self._init_db()
        self._load_all_active()

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_conn:
            return self._mem_conn
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _close_connection(self, conn: sqlite3.Connection):
        if conn != self._mem_conn:
            conn.close()

    def _init_db(self):
        """Initializes tables for policies and decisions."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS policies_v3 (
                            policy_id TEXT NOT NULL,
                            policy_version TEXT NOT NULL,
                            name TEXT NOT NULL,
                            description TEXT NOT NULL,
                            status TEXT NOT NULL,
                            priority INTEGER NOT NULL,
                            scope_json TEXT NOT NULL,
                            rules_json TEXT NOT NULL,
                            policy_hash TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            created_by TEXT NOT NULL,
                            PRIMARY KEY (policy_id, policy_version)
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_policies_status ON policies_v3(status)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_policies_priority ON policies_v3(priority DESC)")

                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS policy_decisions_v3 (
                            decision_id TEXT PRIMARY KEY,
                            action_id TEXT NOT NULL,
                            decision TEXT NOT NULL,
                            policy_id TEXT,
                            policy_version TEXT,
                            tenant_id TEXT NOT NULL,
                            reason_codes_json TEXT NOT NULL,
                            explanation TEXT NOT NULL,
                            risk_level TEXT NOT NULL,
                            requires_approval INTEGER NOT NULL,
                            decision_hash TEXT NOT NULL,
                            evaluated_at TEXT NOT NULL,
                            full_decision_json TEXT NOT NULL
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_action ON policy_decisions_v3(action_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_tenant ON policy_decisions_v3(tenant_id)")
            finally:
                self._close_connection(conn)

    def _load_all_active(self):
        """Loads all policies from SQLite into memory cache on startup."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM policies_v3 ORDER BY priority DESC")
                rows = cursor.fetchall()
                for row in rows:
                    p = self._row_to_policy(row)
                    key = f"{p.policy_id}:{p.policy_version}"
                    self._policies[key] = p
            finally:
                self._close_connection(conn)

    def _row_to_policy(self, row: sqlite3.Row) -> Policy:
        scope = json.loads(row["scope_json"])
        raw_rules = json.loads(row["rules_json"])
        rules = [PolicyRule(**r) for r in raw_rules]
        return Policy(
            policy_id=row["policy_id"],
            policy_version=row["policy_version"],
            name=row["name"],
            description=row["description"],
            status=PolicyLifecycle(row["status"]),
            priority=row["priority"],
            scope=scope,
            rules=rules,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row["created_by"],
            policy_hash=row["policy_hash"]
        )

    def save_policy(self, policy: Policy) -> Policy:
        """Persists or updates a versioned policy definition."""
        with self._lock:
            key = f"{policy.policy_id}:{policy.policy_version}"
            policy.policy_hash = policy.compute_hash()
            self._policies[key] = policy

            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO policies_v3 (
                            policy_id, policy_version, name, description, status,
                            priority, scope_json, rules_json, policy_hash,
                            created_at, updated_at, created_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        policy.policy_id,
                        policy.policy_version,
                        policy.name,
                        policy.description,
                        policy.status.value,
                        policy.priority,
                        json.dumps(policy.scope),
                        json.dumps([r.model_dump() for r in policy.rules]),
                        policy.policy_hash,
                        policy.created_at,
                        policy.updated_at,
                        policy.created_by
                    ))
            finally:
                self._close_connection(conn)

            return policy

    def get_policy(self, policy_id: str, version: Optional[str] = None) -> Optional[Policy]:
        """Retrieves policy by ID and optional version. Defaults to highest semantic version."""
        with self._lock:
            if version:
                key = f"{policy_id}:{version}"
                return self._policies.get(key)
            
            # Find matching policies for this ID, sort by version descending
            matching = [p for p in self._policies.values() if p.policy_id == policy_id]
            if matching:
                matching.sort(key=lambda x: x.policy_version, reverse=True)
                return matching[0]
            return None

    def list_policies(
        self,
        tenant_id: Optional[str] = None,
        active_only: bool = True
    ) -> List[Policy]:
        """Lists policies filtered by tenant scope and active lifecycle status."""
        with self._lock:
            result = []
            for p in self._policies.values():
                if active_only and p.status != PolicyLifecycle.ACTIVE:
                    continue
                # Tenant scope filtering: global policies (no tenant_id in scope) or tenant matching
                p_tenant = p.scope.get("tenant_id")
                if p_tenant and tenant_id and p_tenant != tenant_id:
                    continue
                result.append(p)
            result.sort(key=lambda x: x.priority, reverse=True)
            return result

    def save_decision(self, decision: PolicyDecision) -> PolicyDecision:
        """Persists a canonical PolicyDecision for ledger and audit reconstructability."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO policy_decisions_v3 (
                            decision_id, action_id, decision, policy_id, policy_version,
                            tenant_id, reason_codes_json, explanation, risk_level,
                            requires_approval, decision_hash, evaluated_at, full_decision_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        decision.decision_id,
                        decision.action_id,
                        decision.decision.value,
                        decision.policy_id,
                        decision.policy_version,
                        decision.tenant_id,
                        json.dumps(decision.reason_codes),
                        decision.explanation,
                        decision.risk_level,
                        1 if decision.requires_approval else 0,
                        decision.decision_hash or decision.compute_hash(),
                        decision.evaluated_at,
                        json.dumps(decision.model_dump())
                    ))
            finally:
                self._close_connection(conn)
            return decision

    def get_decision(self, decision_id: str) -> Optional[PolicyDecision]:
        """Retrieves a historical policy decision by ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT full_decision_json FROM policy_decisions_v3 WHERE decision_id = ?", (decision_id,))
                row = cursor.fetchone()
                if row:
                    data = json.loads(row["full_decision_json"])
                    return PolicyDecision(**data)
                return None
            finally:
                self._close_connection(conn)


# =====================================================================
# 3. CANONICAL POLICY ENFORCEMENT SERVICE
# =====================================================================

class PolicyService:
    """
    Deterministic Policy Enforcement Engine.
    Executes authoritative policy evaluation, precedence resolution, conflict detection,
    and lifecycle coordination without executing operational actions.
    """

    def __init__(self, store: Optional[PolicyStore] = None):
        self.store = store or PolicyStore()
        self._bootstrap_default_policies()

    def _bootstrap_default_policies(self):
        """Initializes canonical industrial policies in the store if not already present."""
        # 1. Plant Shutdown Block Policy (Priority 100 - Highest)
        if not self.store.get_policy("POL-DEFAULT-SHUTDOWN-DENY", "1.0"):
            self.store.save_policy(Policy(
                policy_id="POL-DEFAULT-SHUTDOWN-DENY",
                policy_version="1.0",
                name="Plant Shutdown Operational Freeze",
                description="Strictly blocks all operational mutations during scheduled plant maintenance shutdown.",
                priority=100,
                scope={},
                rules=[
                    PolicyRule(
                        rule_id="rule_shutdown_block",
                        name="Prohibit Changes During Shutdown",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.RESOURCE_ID,
                                operator=PolicyOperator.CONTAINS,
                                value="SHUTDOWN"
                            )
                        ],
                        effect=PolicyEffect.DENY,
                        reason_code=PolicyReasonCode.POLICY_DENIED.value,
                        explanation="Operational actions are strictly prohibited during plant shutdown or maintenance hold."
                    ),
                    PolicyRule(
                        rule_id="rule_incident_shutdown",
                        name="Freeze Under Shutdown Incident",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.INCIDENT,
                                operator=PolicyOperator.EQUALS,
                                value="PLANT_SHUTDOWN"
                            )
                        ],
                        effect=PolicyEffect.DENY,
                        reason_code=PolicyReasonCode.POLICY_DENIED.value,
                        explanation="Active incident PLANT_SHUTDOWN blocks autonomous operational modifications."
                    )
                ]
            ))

        # 2. Critical Line Approval Policy (Priority 85)
        if not self.store.get_policy("POL-CRITICAL-LINE-APPROVAL", "1.0"):
            self.store.save_policy(Policy(
                policy_id="POL-CRITICAL-LINE-APPROVAL",
                policy_version="1.0",
                name="Critical Line Production Governance",
                description="Requires supervisor/manager authorization for changes affecting critical manufacturing lines.",
                priority=85,
                scope={},
                rules=[
                    PolicyRule(
                        rule_id="rule_critical_line_approval",
                        name="Critical Production Line Authorization Gate",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.ACTION_TYPE,
                                operator=PolicyOperator.IN,
                                value=["CHANGE_PRODUCTION_PLAN", "RESCHEDULE_PRODUCTION"]
                            ),
                            PolicyCondition(
                                field=PolicyConditionCategory.RESOURCE_ID,
                                operator=PolicyOperator.CONTAINS,
                                value="CRITICAL"
                            )
                        ],
                        effect=PolicyEffect.REQUIRE_APPROVAL,
                        approval_requirement=ApprovalRequirement(
                            required=True,
                            approval_type="MANAGER",
                            required_role="manager",
                            minimum_approvers=1,
                            reason_code=PolicyReasonCode.POLICY_APPROVAL_REQUIRED.value,
                            reason="Production modifications affecting critical manufacturing lines require manager clearance.",
                            policy_id="POL-CRITICAL-LINE-APPROVAL",
                            policy_version="1.0"
                        ),
                        reason_code=PolicyReasonCode.POLICY_APPROVAL_REQUIRED.value,
                        explanation="Critical line changes require verified human authorization."
                    )
                ]
            ))

        # 3. High Cost Financial Approval Policy (Priority 80)
        if not self.store.get_policy("POL-HIGH-COST-APPROVAL", "1.0"):
            self.store.save_policy(Policy(
                policy_id="POL-HIGH-COST-APPROVAL",
                policy_version="1.0",
                name="Expenditure Threshold Governance",
                description="Enforces tiered approval hierarchy based on financial impact ($10,000 / $50,000 thresholds).",
                priority=80,
                scope={},
                rules=[
                    PolicyRule(
                        rule_id="rule_executive_cost_gate",
                        name="Executive Cost Authorization Gate",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.ESTIMATED_COST,
                                operator=PolicyOperator.GREATER_THAN_OR_EQUAL,
                                value=50000.0
                            )
                        ],
                        effect=PolicyEffect.REQUIRE_APPROVAL,
                        approval_requirement=ApprovalRequirement(
                            required=True,
                            approval_type="EXECUTIVE",
                            required_role="executive",
                            minimum_approvers=1,
                            reason_code=PolicyReasonCode.POLICY_COST_LIMIT_EXCEEDED.value,
                            reason="Estimated financial impact >= $50,000 requires Executive Committee sign-off.",
                            policy_id="POL-HIGH-COST-APPROVAL",
                            policy_version="1.0"
                        ),
                        reason_code=PolicyReasonCode.POLICY_COST_LIMIT_EXCEEDED.value,
                        explanation="High financial commitment (>= $50,000) mandates executive level approval."
                    ),
                    PolicyRule(
                        rule_id="rule_manager_cost_gate",
                        name="Manager Cost Authorization Gate",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.ESTIMATED_COST,
                                operator=PolicyOperator.GREATER_THAN_OR_EQUAL,
                                value=10000.0
                            ),
                            PolicyCondition(
                                field=PolicyConditionCategory.ESTIMATED_COST,
                                operator=PolicyOperator.LESS_THAN,
                                value=50000.0
                            )
                        ],
                        effect=PolicyEffect.REQUIRE_APPROVAL,
                        approval_requirement=ApprovalRequirement(
                            required=True,
                            approval_type="MANAGER",
                            required_role="manager",
                            minimum_approvers=1,
                            reason_code=PolicyReasonCode.POLICY_COST_LIMIT_EXCEEDED.value,
                            reason="Estimated financial impact >= $10,000 requires Operations Manager clearance.",
                            policy_id="POL-HIGH-COST-APPROVAL",
                            policy_version="1.0"
                        ),
                        reason_code=PolicyReasonCode.POLICY_COST_LIMIT_EXCEEDED.value,
                        explanation="Financial commitment between $10,000 and $50,000 mandates manager authorization."
                    )
                ]
            ))

        # 4. System Risk Level Governance Policy (Priority 75)
        if not self.store.get_policy("POL-RISK-LEVEL-APPROVAL", "1.0"):
            self.store.save_policy(Policy(
                policy_id="POL-RISK-LEVEL-APPROVAL",
                policy_version="1.0",
                name="Deterministic Risk Governance Gate",
                description="Requires human authorization for any action classified with HIGH or CRITICAL system risk.",
                priority=75,
                scope={},
                rules=[
                    PolicyRule(
                        rule_id="rule_high_risk_gate",
                        name="High/Critical Risk Human In The Loop",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.RISK_LEVEL,
                                operator=PolicyOperator.IN,
                                value=["HIGH", "CRITICAL"]
                            )
                        ],
                        effect=PolicyEffect.REQUIRE_APPROVAL,
                        approval_requirement=ApprovalRequirement(
                            required=True,
                            approval_type="MANAGER",
                            required_role="manager",
                            minimum_approvers=1,
                            reason_code=PolicyReasonCode.POLICY_APPROVAL_REQUIRED.value,
                            reason="Actions with HIGH or CRITICAL system risk mandate human supervisor clearance.",
                            policy_id="POL-RISK-LEVEL-APPROVAL",
                            policy_version="1.0"
                        ),
                        reason_code=PolicyReasonCode.POLICY_APPROVAL_REQUIRED.value,
                        explanation="Authoritative system risk level requires human-in-the-loop governance sign-off."
                    )
                ]
            ))

        # 5. Simulation Sandbox Experimentation Policy (Priority 70)
        if not self.store.get_policy("POL-SIMULATION-ALLOW", "1.0"):
            self.store.save_policy(Policy(
                policy_id="POL-SIMULATION-ALLOW",
                policy_version="1.0",
                name="Simulation Sandbox Policy",
                description="Permits autonomous simulation exploration when operating in SIMULATION data mode.",
                priority=70,
                scope={},
                rules=[
                    PolicyRule(
                        rule_id="rule_sim_exploration",
                        name="Permit Safe Simulation Experimentation",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.DATA_MODE,
                                operator=PolicyOperator.EQUALS,
                                value="SIMULATION"
                            ),
                            PolicyCondition(
                                field=PolicyConditionCategory.RISK_LEVEL,
                                operator=PolicyOperator.EQUALS,
                                value="LOW"
                            )
                        ],
                        effect=PolicyEffect.ALLOW,
                        reason_code=PolicyReasonCode.POLICY_ALLOWED.value,
                        explanation="Autonomous simulation experimentation is permitted under safe parameters."
                    )
                ]
            ))

        # 6. Low-Risk Routine Reorder Policy (Priority 60)
        if not self.store.get_policy("POL-LOW-RISK-REORDER-ALLOW", "1.0"):
            self.store.save_policy(Policy(
                policy_id="POL-LOW-RISK-REORDER-ALLOW",
                policy_version="1.0",
                name="Routine Inventory Maintenance Policy",
                description="Permits routine low-risk reorder point adjustments and warehouse inventory moves under $5,000.",
                priority=60,
                scope={},
                rules=[
                    PolicyRule(
                        rule_id="rule_routine_reorder_allow",
                        name="Allow Low-Cost Routine Safety Stock Changes",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.ACTION_TYPE,
                                operator=PolicyOperator.IN,
                                value=["ADJUST_REORDER_POINT", "MOVE_INVENTORY"]
                            ),
                            PolicyCondition(
                                field=PolicyConditionCategory.RISK_LEVEL,
                                operator=PolicyOperator.EQUALS,
                                value="LOW"
                            )
                        ],
                        effect=PolicyEffect.ALLOW,
                        reason_code=PolicyReasonCode.POLICY_ALLOWED.value,
                        explanation="Low-risk routine inventory safety stock adjustments proceed without human approval."
                    )
                ]
            ))

        # 7. Supplier Order Modification Governance (Priority 65)
        if not self.store.get_policy("POL-SUPPLIER-UPDATE-APPROVAL", "1.0"):
            self.store.save_policy(Policy(
                policy_id="POL-SUPPLIER-UPDATE-APPROVAL",
                policy_version="1.0",
                name="Supplier Order Amendment Policy",
                description="Requires procurement manager approval for supplier contract or purchase order modifications.",
                priority=65,
                scope={},
                rules=[
                    PolicyRule(
                        rule_id="rule_supplier_update_gate",
                        name="Supplier Order Change Gate",
                        conditions=[
                            PolicyCondition(
                                field=PolicyConditionCategory.ACTION_TYPE,
                                operator=PolicyOperator.EQUALS,
                                value="UPDATE_SUPPLIER_ORDER"
                            )
                        ],
                        effect=PolicyEffect.REQUIRE_APPROVAL,
                        approval_requirement=ApprovalRequirement(
                            required=True,
                            approval_type="PROCUREMENT",
                            required_role="manager",
                            minimum_approvers=1,
                            reason_code=PolicyReasonCode.POLICY_APPROVAL_REQUIRED.value,
                            reason="Modifying external vendor supply orders mandates procurement manager review.",
                            policy_id="POL-SUPPLIER-UPDATE-APPROVAL",
                            policy_version="1.0"
                        ),
                        reason_code=PolicyReasonCode.POLICY_APPROVAL_REQUIRED.value,
                        explanation="Supplier order modifications require authorized procurement approval."
                    )
                ]
            ))

    def evaluate(
        self,
        action: Action,
        context: PolicyEvaluationContext,
        policy_ids: Optional[List[str]] = None,
        persist_decision: bool = True
    ) -> PolicyDecision:
        """
        Authoritatively evaluates an Action against active system policies.
        Precedence: DENY > REQUIRE_APPROVAL > HOLD > ALLOW. Default: Fail closed (HOLD).
        """
        trace = PolicyEvaluationTrace()
        matched_rules: List[Dict[str, Any]] = []
        conflicts: List[str] = []
        blocking_rules: List[Dict[str, Any]] = []
        approval_rules: List[Dict[str, Any]] = []
        allow_rules: List[Dict[str, Any]] = []
        hold_rules: List[Dict[str, Any]] = []

        # 1. Load applicable policies matching tenant scope
        if policy_ids:
            policies = [self.store.get_policy(pid) for pid in policy_ids if self.store.get_policy(pid)]
        else:
            policies = self.store.list_policies(tenant_id=context.tenant_id, active_only=True)

        trace.policies_evaluated = len(policies)
        trace.evaluated_policy_ids = [p.policy_id for p in policies]

        primary_policy: Optional[Policy] = None

        # 2. Evaluate all policies in priority order (high to low)
        for policy in policies:
            policy_matched = False
            for rule in policy.rules:
                # All conditions within a rule must match (AND)
                rule_matches = True
                for cond in rule.conditions:
                    if not PolicyConditionEvaluator.evaluate_condition(cond, action, context):
                        rule_matches = False
                        break

                if rule_matches:
                    policy_matched = True
                    rule_info = {
                        "policy_id": policy.policy_id,
                        "policy_version": policy.policy_version,
                        "rule_id": rule.rule_id,
                        "rule_name": rule.name,
                        "effect": rule.effect.value,
                        "reason_code": rule.reason_code,
                        "explanation": rule.explanation,
                        "approval_requirement": rule.approval_requirement.model_dump() if rule.approval_requirement else None
                    }
                    matched_rules.append(rule_info)
                    trace.matched_rule_ids.append(rule.rule_id)

                    if rule.effect == PolicyEffect.DENY:
                        blocking_rules.append(rule_info)
                    elif rule.effect == PolicyEffect.REQUIRE_APPROVAL:
                        approval_rules.append(rule_info)
                    elif rule.effect == PolicyEffect.HOLD:
                        hold_rules.append(rule_info)
                    elif rule.effect == PolicyEffect.ALLOW:
                        allow_rules.append(rule_info)

            if policy_matched:
                trace.policies_matched += 1
            else:
                trace.policies_unmatched += 1

        trace.blocking_rules = len(blocking_rules)
        trace.approval_rules = len(approval_rules)

        # 3. Apply Deterministic Precedence Hierarchy
        final_decision: PolicyEffect
        decisive_reason_codes: List[str] = []
        decisive_explanation: str
        effective_approval_req: Optional[ApprovalRequirement] = None
        decisive_policy_id: Optional[str] = None
        decisive_policy_version: Optional[str] = None

        if blocking_rules:
            # DENY has highest precedence
            final_decision = PolicyEffect.DENY
            top_rule = blocking_rules[0]
            decisive_policy_id = top_rule["policy_id"]
            decisive_policy_version = top_rule["policy_version"]
            decisive_reason_codes.append(top_rule["reason_code"] or PolicyReasonCode.POLICY_DENIED.value)
            decisive_explanation = f"Action DENIED by policy '{decisive_policy_id}': {top_rule['explanation']}"

            # Detect conflicts with any ALLOW rules
            if allow_rules:
                conflict_msg = f"Conflict detected: Policy '{top_rule['policy_id']}' DENIED action while lower-precedence rules matched ALLOW. Resolved to DENY."
                conflicts.append(conflict_msg)
                decisive_reason_codes.append(PolicyReasonCode.POLICY_CONFLICT.value)

        elif approval_rules:
            # REQUIRE_APPROVAL is next highest precedence
            final_decision = PolicyEffect.REQUIRE_APPROVAL
            top_rule = approval_rules[0]
            decisive_policy_id = top_rule["policy_id"]
            decisive_policy_version = top_rule["policy_version"]
            decisive_reason_codes.append(top_rule["reason_code"] or PolicyReasonCode.POLICY_APPROVAL_REQUIRED.value)
            decisive_explanation = f"Human authorization required by policy '{decisive_policy_id}': {top_rule['explanation']}"
            if top_rule.get("approval_requirement"):
                effective_approval_req = ApprovalRequirement(**top_rule["approval_requirement"])

        elif hold_rules:
            # HOLD is next
            final_decision = PolicyEffect.HOLD
            top_rule = hold_rules[0]
            decisive_policy_id = top_rule["policy_id"]
            decisive_policy_version = top_rule["policy_version"]
            decisive_reason_codes.append(top_rule["reason_code"] or PolicyReasonCode.POLICY_HOLD.value)
            decisive_explanation = f"Action placed on HOLD by policy '{decisive_policy_id}': {top_rule['explanation']}"

        elif allow_rules:
            # ALLOW is lowest precedence
            final_decision = PolicyEffect.ALLOW
            top_rule = allow_rules[0]
            decisive_policy_id = top_rule["policy_id"]
            decisive_policy_version = top_rule["policy_version"]
            decisive_reason_codes.append(top_rule["reason_code"] or PolicyReasonCode.POLICY_ALLOWED.value)
            decisive_explanation = f"Action permitted by policy '{decisive_policy_id}': {top_rule['explanation']}"

        else:
            # Fail closed: No matching active policy found
            final_decision = PolicyEffect.HOLD
            decisive_reason_codes.append(PolicyReasonCode.NO_MATCHING_POLICY_FOUND.value)
            decisive_explanation = "No applicable policy definition matched this action. System fails closed (HOLD) pending governance review."

        trace.conflicts_detected = conflicts
        trace.final_decision = final_decision

        decision = PolicyDecision(
            action_id=action.action_id,
            decision=final_decision,
            policy_id=decisive_policy_id,
            policy_version=decisive_policy_version,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            plant_id=action.target.plant_id or context.plant_id,
            reason_codes=decisive_reason_codes,
            explanation=decisive_explanation,
            matched_rules=matched_rules,
            risk_level=action.system_risk_level.value if hasattr(action.system_risk_level, "value") else str(action.system_risk_level),
            requires_approval=(final_decision == PolicyEffect.REQUIRE_APPROVAL),
            approval_requirement=effective_approval_req,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            data_mode=action.data_mode,
            evaluation_trace=trace.model_dump()
        )

        # 4. Save decision to repository for ledger & auditability
        if persist_decision:
            self.store.save_decision(decision)

            # 5. Coordinate Action Lifecycle status update
            if action_store.get(action.action_id):
                if final_decision == PolicyEffect.REQUIRE_APPROVAL:
                    action_store.update_status(action.action_id, ActionStatus.AWAITING_APPROVAL)
                elif final_decision == PolicyEffect.ALLOW:
                    action_store.update_status(action.action_id, ActionStatus.APPROVED)
                elif final_decision == PolicyEffect.DENY:
                    action_store.update_status(action.action_id, ActionStatus.REJECTED)
                # HOLD leaves action in POLICY_REVIEW

            # 6. Structured Security Audit Event
            audit_event_name = (
                "POLICY_ALLOWED" if final_decision == PolicyEffect.ALLOW
                else "POLICY_DENIED" if final_decision == PolicyEffect.DENY
                else "POLICY_APPROVAL_REQUIRED" if final_decision == PolicyEffect.REQUIRE_APPROVAL
                else "POLICY_HOLD"
            )
            log_security_event(
                event_name=audit_event_name,
                user_id=context.user_id,
                details={
                    "tenant_id": context.tenant_id,
                    "action_id": action.action_id,
                    "decision": final_decision.value,
                    "policy_id": decisive_policy_id,
                    "policy_version": decisive_policy_version,
                    "risk_level": decision.risk_level,
                    "requires_approval": decision.requires_approval,
                    "reason_codes": decisive_reason_codes
                }
            )

        return decision

    def simulate(
        self,
        action: Action,
        context: PolicyEvaluationContext,
        hypothetical_policies: Optional[List[Policy]] = None
    ) -> PolicyDecision:
        """
        Simulates policy evaluation without state mutation or action status updates.
        Zero side effects.
        """
        if hypothetical_policies:
            # Create a temporary evaluator with hypothetical policies
            temp_store = PolicyStore(db_path=":memory:")
            for p in hypothetical_policies:
                temp_store.save_policy(p)
            sim_service = PolicyService(store=temp_store)
            return sim_service.evaluate(action, context, persist_decision=False)

        return self.evaluate(action, context, persist_decision=False)


# Global singleton instance
policy_service = PolicyService()
