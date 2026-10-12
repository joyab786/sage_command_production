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

        # Filter to accessible, scope-authorized items
        authorized = [
            a for a in assessments
            if a.scope_status == ScopeStatus.AUTHORIZED and a.applicability_status == "APPLICABLE"
        ]

        if not authorized:
            for a in assessments:
                if a.scope_status != ScopeStatus.AUTHORIZED:
                    limitations.append(f"Evidence '{a.evidence_id}' rejected due to scope boundary violation: {a.scope_status.value}.")
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Evidence exists for target '{target_id}' but was rejected due to scope boundary isolation.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        ev_ids = [a.evidence_id for a in authorized]
        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=ev_ids,
            evidence_assessments=assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"Found {len(authorized)} authorized evidence item(s) supporting target '{target_id}'.",
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
                explanation=f"No evidence records available to validate for target '{target_id}'.",
                limitations=["Missing evidence records."],
                evaluated_at=now_iso,
            )

        invalid_items = [a for a in assessments if a.integrity_status.upper() == "INVALID" or a.quality_status == QualityStatus.INVALID]
        unverified_items = [a for a in assessments if a.integrity_status.upper() == "UNVERIFIED" or a.quality_status == QualityStatus.UNVERIFIED]
        valid_items = [a for a in assessments if a.integrity_status.upper() == "VALID" or a.quality_status == QualityStatus.VALID]

        if invalid_items:
            for inv in invalid_items:
                limitations.append(f"Evidence '{inv.evidence_id}' failed cryptographic or schema integrity check.")
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' contains {len(invalid_items)} INVALID evidence record(s). Cannot establish verification.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        if unverified_items and not valid_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"All evidence records for target '{target_id}' are UNVERIFIED; validation has not been performed.",
                limitations=["Evidence integrity unverified."],
                evaluated_at=now_iso,
            )

        if unverified_items and valid_items:
            limitations.append(f"{len(unverified_items)} evidence item(s) remain unverified.")

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=[a.evidence_id for a in assessments],
            evidence_assessments=assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"Validated {len(valid_items)} evidence item(s) supporting target '{target_id}'.",
            limitations=limitations,
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

        stale_items = []
        missing_ts_items = []
        future_items = []
        fresh_items = []

        for a in assessments:
            a.freshness_threshold_seconds = threshold
            obs_dt = _parse_iso_timestamp(a.observed_at)
            if not obs_dt:
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
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' contains future-dated evidence timestamps. Cannot certify freshness.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        if stale_items and not fresh_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.STALE,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"All available evidence for target '{target_id}' is STALE beyond allowed window ({threshold:.0f}s).",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        if missing_ts_items and not fresh_items:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Evidence for target '{target_id}' is missing observation timestamps. Freshness cannot be determined.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        if fresh_items:
            status = VerificationStatus.VERIFIED
            explanation = f"Found {len(fresh_items)} fresh evidence record(s) within threshold ({threshold:.0f}s) for target '{target_id}'."
        else:
            status = VerificationStatus.NOT_VERIFIED
            explanation = f"No fresh evidence satisfied freshness requirements for target '{target_id}'."

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=status,
            evidence_references=[a.evidence_id for a in assessments],
            evidence_assessments=assessments,
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

        if not required_types and not required_ids:
            # Fallback: at least one evidence item must be present
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
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.VERIFIED,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"All general evidence requirements met for target '{target_id}'.",
                limitations=[],
                evaluated_at=now_iso,
            )

        present_types = {a.source_type.upper() for a in assessments}
        present_ids = {a.evidence_id for a in assessments}

        missing_types = [t for t in required_types if t.upper() not in present_types]
        missing_ids = [i for i in required_ids if i not in present_ids]

        if missing_types or missing_ids:
            if missing_types:
                limitations.append(f"Missing required evidence types: {missing_types}.")
            if missing_ids:
                limitations.append(f"Missing required evidence IDs: {missing_ids}.")

            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
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
            evidence_references=[a.evidence_id for a in assessments],
            evidence_assessments=assessments,
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
                explanation=f"No evidence available for target '{target_id}'.",
                limitations=["Missing evidence records."],
                evaluated_at=now_iso,
            )

        invalid = [a for a in assessments if a.integrity_status.upper() != "VALID"]
        if invalid:
            for inv in invalid:
                limitations.append(f"Evidence '{inv.evidence_id}' has integrity status '{inv.integrity_status}'.")
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.NOT_VERIFIED,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' has {len(invalid)} unvalidated or invalid evidence item(s).",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=[a.evidence_id for a in assessments],
            evidence_assessments=assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"All {len(assessments)} supporting evidence record(s) are present and validated for target '{target_id}'.",
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

        scope_violations = []
        for a in assessments:
            if a.scope_status != ScopeStatus.AUTHORIZED:
                scope_violations.append(a)
                limitations.append(f"Evidence '{a.evidence_id}' scope status is '{a.scope_status.value}'.")

        if scope_violations:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.BLOCKED,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Target '{target_id}' blocked due to {len(scope_violations)} scope boundary violation(s).",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        return VerificationFinding(
            finding_id=finding_id,
            target_type=target_type,
            target_id=target_id,
            status=VerificationStatus.VERIFIED,
            evidence_references=[a.evidence_id for a in assessments],
            evidence_assessments=assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"All {len(assessments)} evidence item(s) strictly match tenant, workspace, and plant boundaries.",
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

        raw_payloads = parameters.get("evidence_payloads", {})

        missing_fields_total = []
        for a in assessments:
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
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
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
            evidence_references=[a.evidence_id for a in assessments],
            evidence_assessments=assessments,
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

        if len(assessments) < 2:
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.INDETERMINATE,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Only {len(assessments)} source(s) available for target '{target_id}'. Multi-source consistency requires at least 2 independent sources.",
                limitations=["Insufficient corroborating sources."],
                evaluated_at=now_iso,
            )

        # Check for explicit conflict flags or payload values comparison
        raw_payloads = parameters.get("evidence_payloads", {})
        metric_key = parameters.get("metric_key")
        tolerance = float(parameters.get("tolerance", 0.05))

        # 1. QualityStatus check
        conflicting_assessments = [a for a in assessments if a.quality_status == QualityStatus.CONFLICTING]
        if conflicting_assessments:
            for ca in conflicting_assessments:
                limitations.append(f"Evidence '{ca.evidence_id}' explicitly flagged as CONFLICTING.")
            return VerificationFinding(
                finding_id=finding_id,
                target_type=target_type,
                target_id=target_id,
                status=VerificationStatus.CONFLICTING,
                evidence_references=[a.evidence_id for a in assessments],
                evidence_assessments=assessments,
                rule_id=self.rule_id,
                rule_version=self.rule_version,
                explanation=f"Conflicting evidence sources detected for target '{target_id}'. Corroboration cannot be fabricated.",
                limitations=limitations,
                evaluated_at=now_iso,
            )

        # 2. Metric value check if metric_key provided
        if metric_key:
            extracted_vals = []
            for a in assessments:
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
                        evidence_references=[a.evidence_id for a in assessments],
                        evidence_assessments=assessments,
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
            evidence_references=[a.evidence_id for a in assessments],
            evidence_assessments=assessments,
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            explanation=f"Consistent agreement confirmed across {len(assessments)} independent evidence sources for target '{target_id}'.",
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
