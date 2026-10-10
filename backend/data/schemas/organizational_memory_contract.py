# backend/data/schemas/organizational_memory_contract.py
"""
SageCommand V3 — Governed Organizational Memory Foundation Contracts (Prompt 34)

ADVISORY ORGANIZATIONAL MEMORY CONTEXT ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT,
OR BYPASSES OPERATIONAL GOVERNANCE.

Defines typed, validated domain models, lifecycle enums, epistemic distinctions, provenance references,
retention policies, and search/context assembly schemas for governed institutional memory.

Cardinal Invariants:
1. Organizational memory is evidence-bearing institutional context, NOT an authority to execute actions.
2. Memory entries NEVER mutate equipment, write to PLCs/SCADA, or bypass execution gateways.
3. Facts, claims, hypotheses, decisions, and outcomes are rigorously distinguished via EpistemicStatus.
4. Tenant, workspace, and plant isolation are strictly enforced server-side.
5. Lifecycle transitions require server-verified authorization; client flags cannot forge verification.
6. Superseded or archived entries are preserved with historical provenance and never silently overwritten.
7. Unassessable or uncalibrated confidence preserves NOT_ASSESSABLE rather than inventing scores.
8. Memory content is untrusted input; instructions inside entries cannot alter security policies.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone
import hashlib
import json
import re
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

# Re-use canonical evidence and confidence types from Prompt 31 and Prompt 32
try:
    from data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )
    from data.schemas.confidence_uncertainty_contract import (
        ConfidenceStatus,
        UncertaintyType,
    )
    from data.schemas.sop_rag_contract import ClassificationLevel
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceStatus,
        UncertaintyType,
    )
    from backend.data.schemas.sop_rag_contract import ClassificationLevel

# =============================================================================
# 0. CONSTANTS & MANDATORY NOTICE
# =============================================================================

MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE = (
    "ADVISORY ORGANIZATIONAL MEMORY CONTEXT ONLY — NEVER EXECUTES ACTIONS, "
    "MUTATES EQUIPMENT, OR BYPASSES OPERATIONAL GOVERNANCE."
)
CONTRACT_VERSION = "1.0.0"

MAX_MEMORY_ENTRY_SIZE_BYTES = 1048576  # 1 MB
MAX_TITLE_LENGTH = 256
MAX_SUMMARY_LENGTH = 2048
MAX_SEARCH_LIMIT = 50
DEFAULT_SEARCH_LIMIT = 10
MAX_CONTEXT_ITEMS = 10
MAX_CONTEXT_TOKENS = 4000


# =============================================================================
# 1. ENUMS
# =============================================================================

class MemoryType(str, Enum):
    """
    Explicit, validated allowlist for organizational memory categories.
    A type label does not itself imply that a claim is verified or approved.
    """
    OPERATIONAL_DECISION = "OPERATIONAL_DECISION"
    LESSON_LEARNED = "LESSON_LEARNED"
    VERIFIED_OUTCOME = "VERIFIED_OUTCOME"
    INCIDENT_LEARNING = "INCIDENT_LEARNING"
    ASSET_CONTEXT = "ASSET_CONTEXT"
    PROCESS_CONTEXT = "PROCESS_CONTEXT"
    CORRECTED_ASSUMPTION = "CORRECTED_ASSUMPTION"
    INVESTIGATION_FINDING = "INVESTIGATION_FINDING"
    ORGANIZATIONAL_PREFERENCE = "ORGANIZATIONAL_PREFERENCE"


class EpistemicStatus(str, Enum):
    """
    Rigorous epistemic category distinguishing facts, unverified assertions,
    hypotheses, recommendations, human decisions, and verified outcomes.
    Prevents unverified hypotheses or claims from masquerading as verified facts.
    """
    OBSERVED_FACT = "OBSERVED_FACT"              # Directly supported by an identified primary source
    REPORTED_CLAIM = "REPORTED_CLAIM"            # Asserted by a person or system, not independently verified
    HYPOTHESIS = "HYPOTHESIS"                    # Possible explanation that remains unconfirmed
    RECOMMENDATION = "RECOMMENDATION"            # Proposed course of action
    DECISION = "DECISION"                        # Decision attributable to an authorized human or governed process
    ATTEMPTED_ACTION = "ATTEMPTED_ACTION"        # Action reported or recorded as attempted
    VERIFIED_OUTCOME = "VERIFIED_OUTCOME"        # Outcome supported by appropriate post-action evidence
    CORRECTED_KNOWLEDGE = "CORRECTED_KNOWLEDGE"  # Information explicitly revised because later evidence changed the conclusion


class MemoryLifecycleStatus(str, Enum):
    """
    Deterministic lifecycle state of an organizational memory entry.
    """
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"


class VerificationStatus(str, Enum):
    """
    Independent verification status evaluated by authorized humans or verified systems.
    """
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CONTRADICTED = "CONTRADICTED"


class RelationshipType(str, Enum):
    """
    Explicit relationship between memory entries or external records.
    """
    RELATED_TO = "RELATED_TO"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"
    CORRECTS = "CORRECTS"
    DERIVED_FROM = "DERIVED_FROM"


class RetentionPolicy(str, Enum):
    """
    Data retention governance tiers.
    """
    STANDARD_7_YEARS = "STANDARD_7_YEARS"
    OPERATIONAL_1_YEAR = "OPERATIONAL_1_YEAR"
    CRITICAL_10_YEARS = "CRITICAL_10_YEARS"
    PERMANENT = "PERMANENT"
    CUSTOM = "CUSTOM"


# Allowed lifecycle transitions matrix
VALID_LIFECYCLE_TRANSITIONS: Dict[MemoryLifecycleStatus, Set[MemoryLifecycleStatus]] = {
    MemoryLifecycleStatus.DRAFT: {
        MemoryLifecycleStatus.PENDING_REVIEW,
        MemoryLifecycleStatus.VERIFIED,
        MemoryLifecycleStatus.ACTIVE,
        MemoryLifecycleStatus.ARCHIVED,
        MemoryLifecycleStatus.REVOKED,
    },
    MemoryLifecycleStatus.PENDING_REVIEW: {
        MemoryLifecycleStatus.VERIFIED,
        MemoryLifecycleStatus.ACTIVE,
        MemoryLifecycleStatus.REJECTED,
        MemoryLifecycleStatus.DRAFT,
        MemoryLifecycleStatus.REVOKED,
    },
    MemoryLifecycleStatus.VERIFIED: {
        MemoryLifecycleStatus.ACTIVE,
        MemoryLifecycleStatus.SUPERSEDED,
        MemoryLifecycleStatus.ARCHIVED,
        MemoryLifecycleStatus.REVOKED,
    },
    MemoryLifecycleStatus.ACTIVE: {
        MemoryLifecycleStatus.SUPERSEDED,
        MemoryLifecycleStatus.ARCHIVED,
        MemoryLifecycleStatus.REVOKED,
        MemoryLifecycleStatus.PENDING_REVIEW,
    },
    MemoryLifecycleStatus.SUPERSEDED: {
        MemoryLifecycleStatus.ARCHIVED,
        MemoryLifecycleStatus.REVOKED,
    },
    MemoryLifecycleStatus.REJECTED: {
        MemoryLifecycleStatus.DRAFT,
        MemoryLifecycleStatus.ARCHIVED,
        MemoryLifecycleStatus.REVOKED,
    },
    MemoryLifecycleStatus.ARCHIVED: {
        # Terminal state under standard governance
    },
    MemoryLifecycleStatus.REVOKED: {
        # Terminal state under standard governance
    },
}


# =============================================================================
# 2. PROVENANCE & RELATIONSHIP SCHEMAS
# =============================================================================

class SourceReference(BaseModel):
    """
    Durable reference to an authoritative source record.
    Preserves origin without copying large document bodies.
    """
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, max_length=128, description="Stable identifier of the source record")
    source_type: str = Field(..., min_length=1, max_length=64, description="Type: INCIDENT, RCA, DECISION, SOP, TELEMETRY, MANUAL")
    source_uri_or_path: Optional[str] = Field(None, max_length=512, description="URI, file path, or database route")
    source_version: Optional[str] = Field(None, max_length=64, description="Version or revision of the source")
    source_title: Optional[str] = Field(None, max_length=256, description="Descriptive title of the source")
    source_confidence_status: Optional[ConfidenceStatus] = Field(
        default=ConfidenceStatus.NOT_ASSESSABLE,
        description="Assessed confidence of the source record itself"
    )
    notes: Optional[str] = Field(None, max_length=1024, description="Limitation or provenance context notes")


class MemoryRelationship(BaseModel):
    """
    Explicit, directed relationship between organizational memory records.
    """
    model_config = ConfigDict(extra="forbid")

    target_memory_id: str = Field(..., min_length=1, max_length=128)
    relationship_type: RelationshipType
    description: Optional[str] = Field(None, max_length=1024)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = Field(..., min_length=1, max_length=128)


# =============================================================================
# 3. CORE DOMAIN MODEL
# =============================================================================

class OrganizationalMemoryEntry(BaseModel):
    """
    Governed organizational memory entry.
    Represents institutional knowledge with full provenance, scope, lifecycle,
    and confidence metadata.
    """
    model_config = ConfigDict(extra="forbid")

    # Identifiers & Isolation Scope
    memory_id: str = Field(..., min_length=1, max_length=128, description="Unique memory entry ID (mem-...)")
    tenant_id: str = Field(..., min_length=1, max_length=64, description="Server-derived tenant ID")
    workspace_id: str = Field(..., min_length=1, max_length=64, description="Authoritative workspace ID")
    plant_id: str = Field(..., min_length=1, max_length=64, description="Authoritative plant ID")
    asset_id: Optional[str] = Field(None, max_length=64, description="Optional associated asset ID")
    process_id: Optional[str] = Field(None, max_length=64, description="Optional associated process/unit ID")
    session_id: Optional[str] = Field(None, max_length=64, description="Originating session reference (reference only)")

    # Classification & Governance
    classification: ClassificationLevel = Field(
        default=ClassificationLevel.INTERNAL,
        description="Data classification level enforcing clearance checks"
    )
    memory_type: MemoryType = Field(..., description="Categorical type of organizational memory")
    epistemic_status: EpistemicStatus = Field(
        default=EpistemicStatus.REPORTED_CLAIM,
        description="Epistemic distinction (Fact, Claim, Hypothesis, Decision, Outcome)"
    )
    lifecycle_status: MemoryLifecycleStatus = Field(
        default=MemoryLifecycleStatus.DRAFT,
        description="Current lifecycle state"
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Verification state"
    )

    # Core Knowledge Content
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LENGTH)
    summary: str = Field(..., min_length=1, max_length=MAX_SUMMARY_LENGTH)
    content: str = Field(..., min_length=1, max_length=MAX_MEMORY_ENTRY_SIZE_BYTES)
    tags: List[str] = Field(default_factory=list, max_length=32)

    # Provenance and Linked Records
    source_references: List[SourceReference] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list, description="IDs of Prompt 31 EvidenceRecords")
    decision_reference: Optional[str] = Field(None, max_length=128, description="Related decision ID")
    incident_reference: Optional[str] = Field(None, max_length=128, description="Related incident ID")
    rca_reference: Optional[str] = Field(None, max_length=128, description="Related root cause investigation ID")
    sop_reference: Optional[str] = Field(None, max_length=128, description="Related SOP document ID")
    relationships: List[MemoryRelationship] = Field(default_factory=list)

    # Versioning & Supersession
    supersedes_memory_id: Optional[str] = Field(None, max_length=128, description="ID of memory superseded by this entry")
    superseded_by_memory_id: Optional[str] = Field(None, max_length=128, description="ID of memory superseding this entry")
    revision: int = Field(default=1, ge=1)

    # Confidence and Uncertainty Integration
    confidence_status: ConfidenceStatus = Field(
        default=ConfidenceStatus.NOT_ASSESSABLE,
        description="Assessed confidence from Prompt 32 contract"
    )
    uncertainty_types: List[UncertaintyType] = Field(
        default_factory=list,
        description="Classified uncertainty dimensions from Prompt 32"
    )
    uncertainty_notes: Optional[str] = Field(None, max_length=1024)

    # Retention Governance
    retention_policy: str = Field(default="STANDARD_7_YEARS", max_length=64)
    is_hold: bool = Field(default=False, description="Legal/operational hold flag preventing deletion or premature archival")
    hold_reason: Optional[str] = Field(None, max_length=512)

    # Temporal Timestamps
    event_timestamp: Optional[datetime] = Field(None, description="When the described physical event occurred")
    valid_from: Optional[datetime] = Field(None, description="Validity start window")
    valid_until: Optional[datetime] = Field(None, description="Validity expiration window")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verified_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None

    # Actors
    created_by: str = Field(..., min_length=1, max_length=128)
    verified_by: Optional[str] = Field(None, max_length=128)
    superseded_by: Optional[str] = Field(None, max_length=128)
    archived_by: Optional[str] = Field(None, max_length=128)

    # Advisory notice & custom metadata
    advisory_notice: str = Field(default=MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_MEMORY_ENTRY_SIZE_BYTES:
            raise ValueError(f"Content exceeds maximum allowed size of {MAX_MEMORY_ENTRY_SIZE_BYTES} bytes")
        return v

    @model_validator(mode="after")
    def validate_epistemic_and_verification_coherence(self) -> "OrganizationalMemoryEntry":
        # Verification coherence: if verified, verified_by and verified_at should be present
        if self.verification_status == VerificationStatus.VERIFIED:
            if not self.verified_by:
                raise ValueError("Verification status is VERIFIED but verified_by actor is missing")
        # Fact upgrade protection: an OBSERVED_FACT must have at least one source reference or evidence reference
        if self.epistemic_status == EpistemicStatus.OBSERVED_FACT:
            if not self.source_references and not self.evidence_references:
                raise ValueError("OBSERVED_FACT requires at least one source reference or evidence reference")
        # Superseded entries must not remain in ACTIVE lifecycle
        if self.superseded_by_memory_id and self.lifecycle_status == MemoryLifecycleStatus.ACTIVE:
            raise ValueError("Superseded entry cannot remain in ACTIVE lifecycle status")
        return self


# =============================================================================
# 4. REQUEST AND RESPONSE CONTRACTS
# =============================================================================

class MemoryDraftCreateRequest(BaseModel):
    """
    Request to create a new draft organizational memory entry.
    Client-provided parameters are restricted: clients CANNOT specify verified status,
    privileged lifecycle status, or fake approval identities.
    """
    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LENGTH)
    summary: str = Field(..., min_length=1, max_length=MAX_SUMMARY_LENGTH)
    content: str = Field(..., min_length=1, max_length=MAX_MEMORY_ENTRY_SIZE_BYTES)
    epistemic_status: EpistemicStatus = Field(default=EpistemicStatus.REPORTED_CLAIM)
    classification: ClassificationLevel = Field(default=ClassificationLevel.INTERNAL)

    # Scoping context (will be validated against caller's authoritative identity)
    plant_id: Optional[str] = Field(None, max_length=64)
    asset_id: Optional[str] = Field(None, max_length=64)
    process_id: Optional[str] = Field(None, max_length=64)
    session_id: Optional[str] = Field(None, max_length=64)

    # References
    source_references: List[SourceReference] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)
    decision_reference: Optional[str] = Field(None, max_length=128)
    incident_reference: Optional[str] = Field(None, max_length=128)
    rca_reference: Optional[str] = Field(None, max_length=128)
    sop_reference: Optional[str] = Field(None, max_length=128)

    # Confidence and uncertainty assertions
    confidence_status: Optional[ConfidenceStatus] = Field(default=ConfidenceStatus.NOT_ASSESSABLE)
    uncertainty_types: List[UncertaintyType] = Field(default_factory=list)
    uncertainty_notes: Optional[str] = Field(None, max_length=1024)

    # Governance & Timing
    retention_policy: str = Field(default="STANDARD_7_YEARS", max_length=64)
    event_timestamp: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryDraftUpdateRequest(BaseModel):
    """
    Request to update an existing DRAFT memory entry.
    Only draft entries can be edited. Active or verified entries must be superseded.
    """
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=MAX_TITLE_LENGTH)
    summary: Optional[str] = Field(None, min_length=1, max_length=MAX_SUMMARY_LENGTH)
    content: Optional[str] = Field(None, min_length=1, max_length=MAX_MEMORY_ENTRY_SIZE_BYTES)
    memory_type: Optional[MemoryType] = None
    epistemic_status: Optional[EpistemicStatus] = None
    classification: Optional[ClassificationLevel] = None
    asset_id: Optional[str] = Field(None, max_length=64)
    process_id: Optional[str] = Field(None, max_length=64)
    source_references: Optional[List[SourceReference]] = None
    evidence_references: Optional[List[str]] = None
    decision_reference: Optional[str] = None
    incident_reference: Optional[str] = None
    rca_reference: Optional[str] = None
    sop_reference: Optional[str] = None
    confidence_status: Optional[ConfidenceStatus] = None
    uncertainty_types: Optional[List[UncertaintyType]] = None
    uncertainty_notes: Optional[str] = None
    retention_policy: Optional[str] = None
    event_timestamp: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class MemoryVerifyRequest(BaseModel):
    """
    Privileged request to verify an organizational memory entry.
    Requires server-verified authority (e.g. memory.verify permission).
    """
    model_config = ConfigDict(extra="forbid")

    verification_status: VerificationStatus = Field(default=VerificationStatus.VERIFIED)
    verification_notes: Optional[str] = Field(None, max_length=1024)
    confidence_status: Optional[ConfidenceStatus] = None
    activate_immediately: bool = Field(default=True, description="Transition directly from VERIFIED to ACTIVE")


class MemorySupersedeRequest(BaseModel):
    """
    Request to supersede an existing memory entry with a new entry or reference.
    Preserves historical memory and establishes an explicit relationship.
    """
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=1024, description="Justification for superseding prior knowledge")
    replacement_draft: Optional[MemoryDraftCreateRequest] = Field(
        None,
        description="Optional payload to create replacement entry atomically"
    )
    replacement_memory_id: Optional[str] = Field(
        None,
        max_length=128,
        description="ID of existing entry that supersedes this entry"
    )


class MemoryArchiveRequest(BaseModel):
    """
    Request to archive a memory entry.
    """
    model_config = ConfigDict(extra="forbid")

    archive_reason: str = Field(..., min_length=1, max_length=1024)


class MemorySearchRequest(BaseModel):
    """
    Deterministic, bounded search request for organizational memory.
    """
    model_config = ConfigDict(extra="forbid")

    query: Optional[str] = Field(None, max_length=256, description="Lexical search terms")
    memory_type: Optional[MemoryType] = None
    epistemic_status: Optional[EpistemicStatus] = None
    lifecycle_status: Optional[MemoryLifecycleStatus] = None
    verification_status: Optional[VerificationStatus] = None
    plant_id: Optional[str] = Field(None, max_length=64)
    asset_id: Optional[str] = Field(None, max_length=64)
    process_id: Optional[str] = Field(None, max_length=64)
    incident_reference: Optional[str] = Field(None, max_length=128)
    decision_reference: Optional[str] = Field(None, max_length=128)
    tag: Optional[str] = Field(None, max_length=64)
    valid_at: Optional[datetime] = Field(None, description="Temporal filter: must be valid at this timestamp")
    include_superseded: bool = Field(default=False)
    include_archived: bool = Field(default=False)
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)
    offset: int = Field(default=0, ge=0)


class MemorySearchResponse(BaseModel):
    """
    Response containing bounded, authorized search results.
    """
    model_config = ConfigDict(extra="forbid")

    entries: List[OrganizationalMemoryEntry]
    total_count: int
    returned_count: int
    offset: int
    limit: int
    has_more: bool
    advisory_notice: str = MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE


# =============================================================================
# 5. AI CONTEXT ASSEMBLY CONTRACTS
# =============================================================================

class MemoryContextAssemblyRequest(BaseModel):
    """
    Request to assemble bounded, safe organizational memory context for the AI layer.
    """
    model_config = ConfigDict(extra="forbid")

    plant_id: Optional[str] = Field(None, max_length=64)
    asset_id: Optional[str] = Field(None, max_length=64)
    process_id: Optional[str] = Field(None, max_length=64)
    incident_reference: Optional[str] = Field(None, max_length=128)
    decision_reference: Optional[str] = Field(None, max_length=128)
    query: Optional[str] = Field(None, max_length=256)
    memory_types: Optional[List[MemoryType]] = None
    max_items: int = Field(default=MAX_CONTEXT_ITEMS, ge=1, le=MAX_CONTEXT_ITEMS)
    max_tokens: int = Field(default=MAX_CONTEXT_TOKENS, ge=100, le=MAX_CONTEXT_TOKENS)


class MemoryContextItem(BaseModel):
    """
    Sanitized, bounded summary of an authorized memory item for AI context assembly.
    Excludes internal infrastructure details and sensitive credentials.
    """
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    memory_type: MemoryType
    epistemic_status: EpistemicStatus
    lifecycle_status: MemoryLifecycleStatus
    verification_status: VerificationStatus
    title: str
    summary: str
    content_snippet: str
    confidence_status: ConfidenceStatus
    uncertainty_notes: Optional[str] = None
    event_timestamp: Optional[str] = None
    created_at: str
    source_references: List[Dict[str, Any]]
    limitations: List[str]


class MemoryContextResponse(BaseModel):
    """
    Structured context packet ready for injection into AI reasoning prompts.
    Enclosed within strict safety boundaries and explicit untrusted data markers.
    """
    model_config = ConfigDict(extra="forbid")

    context_items: List[MemoryContextItem]
    item_count: int
    estimated_tokens: int
    formatted_prompt_block: str
    advisory_notice: str = MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE
    is_sufficient: bool = True
    unresolved_conflicts: List[str] = Field(default_factory=list)


# =============================================================================
# 6. AUDIT CONTRACT
# =============================================================================

class MemoryAuditRecord(BaseModel):
    """
    Audit ledger entry for organizational memory events.
    Enforces non-repudiation and lifecycle governance.
    """
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(..., min_length=1, max_length=128)
    event_type: str = Field(..., min_length=1, max_length=64)
    memory_id: str = Field(..., min_length=1, max_length=128)
    tenant_id: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(..., min_length=1, max_length=64)
    plant_id: str = Field(..., min_length=1, max_length=64)
    actor_id: str = Field(..., min_length=1, max_length=128)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    outcome: str = Field(default="SUCCESS", max_length=32)
    details: Dict[str, Any] = Field(default_factory=dict)
    advisory_notice: str = MANDATORY_ORGANIZATIONAL_MEMORY_NOTICE
