# backend/services/verification_rules.py
"""
SageCommand V3 — Deterministic Verification Rules Registry (Prompt 36)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Provides versioned, deterministic verification rules:
- EVIDENCE_EXISTS
- EVIDENCE_VALIDATED
- EVIDENCE_FRESH
- REQUIRED_EVIDENCE_PRESENT
- REQUIRED_EVIDENCE_VALIDATED
- EVIDENCE_SCOPE_MATCH
- REQUIRED_FIELDS_PRESENT
- SOURCE_CONSISTENCY

Invariants:
- Deterministic: same inputs + rule version -> identical output.
- LLM reasoning or client payloads cannot override deterministic results.
- Preserves uncertainty: missing, stale, or conflicting evidence produces distinct statuses.
- Never executes arbitrary SQL, shell, or code expressions.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone, timedelta
import math
import uuid

try:
    from core.config import SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS
    from data.schemas.verification_contract import (
        RuleType,
        VerificationStatus,
        VerificationTargetType,
        FreshnessStatus,
        QualityStatus,
        ScopeStatus,
        EvidenceAssessment,
        VerificationFinding,
        VerificationRule,
        RULE_SET_VERSION,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS
    from backend.data.schemas.verification_contract import (
        RuleType,
        VerificationStatus,
        VerificationTargetType,
        FreshnessStatus,
        QualityStatus,
        ScopeStatus,
        EvidenceAssessment,
        VerificationFinding,
        VerificationRule,
        RULE_SET_VERSION,
    )


def _parse_iso_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Safely parses ISO-8601 timestamp string into timezone-aware UTC datetime."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        clean = ts_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# =============================================================================
# UNIVERSAL SCOPE AUTHORIZATION & NON-DISCLOSURE HELPERS
# =============================================================================

UNAUTHORIZED_SCOPE_STATUSES: Set[ScopeStatus] = {
    ScopeStatus.CROSS_TENANT,
    ScopeStatus.CROSS_WORKSPACE,
    ScopeStatus.CROSS_PLANT,
    ScopeStatus.UNAUTHORIZED,
    ScopeStatus.REJECTED,
    ScopeStatus.UNTAGGED_PLANT,
}

BLOCKED_CLASSIFICATION_STATUSES: Set[str] = {
    "BLOCKED",
    "CLEARANCE_INSUFFICIENT",
}


def is_evidence_scope_violation(a: EvidenceAssessment) -> bool:
    """Returns True if an assessment represents an explicit cross-boundary or unauthorized scope status."""
    return a.scope_status in UNAUTHORIZED_SCOPE_STATUSES


def is_evidence_clearance_violation(a: EvidenceAssessment) -> bool:
    """Returns True if an assessment has insufficient clearance or blocked classification."""
    return a.classification_status in BLOCKED_CLASSIFICATION_STATUSES


def is_evidence_blocked(a: EvidenceAssessment) -> bool:
    """Returns True if an assessment must be blocked due to scope boundary violation or classification clearance."""
    return is_evidence_scope_violation(a) or is_evidence_clearance_violation(a)


def is_evidence_authorized_for_disclosure(a: EvidenceAssessment) -> bool:
    """
    Returns True if an assessment is authorized for caller-visible disclosure.
    Must strictly have AUTHORIZED scope status and authorized clearance.
    """
    if is_evidence_blocked(a):
        return False
    if a.scope_status != ScopeStatus.AUTHORIZED:
        return False
    if a.classification_status not in ("AUTHORIZED", "CLEARANCE_SUFFICIENT"):
        return False
    return True


def sanitize_finding_disclosure(
    assessments: List[EvidenceAssessment],
) -> tuple[List[str], List[EvidenceAssessment]]:
    """
    Filters caller-visible evidence references and assessments, returning ONLY
    those authorized for disclosure. Inaccessible/blocked/unresolved items are completely redacted.
    """
    visible = [a for a in assessments if is_evidence_authorized_for_disclosure(a)]
    return [a.evidence_id for a in visible], visible


def generate_non_disclosing_limitations(
    blocked_items: List[EvidenceAssessment],
    default_msg: str = "One or more evidence references could not be evaluated within the authorized scope.",
) -> List[str]:
    """Generates generic, non-disclosing limitations for blocked items without leaking IDs or record metadata."""
    limits = []
    has_clearance = any(is_evidence_clearance_violation(b) for b in blocked_items)
    has_scope = any(is_evidence_scope_violation(b) for b in blocked_items)
    if has_clearance:
        limits.append("One or more evidence references could not be verified due to classification clearance restrictions.")
    if has_scope:
        limits.append("One or more evidence references could not be verified due to scope boundary restrictions.")
    if not limits:
        limits.append(default_msg)
    return limits


class BaseDeterministicRule(ABC):
    """Abstract base class for deterministic verification rules."""

    def __init__(
        self,
        rule_id: str,
        rule_type: RuleType,
        description: str,
        rule_version: str = RULE_SET_VERSION,
        supported_target_types: Optional[List[VerificationTargetType]] = None,
        freshness_threshold_seconds: Optional[float] = None,
    ):
        self.rule_id = rule_id
        self.rule_type = rule_type
        self.description = description
        self.rule_version = rule_version
        self.supported_target_types = supported_target_types or [
            VerificationTargetType.CRITERION,
            VerificationTargetType.STEP,
            VerificationTargetType.OVERALL_MISSION,
        ]
        self.freshness_threshold_seconds = freshness_threshold_seconds

    def to_contract(self) -> VerificationRule:
        return VerificationRule(
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            rule_type=self.rule_type,
            description=self.description,
            supported_target_types=self.supported_target_types,
            freshness_threshold_seconds=self.freshness_threshold_seconds,
        )

    @abstractmethod
    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        """Deterministically evaluates target against resolved evidence assessments."""
        pass


class EvidenceExistsRule(BaseDeterministicRule):
    """Evaluates whether at least one authorized, applicable evidence item exists."""

    def __init__(self):
        super().__init__(
            rule_id="RULE_EVIDENCE_EXISTS_V1",
            rule_type=RuleType.EVIDENCE_EXISTS,
            description="Verifies that at least one authorized, applicable evidence item exists for the target.",
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"
        limitations: List[str] = []

        if not assessments:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[],
                evidence_assessments=[],
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"No evidence records found or accessible for target '{target_id}'. Condition remains unverified.",
                limitations=["Evidence repository contains no matching records within authorized scope."],
                evaluated_at=now_iso,
            )

        required_assessments = list(assessments)
        authorized_req = [
            a for a in required_assessments
            if is_evidence_authorized_for_disclosure(a) and a.applicability_status == "APPLICABLE"
        ]
        blocked_req = [a for a in required_assessments if is_evidence_blocked(a)]
        unknown_req = [a for a in required_assessments if a not in authorized_req and a not in blocked_req]

        visible_evidence_refs, visible_assessments = sanitize_finding_disclosure(required_assessments)

        if blocked_req:
            limitations = generate_non_disclosing_limitations(blocked_req)
        elif unknown_req:
            if authorized_req:
                limitations.append("One or more required evidence references could not be resolved within authorized scope.")
            else:
                limitations.append("Evidence repository contains no matching records within authorized scope.")

        if blocked_req:
            status = VerificationStatus.BLOCKED
            explanation = (
                f"Target '{target_id}' verification blocked: one or more required evidence references "
                f"cannot be assessed within authorized scope or clearance boundaries."
            )
        elif unknown_req:
            if authorized_req:
                status = VerificationStatus.INDETERMINATE
                explanation = (
                    f"Target '{target_id}' verification indeterminate: one or more required evidence records "
                    f"are unresolved or unavailable within authorized scope."
                )
            else:
                status = VerificationStatus.NOT_VERIFIED
                explanation = f"No evidence records found in repository for target '{target_id}'. Condition remains unverified."
        elif authorized_req and len(authorized_req) == len(required_assessments):
            status = VerificationStatus.VERIFIED
            explanation = (
                f"Verified presence of {len(authorized_req)} accessible, scope-authorized evidence record(s) "
                f"for target '{target_id}'. Notice: Evidence existence confirms record presence only — "
                f"does not self-certify operational completion or outcome."
            )
        else:
            status = VerificationStatus.INDETERMINATE
            explanation = f"Evidence for target '{target_id}' does not satisfy existence criteria within authorized scope."
            limitations = ["Evidence records unresolved or unavailable within authorized scope."]

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=status,
            evidence_references=visible_evidence_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=explanation,
            limitations=limitations,
            evaluated_at=now_iso,
        )


class EvidenceValidatedRule(BaseDeterministicRule):
    """Evaluates whether all applicable evidence items have integrity_status == 'VALID'."""

    def __init__(self):
        super().__init__(
            rule_id="RULE_EVIDENCE_VALIDATED_V1",
            rule_type=RuleType.EVIDENCE_VALIDATED,
            description="Verifies that all resolved evidence records have validated integrity and are not unverified or invalid.",
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"

        if not assessments:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[],
                evidence_assessments=[],
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"No evidence records available to validate for target '{target_id}'.",
                limitations=["Missing evidence records."],
                evaluated_at=now_iso,
            )

        # 1. Scope & clearance boundary check: fail closed
        blocked_items = [a for a in assessments if is_evidence_blocked(a)]
        if blocked_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            limitations = generate_non_disclosing_limitations(blocked_items)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' verification blocked due to scope boundary violation or insufficient classification clearance in supporting evidence.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 2. Scope unknown check
        unknown_scope = [a for a in assessments if a.scope_status == ScopeStatus.UNKNOWN or a.scope_status is None]
        if unknown_scope:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' verification indeterminate: one or more evidence items have unknown scope status.",
                limitations=["Evidence items have unknown scope status within authorized boundaries."],
                evaluated_at=now_iso,
            )

        visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)

        # 3. Explicit conflict check
        conflicting_items = [
            a for a in visible_assessments
            if a.quality_status == QualityStatus.CONFLICTING or str(a.integrity_status).upper() == "CONFLICTING"
        ]
        if conflicting_items:
            limitations = ["Conflicting evidence sources detected across supporting records."]
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.CONFLICTING,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Conflicting evidence sources detected for target '{target_id}'. Condition cannot be verified.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 4. Invalid items check
        invalid_items = [
            a for a in visible_assessments
            if str(a.integrity_status).upper() == "INVALID"
            or a.quality_status == QualityStatus.INVALID
            or a.applicability_status in ("INAPPLICABLE", "TARGET_MISMATCH")
        ]
        if invalid_items:
            limitations = ["One or more supporting evidence items failed integrity validation check."]
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' contains {len(invalid_items)} INVALID evidence record(s). Cannot establish verification.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 5. Unverified / unknown / incomplete items check (Mixed collections FAIL CLOSED)
        unresolved_items = [
            a for a in visible_assessments
            if str(a.integrity_status).upper() in ("UNVERIFIED", "UNKNOWN", "INCOMPLETE")
            or a.quality_status in (QualityStatus.UNVERIFIED, QualityStatus.UNKNOWN, QualityStatus.INCOMPLETE)
            or a.classification_status == "UNKNOWN"
            or a.applicability_status in ("UNKNOWN", "UNAVAILABLE")
        ]
        if unresolved_items:
            limitations = ["One or more evidence items have unresolved or unverified integrity within authorized scope."]
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=(
                    f"Target '{target_id}' contains {len(unresolved_items)} unverified, unknown, or incomplete evidence record(s). "
                    f"All required evidence must have validated integrity before verification can be confirmed."
                ),
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 6. ALL items must be valid, authorized, and applicable
        valid_items = [
            a for a in visible_assessments
            if str(a.integrity_status).upper() == "VALID"
            and a.quality_status == QualityStatus.VALID
            and a.scope_status == ScopeStatus.AUTHORIZED
            and a.classification_status in ("AUTHORIZED", "CLEARANCE_SUFFICIENT")
            and a.applicability_status == "APPLICABLE"
        ]
        if len(valid_items) != len(assessments) or not valid_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Not all evidence records for target '{target_id}' meet validated integrity criteria.",
                limitations=["Unresolved evidence items within authorized scope."],
                evaluated_at=now_iso,
            )

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=visible_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"All {len(valid_items)} supporting evidence record(s) have validated integrity and authorized clearance for target '{target_id}'.",
            limitations=[],
            evaluated_at=now_iso,
        )


class EvidenceFreshRule(BaseDeterministicRule):
    """Evaluates evidence freshness against configurable or default threshold."""

    def __init__(self, default_threshold_seconds: float = SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS):
        super().__init__(
            rule_id="RULE_EVIDENCE_FRESH_V1",
            rule_type=RuleType.EVIDENCE_FRESH,
            description="Verifies that supporting evidence has current observation timestamps within the allowed freshness window.",
            freshness_threshold_seconds=default_threshold_seconds,
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        eval_dt = now or datetime.now(timezone.utc)
        now_iso = eval_dt.isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"
        limitations: List[str] = []

        threshold = float(parameters.get("freshness_threshold_seconds") or self.freshness_threshold_seconds or SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS)

        if not assessments:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[],
                evidence_assessments=[],
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"No evidence records available to evaluate freshness for target '{target_id}'.",
                limitations=["Missing evidence records."],
                evaluated_at=now_iso,
            )

        # 1. Scope and clearance boundary check: fail closed
        blocked_items = [a for a in assessments if is_evidence_blocked(a)]
        if blocked_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            limitations = generate_non_disclosing_limitations(blocked_items)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' freshness evaluation blocked due to scope boundary violation or insufficient classification clearance.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 2. Scope unknown check
        unknown_scope = [a for a in assessments if a.scope_status == ScopeStatus.UNKNOWN or a.scope_status is None]
        if unknown_scope:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' freshness evaluation indeterminate: one or more evidence items have unknown scope status.",
                limitations=["Evidence items have unknown scope status."],
                evaluated_at=now_iso,
            )

        visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)

        stale_items = []
        missing_ts_items = []
        future_items = []
        fresh_items = []

        for a in visible_assessments:
            a.freshness_threshold_seconds = threshold
            obs_dt = _parse_iso_timestamp(a.observed_at)
            if not obs_dt or a.freshness_status == FreshnessStatus.TIMESTAMP_MISSING:
                a.freshness_status = FreshnessStatus.TIMESTAMP_MISSING
                missing_ts_items.append(a)
                limitations.append(f"Evidence '{a.evidence_id}' lacks valid observation timestamp; freshness cannot be proven.")
                continue

            age_sec = (eval_dt - obs_dt).total_seconds()
            a.freshness_seconds = max(0.0, age_sec)

            if age_sec < -60.0:  # More than 60s in the future
                a.freshness_status = FreshnessStatus.FUTURE_DATED
                future_items.append(a)
                limitations.append(f"Evidence '{a.evidence_id}' has a future-dated timestamp ({a.observed_at}).")
            elif age_sec > threshold:
                a.freshness_status = FreshnessStatus.STALE
                stale_items.append(a)
                limitations.append(f"Evidence '{a.evidence_id}' is stale (age: {age_sec:.1f}s > threshold: {threshold:.1f}s).")
            else:
                a.freshness_status = FreshnessStatus.CURRENT
                fresh_items.append(a)

        if future_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' contains future-dated evidence timestamps. Cannot certify freshness.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        if missing_ts_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Evidence for target '{target_id}' is missing observation timestamps. Freshness cannot be determined without authoritative observation time.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        if stale_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.STALE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Supporting evidence for target '{target_id}' is STALE beyond allowed window ({threshold:.0f}s).",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        if len(fresh_items) == len(assessments) and fresh_items:
            status = VerificationStatus.VERIFIED
            explanation = f"All {len(fresh_items)} evidence record(s) have verified fresh observation timestamps within threshold ({threshold:.0f}s) for target '{target_id}'."
        else:
            status = VerificationStatus.NOT_VERIFIED
            explanation = f"No fresh evidence satisfied freshness requirements for target '{target_id}'."

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=status,
            evidence_references=visible_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=explanation,
            limitations=limitations,
            evaluated_at=now_iso,
        )


class RequiredEvidencePresentRule(BaseDeterministicRule):
    """Evaluates whether all explicitly required evidence items or source types are present."""

    def __init__(self):
        super().__init__(
            rule_id="RULE_REQUIRED_EVIDENCE_PRESENT_V1",
            rule_type=RuleType.REQUIRED_EVIDENCE_PRESENT,
            description="Verifies that all specified mandatory evidence requirements or source types are present.",
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"
        limitations: List[str] = []

        required_types: List[str] = parameters.get("required_evidence_types", [])
        required_ids: List[str] = parameters.get("required_evidence_ids", [])

        # Check scope and clearance on attached assessments
        blocked_items = [a for a in assessments if is_evidence_blocked(a)]
        if blocked_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            limitations = generate_non_disclosing_limitations(blocked_items)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' verification blocked due to scope boundary violation or insufficient classification clearance in required evidence.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        unknown_scope = [a for a in assessments if a.scope_status == ScopeStatus.UNKNOWN or a.scope_status is None]
        if unknown_scope:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' has evidence with unverified or unknown scope.",
                limitations=["Evidence items have unknown scope status within authorized boundaries."],
                evaluated_at=now_iso,
            )

        if not required_types and not required_ids:
            if not assessments:
                return VerificationFinding(
                    finding_id=finding_id,
                    target_type=target_type,
                    target_id=target_id,
                    status=VerificationStatus.NOT_VERIFIED,
                    evidence_references=[],
                    evidence_assessments=[],
                    rule_id=self.rule_id,
                    rule_version=self.rule_version,
                    explanation=f"Target '{target_id}' has no supporting evidence attached.",
                    limitations=["Missing evidence records."],
                    evaluated_at=now_iso,
                )

            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.VERIFIED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"All general evidence requirements met for target '{target_id}'.",
                limitations=[],
                evaluated_at=now_iso,
            )

        present_types = {a.source_type.upper() for a in assessments if a.scope_status == ScopeStatus.AUTHORIZED}
        present_ids = {a.evidence_id for a in assessments if a.scope_status == ScopeStatus.AUTHORIZED}

        missing_types = [t for t in required_types if t.upper() not in present_types]
        missing_ids = [i for i in required_ids if i not in present_ids]

        visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)

        if missing_types or missing_ids:
            if missing_types:
                limitations.append(f"Missing required evidence types: {missing_types}.")
            if missing_ids:
                limitations.append("Missing required evidence records within authorized scope.")

            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' is missing required evidence items.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=visible_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"All {len(required_types) + len(required_ids)} required evidence items and types are present for target '{target_id}'.",
            limitations=[],
            evaluated_at=now_iso,
        )


class RequiredEvidenceValidatedRule(BaseDeterministicRule):
    """Evaluates whether all required evidence items are present AND validated."""

    def __init__(self):
        super().__init__(
            rule_id="RULE_REQUIRED_EVIDENCE_VALIDATED_V1",
            rule_type=RuleType.REQUIRED_EVIDENCE_VALIDATED,
            description="Verifies that all specified mandatory evidence requirements are present and validated.",
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"

        if not assessments:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[],
                evidence_assessments=[],
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"No evidence available for target '{target_id}'.",
                limitations=["Missing evidence records."],
                evaluated_at=now_iso,
            )

        # 1. Scope & clearance check
        blocked_items = [a for a in assessments if is_evidence_blocked(a)]
        if blocked_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            limitations = generate_non_disclosing_limitations(blocked_items)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' verification blocked due to scope boundary violation or insufficient classification clearance in supporting evidence.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 2. Scope unknown check
        unknown_scope = [a for a in assessments if a.scope_status == ScopeStatus.UNKNOWN or a.scope_status is None]
        if unknown_scope:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' verification indeterminate: one or more evidence items have unknown scope status.",
                limitations=["Evidence items have unknown scope status."],
                evaluated_at=now_iso,
            )

        visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)

        # 3. Conflicts
        conflicting_items = [
            a for a in visible_assessments
            if a.quality_status == QualityStatus.CONFLICTING or str(a.integrity_status).upper() == "CONFLICTING"
        ]
        if conflicting_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.CONFLICTING,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Conflicting evidence sources detected for target '{target_id}'. Condition cannot be verified.",
                limitations=["Conflicting evidence sources detected."],
                evaluated_at=now_iso,
            )

        # 4. Invalid items
        invalid = [
            a for a in visible_assessments
            if str(a.integrity_status).upper() == "INVALID"
            or a.quality_status == QualityStatus.INVALID
            or a.applicability_status in ("INAPPLICABLE", "TARGET_MISMATCH")
        ]
        if invalid:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' has {len(invalid)} invalid evidence item(s).",
                limitations=["One or more evidence items failed integrity validation check."],
                evaluated_at=now_iso,
            )

        # 5. Unverified / unknown items
        unresolved = [
            a for a in visible_assessments
            if str(a.integrity_status).upper() in ("UNVERIFIED", "UNKNOWN", "INCOMPLETE")
            or a.quality_status in (QualityStatus.UNVERIFIED, QualityStatus.UNKNOWN, QualityStatus.INCOMPLETE)
            or a.classification_status == "UNKNOWN"
            or a.applicability_status in ("UNKNOWN", "UNAVAILABLE")
        ]
        if unresolved:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' contains {len(unresolved)} unverified or incomplete evidence item(s).",
                limitations=["One or more evidence items have unresolved or incomplete status."],
                evaluated_at=now_iso,
            )

        # 6. Valid items
        valid = [
            a for a in visible_assessments
            if str(a.integrity_status).upper() == "VALID"
            and a.quality_status == QualityStatus.VALID
            and a.scope_status == ScopeStatus.AUTHORIZED
            and a.classification_status in ("AUTHORIZED", "CLEARANCE_SUFFICIENT")
            and a.applicability_status == "APPLICABLE"
        ]
        if len(valid) != len(assessments) or not valid:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' evidence items are not fully validated.",
                limitations=["Incomplete validation."],
                evaluated_at=now_iso,
            )

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=visible_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"All {len(assessments)} supporting evidence record(s) are present, cleared, and validated for target '{target_id}'.",
            limitations=[],
            evaluated_at=now_iso,
        )


class EvidenceScopeMatchRule(BaseDeterministicRule):
    """Verifies that evidence strictly matches the mission's tenant, workspace, and plant scope."""

    def __init__(self):
        super().__init__(
            rule_id="RULE_EVIDENCE_SCOPE_MATCH_V1",
            rule_type=RuleType.EVIDENCE_SCOPE_MATCH,
            description="Verifies that all evidence items strictly match tenant, workspace, and plant scope boundaries.",
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"
        limitations: List[str] = []

        if not assessments:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[],
                evidence_assessments=[],
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"No evidence to check scope match for target '{target_id}'.",
                limitations=["No evidence records."],
                evaluated_at=now_iso,
            )

        # 1. Check for unauthorized / cross-boundary / clearance violations
        blocked_items = [a for a in assessments if is_evidence_blocked(a)]
        if blocked_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            limitations = generate_non_disclosing_limitations(blocked_items)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' blocked due to scope boundary or clearance violation in supporting evidence.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 2. Check for UNKNOWN / unresolved scope status
        unknown_scope_items = [a for a in assessments if a.scope_status == ScopeStatus.UNKNOWN or a.scope_status is None]
        if unknown_scope_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' scope match indeterminate: one or more evidence items have unknown or unverified scope status.",
                limitations=["Evidence items have unknown scope status."],
                evaluated_at=now_iso,
            )

        # 3. Check for full AUTHORIZED match
        authorized_items = [
            a for a in assessments
            if a.scope_status == ScopeStatus.AUTHORIZED
            and a.classification_status in ("AUTHORIZED", "CLEARANCE_SUFFICIENT")
        ]
        if len(authorized_items) != len(assessments) or not authorized_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' evidence items do not fully satisfy authorized scope matching.",
                limitations=["Incomplete scope authorization match."],
                evaluated_at=now_iso,
            )

        visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=visible_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"All {len(assessments)} evidence item(s) strictly match tenant, workspace, plant boundaries, and clearance tier.",
            limitations=[],
            evaluated_at=now_iso,
        )


class RequiredFieldsPresentRule(BaseDeterministicRule):
    """Verifies that evidence records contain specific required non-empty payload fields."""

    def __init__(self):
        super().__init__(
            rule_id="RULE_REQUIRED_FIELDS_PRESENT_V1",
            rule_type=RuleType.REQUIRED_FIELDS_PRESENT,
            description="Verifies that resolved evidence records contain all specified required fields.",
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"
        limitations: List[str] = []

        required_fields: List[str] = parameters.get("required_fields", [])
        if not assessments:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[],
                evidence_assessments=[],
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"No evidence records available to evaluate required fields for target '{target_id}'.",
                limitations=["No evidence records."],
                evaluated_at=now_iso,
            )

        # Check scope and clearance
        blocked_items = [a for a in assessments if is_evidence_blocked(a)]
        if blocked_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            limitations = generate_non_disclosing_limitations(blocked_items)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' evaluation blocked due to scope or clearance restrictions.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        unknown_scope = [a for a in assessments if a.scope_status == ScopeStatus.UNKNOWN or a.scope_status is None]
        if unknown_scope:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' required fields evaluation indeterminate: one or more evidence items have unknown scope status.",
                limitations=["Evidence items have unknown scope status."],
                evaluated_at=now_iso,
            )

        visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
        raw_payloads = parameters.get("evidence_payloads", {})

        missing_fields_total = []
        for a in visible_assessments:
            payload = raw_payloads.get(a.evidence_id, {})
            for rf in required_fields:
                if rf not in payload or payload[rf] is None or payload[rf] == "":
                    missing_fields_total.append(f"{a.evidence_id}:{rf}")
                    limitations.append(f"Evidence '{a.evidence_id}' lacks required field '{rf}'.")

        if missing_fields_total:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' missing required fields: {missing_fields_total}.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=visible_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"All required fields {required_fields} present across resolved evidence for target '{target_id}'.",
            limitations=[],
            evaluated_at=now_iso,
        )


class SourceConsistencyRule(BaseDeterministicRule):
    """Evaluates consistency across multiple independent evidence sources."""

    def __init__(self):
        super().__init__(
            rule_id="RULE_SOURCE_CONSISTENCY_V1",
            rule_type=RuleType.SOURCE_CONSISTENCY,
            description="Verifies consistency across two or more independent evidence sources; reports CONFLICTING if contradictory.",
        )

    def evaluate(
        self,
        target_id: str,
        target_type: VerificationTargetType,
        assessments: List[EvidenceAssessment],
        mission_scope: Dict[str, str],
        parameters: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> VerificationFinding:
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        finding_id = f"vf_{uuid.uuid4().hex[:12]}"
        limitations: List[str] = []

        # Check scope and clearance
        blocked_items = [a for a in assessments if is_evidence_blocked(a)]
        if blocked_items:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            limitations = generate_non_disclosing_limitations(blocked_items)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' multi-source consistency evaluation blocked due to scope or clearance restrictions.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        unknown_scope = [a for a in assessments if a.scope_status == ScopeStatus.UNKNOWN or a.scope_status is None]
        if unknown_scope:
            visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' multi-source consistency evaluation indeterminate: one or more evidence items have unknown scope status.",
                limitations=["Evidence items have unknown scope status."],
                evaluated_at=now_iso,
            )

        visible_refs, visible_assessments = sanitize_finding_disclosure(assessments)

        if len(visible_assessments) < 2:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Only {len(visible_assessments)} source(s) available for target '{target_id}'. Multi-source consistency requires at least 2 independent sources within authorized scope.",
                limitations=["Insufficient corroborating sources within authorized scope."],
                evaluated_at=now_iso,
            )

        # Check for explicit conflict flags or payload values comparison
        raw_payloads = parameters.get("evidence_payloads", {})
        metric_key = parameters.get("metric_key")
        tolerance = float(parameters.get("tolerance", 0.05))

        # 1. QualityStatus check
        conflicting_assessments = [a for a in visible_assessments if a.quality_status == QualityStatus.CONFLICTING]
        if conflicting_assessments:
            for ca in conflicting_assessments:
                limitations.append(f"Evidence '{ca.evidence_id}' explicitly flagged as CONFLICTING.")
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.CONFLICTING,
                evidence_references=visible_refs,
                evidence_assessments=visible_assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Conflicting evidence sources detected for target '{target_id}'. Corroboration cannot be fabricated.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 2. Metric value check if metric_key provided
        if metric_key:
            extracted_vals = []
            for a in visible_assessments:
                p = raw_payloads.get(a.evidence_id, {})
                v = p.get(metric_key)
                if isinstance(v, (int, float)):
                    extracted_vals.append((a.evidence_id, float(v)))

            if len(extracted_vals) >= 2:
                vals = [v for _, v in extracted_vals]
                min_v, max_v = min(vals), max(vals)
                rel_diff = (max_v - min_v) / (max(abs(min_v), 1e-9))
                if rel_diff > tolerance:
                    limitations.append(f"Metric '{metric_key}' values disagree beyond tolerance ({tolerance*100:.1f}%): min={min_v}, max={max_v}.")
                    return VerificationFinding(
                        finding_id=finding_id,
                        target_type=target_type,
                        target_id=target_id,
                        status=VerificationStatus.CONFLICTING,
                        evidence_references=visible_refs,
                        evidence_assessments=visible_assessments,
                        rule_id=self.rule_id,
                        rule_version=self.rule_version,
                        explanation=f"Evidence sources for target '{target_id}' disagree on metric '{metric_key}' ({min_v} vs {max_v}).",
                        limitations=limitations,
                        evaluated_at=now_iso,
                    )

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=visible_refs,
            evidence_assessments=visible_assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"Consistent agreement confirmed across {len(visible_assessments)} independent evidence sources for target '{target_id}'.",
            limitations=[],
            evaluated_at=now_iso,
        )



class VerificationRuleRegistry:
    """Canonical registry of supported, deterministic verification rules."""

    def __init__(self):
        self._rules: Dict[str, BaseDeterministicRule] = {}
        self._by_type: Dict[RuleType, BaseDeterministicRule] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        rules = [
            EvidenceExistsRule(),
            EvidenceValidatedRule(),
            EvidenceFreshRule(),
            RequiredEvidencePresentRule(),
            RequiredEvidenceValidatedRule(),
            EvidenceScopeMatchRule(),
            RequiredFieldsPresentRule(),
            SourceConsistencyRule(),
        ]
        for r in rules:
            self._rules[r.rule_id] = r
            self._by_type[r.rule_type] = r

    def get_rule(self, rule_id: str) -> Optional[BaseDeterministicRule]:
        return self._rules.get(rule_id)

    def get_rule_by_type(self, rule_type: RuleType) -> Optional[BaseDeterministicRule]:
        return self._by_type.get(rule_type)

    def list_rules(self) -> List[VerificationRule]:
        return [r.to_contract() for r in self._rules.values()]

    def is_supported(self, rule_id_or_type: str) -> bool:
        if rule_id_or_type in self._rules:
            return True
        try:
            rt = RuleType(rule_id_or_type)
            return rt in self._by_type
        except ValueError:
            return False


# Canonical singleton rule registry
verification_rule_registry = VerificationRuleRegistry()
