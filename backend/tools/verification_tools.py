# backend/tools/verification_tools.py
"""
SageCommand V3 — Agent Verification Tools (Prompt 36)

Provides governed, read-only verification inspection tools for LangGraph agents.
Enforces the mandatory verification boundary:
- Agents may request verification, inspect authorized findings, summarize limitations,
  and recommend follow-up evidence collection.
- Agents CANNOT forge verification results, declare missing evidence valid, override
  deterministic rules, mark operational steps completed, approve actions, change mission scope,
  or execute missions.

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.
"""

from typing import Dict, Any, Optional, List
from langchain_core.tools import tool

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


@tool
def request_mission_verification_tool(
    mission_id: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    freshness_threshold_override_seconds: Optional[float] = None,
    tenant_id: str = "tenant_default",
    workspace_id: str = "workspace_default",
    plant_id: str = "plant_001",
    user_id: str = "agent_verifier",
) -> str:
    """
    Requests continuous evidence-driven verification for a governed mission.
    Evaluates whether mission criteria or steps are supported by current, authorized evidence.
    Returns deterministic status, verified/unverified counts, and summary.
    Does NOT execute actions or complete steps.
    """
    try:
        # Construct caller identity
        identity = Identity(
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            roles=["ANALYST"],
        )

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

        return (
            f"[VERIFICATION COMPLETED]\n"
            f"Notice: {MANDATORY_VERIFICATION_NOTICE}\n"
            f"Verification ID: {run.verification_id}\n"
            f"Mission ID: {run.mission_id} (Rev {run.mission_revision})\n"
            f"Overall Status: {run.status.value}\n"
            f"Targets Evaluated: {run.target_count} "
            f"(Verified: {run.verified_count}, Unverified: {run.unverified_count}, "
            f"Indeterminate: {run.indeterminate_count}, Blocked: {run.blocked_count}, Failed: {run.failed_count})\n"
            f"Summary: {run.summary}\n"
            f"Limitations Count: {len(run.provenance.limitations)}"
        )
    except Exception as e:
        return f"[VERIFICATION ERROR] Could not verify mission '{mission_id}': {str(e)}"


@tool
def get_mission_verification_findings_tool(
    mission_id: str,
    verification_id: str,
    tenant_id: str = "tenant_default",
    workspace_id: str = "workspace_default",
    plant_id: str = "plant_001",
    user_id: str = "agent_verifier",
) -> str:
    """
    Inspects authorized verification findings for a mission verification run.
    Explains which criteria or steps are verified, unverified, stale, conflicting, or blocked,
    along with evidence references and recorded limitations.
    """
    try:
        identity = Identity(
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            roles=["VIEWER"],
        )

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
        return f"[FINDINGS RETRIEVAL ERROR] Failed to fetch findings: {str(e)}"
