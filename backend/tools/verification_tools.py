# backend/tools/verification_tools.py
"""
SageCommand V3 — Agent Verification Tools (Prompt 36 / 36A Hardened)

Provides governed, read-only verification inspection tools for LangGraph agents.
Enforces the mandatory verification boundary and trusted identity invariants:
- Trusted identity context MUST come from server-injected runtime context (_verification_identity_context_var).
- Model-visible argument schemas MUST NOT include identity, tenant, workspace, plant, user, role, or clearance fields.
- Tools FAIL CLOSED immediately if trusted server identity context is unavailable.
- Tools NEVER manufacture fallback identity (tenant_default, plant_001, agent_verifier).
- Tools NEVER grant fixed roles (ANALYST, VIEWER) inside the tool implementation.
- Agents CANNOT forge verification results, declare missing evidence valid, override
  deterministic rules, mark operational steps completed, approve actions, change mission scope,
  or execute missions.
- Raw exception details are never leaked to model callers.

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.
"""

import logging
from contextvars import ContextVar, Token
from contextlib import contextmanager, asynccontextmanager
from typing import Dict, Any, Optional, List
from langchain_core.tools import tool

logger = logging.getLogger("verification_tools")

try:
    from core.auth import Identity
    from data.schemas.verification_contract import (
        VerificationRequest,
        VerificationTargetType,
        TriggerType,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from services.verification_service import verification_service
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity
    from backend.data.schemas.verification_contract import (
        VerificationRequest,
        VerificationTargetType,
        TriggerType,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from backend.services.verification_service import verification_service

# Thread-safe, async-safe context variable for server-authoritative caller identity
_verification_identity_context_var: ContextVar[Optional[Identity]] = ContextVar(
    "verification_identity_context", default=None
)


def set_active_verification_identity(identity: Optional[Identity]) -> Token:
    """
    Binds trusted, server-authoritative Identity context for verification tool execution.
    Returns ContextVar Token for safe reset in finally blocks.
    """
    return _verification_identity_context_var.set(identity)


def reset_active_verification_identity(token: Token) -> None:
    """
    Resets active verification identity context using the token from set_active_verification_identity.
    """
    _verification_identity_context_var.reset(token)


def get_active_verification_identity() -> Optional[Identity]:
    """Retrieves active trusted Identity context from server environment."""
    return _verification_identity_context_var.get()


@contextmanager
def active_verification_identity(identity: Optional[Identity]):
    """
    Token-safe synchronous context manager for authoritative verification identity lifecycle.
    Guarantees reset of context variable in finally block, preventing cross-request leaks.
    """
    token = set_active_verification_identity(identity)
    try:
        yield identity
    finally:
        reset_active_verification_identity(token)


@asynccontextmanager
async def async_active_verification_identity(identity: Optional[Identity]):
    """
    Token-safe asynchronous context manager for authoritative verification identity lifecycle.
    Guarantees reset of context variable in finally block, preventing cross-request leaks.
    """
    token = set_active_verification_identity(identity)
    try:
        yield identity
    finally:
        reset_active_verification_identity(token)


@tool
def request_mission_verification_tool(
    mission_id: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    freshness_threshold_override_seconds: Optional[float] = None,
) -> str:
    """
    Requests continuous evidence-driven verification for a governed mission.
    Evaluates whether mission criteria or steps are supported by current, authorized evidence.
    Returns deterministic status, verified/unverified counts, and summary.
    Does NOT execute actions or complete steps.
    Requires active, server-authenticated identity context.
    """
    identity = get_active_verification_identity()
    if not identity:
        return (
            "[VERIFICATION BLOCKED] Trusted caller identity context is unavailable. "
            "Verification operations require an authenticated server context."
        )

    try:
        tt_enum = None
        if target_type:
            tt_clean = target_type.upper().strip()
            if tt_clean in ("CRITERION", "STEP"):
                tt_enum = VerificationTargetType(tt_clean)

        req = VerificationRequest(
            target_type=tt_enum,
            target_id=target_id.strip() if target_id else None,
            trigger_type=TriggerType.AUTOMATED_CHECK,
            freshness_threshold_override_seconds=freshness_threshold_override_seconds,
        )

        run = verification_service.request_verification(
            identity=identity,
            mission_id=mission_id.strip(),
            request=req,
        )

        diag_line = ""
        if run.is_diagnostic:
            diag_outcome_str = run.diagnostic_outcome or (run.diagnostic_status.value if run.diagnostic_status else "NONE")
            diag_line = f"Diagnostic Check: True (Outcome: {diag_outcome_str} — non-authoritative existence check)\n"

        return (
            f"[VERIFICATION COMPLETED]\n"
            f"Notice: {MANDATORY_VERIFICATION_NOTICE}\n"
            f"Verification ID: {run.verification_id}\n"
            f"Mission ID: {run.mission_id} (Rev {run.mission_revision})\n"
            f"Overall Status: {run.status.value}\n"
            f"{diag_line}"
            f"Targets Evaluated: {run.target_count} "
            f"(Verified: {run.verified_count}, Unverified: {run.unverified_count}, "
            f"Indeterminate: {run.indeterminate_count}, Blocked: {run.blocked_count}, Failed: {run.failed_count})\n"
            f"Summary: {run.summary}\n"
            f"Limitations Count: {len(run.provenance.limitations)}"
        )
    except Exception as e:
        logger.error("Error executing verification tool for mission '%s': %s", mission_id, e, exc_info=True)
        return (
            f"[VERIFICATION ERROR] Could not verify mission '{mission_id}'. "
            f"A server-side error occurred during verification processing."
        )


@tool
def get_mission_verification_findings_tool(
    mission_id: str,
    verification_id: str,
) -> str:
    """
    Inspects authorized verification findings for a mission verification run.
    Explains which criteria or steps are verified, unverified, stale, conflicting, or blocked,
    along with evidence references and recorded limitations.
    Requires active, server-authenticated identity context.
    """
    identity = get_active_verification_identity()
    if not identity:
        return (
            "[FINDINGS RETRIEVAL BLOCKED] Trusted caller identity context is unavailable. "
            "Findings inspection requires an authenticated server context."
        )

    try:
        findings = verification_service.get_verification_findings(
            identity=identity,
            mission_id=mission_id.strip(),
            verification_id=verification_id.strip(),
        )

        if not findings:
            return f"No findings found for verification run '{verification_id}' on mission '{mission_id}'."

        lines = [
            f"Verification Findings for Run '{verification_id}':",
            f"Notice: {MANDATORY_VERIFICATION_NOTICE}",
        ]
        for f in findings:
            lines.append(
                f"- Target: [{f.target_type.value}] {f.target_id} | Status: {f.status.value} | Rule: {f.rule_id} v{f.rule_version}\n"
                f"  Explanation: {f.explanation}\n"
                f"  Evidence Refs: {f.evidence_references}\n"
                f"  Limitations: {f.limitations}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error(
            "Error retrieving verification findings for run '%s' on mission '%s': %s",
            verification_id,
            mission_id,
            e,
            exc_info=True,
        )
        return (
            f"[FINDINGS RETRIEVAL ERROR] Could not fetch findings for verification run "
            f"'{verification_id}' on mission '{mission_id}'. A server-side error occurred."
        )
