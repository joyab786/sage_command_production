# backend/data/schemas/sop_rag_contract.py
"""
SageCommand V3 — SOP / Retrieval-Augmented Generation (RAG) Intelligence Foundation Contracts (Prompt 33)

ADVISORY SOP KNOWLEDGE ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT, OR BYPASSES OPERATIONAL GOVERNANCE.
Defines typed, validated contracts for the SOP lifecycle, document chunking, secure retrieval,
source citations, and evidence-backed RAG query/answer orchestration:
SOPDocument, DocumentChunk, DocumentLifecycleStatus, DocumentType, OperationalDomain,
ClassificationLevel, DocumentApprovalMetadata, DocumentProvenanceInfo, IngestionRequest,
IngestionResult, RetrievalRequest, Citation, RetrievalResponse, RAGQueryRequest, RAGAnswer,
EvidenceSufficiencyStatus, ModelProviderType, and SOPAuditRecord.

Cardinal Invariants:
1. RAG is an ADVISORY knowledge retrieval layer, NEVER an execution or actuation layer.
2. It NEVER triggers PLCs, modifies setpoints, executes work orders, or bypasses authorization.
3. Tenant isolation and document classification boundaries are strictly enforced at server side.
   Client-supplied tenant or user identifiers must never override authenticated identity.
4. Citations must map strictly to real retrieved source passages. Unknown metadata remains explicitly unknown.
5. Incomplete, draft, superseded, or revoked SOPs must not be silently treated as authoritative published guidance.
6. When evidence is insufficient, answers must be refused or flagged INSUFFICIENT; confidence is NOT_ASSESSABLE.

Notice:
ADVISORY SOP KNOWLEDGE ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT, OR BYPASSES OPERATIONAL GOVERNANCE
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
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
        EvidenceValidationStatus,
    )
    from data.schemas.confidence_uncertainty_contract import (
        ConfidenceUncertaintyResult,
        ConfidenceStatus,
        UncertaintyType,
    )
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
        EvidenceValidationStatus,
    )
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceUncertaintyResult,
        ConfidenceStatus,
        UncertaintyType,
    )


# =============================================================================
# 0. CONSTANTS & MANDATORY ADVISORY NOTICE
# =============================================================================

MANDATORY_SOP_RAG_NOTICE = (
    "ADVISORY SOP KNOWLEDGE ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT, OR BYPASSES OPERATIONAL GOVERNANCE"
)
CONTRACT_VERSION = "1.0.0"

FORBIDDEN_EXECUTION_KEYWORDS = {
    "EXECUTE",
    "DISPATCH",
    "ACTUATE",
    "WRITE_PLC",
    "MUTATE",
    "SUBMIT_ORDER",
    "EXECUTE_WORK_ORDER",
    "TRIGGER_ACTION",
    "EVAL",
    "EXEC",
    "__IMPORT__",
    "OS.SYSTEM",
    "SUBPROCESS",
}


# =============================================================================
# 1. ENUMS
# =============================================================================

class DocumentLifecycleStatus(str, Enum):
    """
    Formal lifecycle state of an SOP document.
    Prevents draft, superseded, or revoked documents from masquerading as authoritative active guidance.
    """
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    REVOKED = "REVOKED"
    FAILED_INGESTION = "FAILED_INGESTION"


class DocumentType(str, Enum):
    """
    Standard industrial document classification.
    """
    STANDARD_OPERATING_PROCEDURE = "STANDARD_OPERATING_PROCEDURE"
    SAFETY_GUIDELINE = "SAFETY_GUIDELINE"
    EMERGENCY_PROCEDURE = "EMERGENCY_PROCEDURE"
    MAINTENANCE_MANUAL = "MAINTENANCE_MANUAL"
    EQUIPMENT_SPECIFICATION = "EQUIPMENT_SPECIFICATION"
    WORK_INSTRUCTION = "WORK_INSTRUCTION"
    COMPLIANCE_POLICY = "COMPLIANCE_POLICY"
    OPERATING_LIMITS = "OPERATING_LIMITS"
    TROUBLESHOOTING_GUIDE = "TROUBLESHOOTING_GUIDE"
    INCIDENT_PLAYBOOK = "INCIDENT_PLAYBOOK"


class OperationalDomain(str, Enum):
    """
    Industrial domain of applicability.
    """
    PRODUCTION = "PRODUCTION"
    MAINTENANCE = "MAINTENANCE"
    SAFETY = "SAFETY"
    QUALITY = "QUALITY"
    FACILITIES = "FACILITIES"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    GENERAL = "GENERAL"


class ClassificationLevel(str, Enum):
    """
    Data classification and access security tier.
    """
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class EvidenceSufficiencyStatus(str, Enum):
    """
    Evaluated sufficiency of retrieved evidence relative to the query.
    """
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICTING = "CONFLICTING"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NO_RELEVANT_PASSAGES = "NO_RELEVANT_PASSAGES"
    GENERATION_UNAVAILABLE = "GENERATION_UNAVAILABLE"


class ModelProviderType(str, Enum):
    """
    Identifies the underlying model generation abstraction.
    """
    NONE = "NONE"
    LOCAL_HEURISTIC = "LOCAL_HEURISTIC"
    RETRIEVAL_ONLY = "RETRIEVAL_ONLY"
    GEMINI_SIMULATED = "GEMINI_SIMULATED"
    EXTERNAL_LLM = "EXTERNAL_LLM"


class FreshnessStatus(str, Enum):
    """
    Freshness and temporal validity classification of retrieved documentation.
    """
    CURRENT = "CURRENT"
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"
    EXPIRED = "EXPIRED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# 2. DOCUMENT GOVERNANCE & METADATA CONTRACTS
# =============================================================================

class DocumentApprovalMetadata(BaseModel):
    """
    Authoritative governance approval record.
    Never invent approvals; unverified metadata must remain explicitly unknown.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    approved_by: Optional[str] = Field(default=None, description="Identity of approving authority")
    approval_timestamp: Optional[str] = Field(default=None, description="ISO timestamp of governance approval")
    approval_id: Optional[str] = Field(default=None, description="Unique governance approval reference ID")
    approval_role: Optional[str] = Field(default=None, description="Role of the approving authority")
    is_verified: bool = Field(default=False, description="Whether approval has been cryptographically or administratively verified")


class DocumentProvenanceInfo(BaseModel):
    """
    Origin, ingestion method, and lineage metadata for an SOP document.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_identifier: str = Field(..., description="Stable identifier of the source file or document")
    source_uri: Optional[str] = Field(default=None, description="Source URI or repository location")
    source_format: str = Field(default="text/plain", description="MIME type or file format (e.g., text/plain, text/markdown)")
    ingested_by: str = Field(..., description="Actor identity performing ingestion")
    ingestion_timestamp: str = Field(..., description="ISO timestamp of ingestion")
    content_fingerprint: str = Field(..., description="SHA-256 fingerprint of the authoritative content")
    provenance_type: EvidenceProvenance = Field(default=EvidenceProvenance.OBSERVED, description="Provenance classification")
    limitations: List[str] = Field(default_factory=list, description="Known limitations or gaps in provenance")


# =============================================================================
# 3. DOCUMENT CHUNK CONTRACT
# =============================================================================

class DocumentChunk(BaseModel):
    """
    A bounded, deterministic text segment extracted from an authoritative SOP document.
    Maintains rigorous backward traceability to the parent document and exact version.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(..., description="Stable chunk identifier (doc_id:version:idx:hash)")
    document_id: str = Field(..., description="Parent document ID")
    document_version: str = Field(..., description="Exact parent document version")
    chunk_index: int = Field(..., ge=0, description="0-indexed position of chunk in the document")
    content: str = Field(..., min_length=1, description="Chunk text content")
    section_heading: Optional[str] = Field(default=None, description="Nearest section heading or header context")
    page_number: Optional[int] = Field(default=None, ge=1, description="Source page number where available")
    content_digest: str = Field(..., description="SHA-256 hash of the chunk content")
    tenant_id: str = Field(..., description="Tenant scope inherited from parent document")
    plant_id: Optional[str] = Field(default=None, description="Plant scope inherited from parent document")
    classification: ClassificationLevel = Field(default=ClassificationLevel.INTERNAL, description="Classification tier inherited from parent")
    access_control_roles: List[str] = Field(default_factory=list, description="Permitted roles inherited from parent")
    lifecycle_status: DocumentLifecycleStatus = Field(default=DocumentLifecycleStatus.PUBLISHED, description="Lifecycle status inherited from parent")
    char_count: int = Field(..., ge=1, description="Character count of chunk text")
    token_count_estimate: int = Field(..., ge=1, description="Estimated token count (approx. words / 0.75)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extracted domain tags or operational metadata")

    @field_validator("chunk_id", "document_id", "tenant_id", "content_digest")
    @classmethod
    def validate_non_empty_strings(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be empty or whitespace.")
        return v.strip()


# =============================================================================
# 4. AUTHORITATIVE SOP DOCUMENT CONTRACT
# =============================================================================

class SOPDocument(BaseModel):
    """
    Authoritative Standard Operating Procedure or industrial guidance document.
    Represents complete metadata, governance lifecycle, access boundaries, and integrity digests.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(..., description="Stable unique document identifier")
    tenant_id: str = Field(..., description="Tenant/organization scope")
    plant_id: Optional[str] = Field(default=None, description="Plant/site partition where applicable")
    title: str = Field(..., min_length=1, max_length=500, description="Document title")
    description: Optional[str] = Field(default=None, max_length=2000, description="Brief synopsis or scope of procedure")
    document_type: DocumentType = Field(default=DocumentType.STANDARD_OPERATING_PROCEDURE, description="Functional document classification")
    operational_domain: OperationalDomain = Field(default=OperationalDomain.GENERAL, description="Operational industrial domain")
    version: str = Field(default="1.0", description="Document revision identifier")
    lifecycle_status: DocumentLifecycleStatus = Field(default=DocumentLifecycleStatus.PUBLISHED, description="Lifecycle governance status")
    effective_from: Optional[str] = Field(default=None, description="ISO timestamp from which procedure is effective")
    effective_until: Optional[str] = Field(default=None, description="ISO timestamp after which procedure is superseded or invalid")
    approval_metadata: Optional[DocumentApprovalMetadata] = Field(default=None, description="Governance approval record")
    classification: ClassificationLevel = Field(default=ClassificationLevel.INTERNAL, description="Data classification and access control tier")
    access_control_roles: List[str] = Field(default_factory=list, description="Roles permitted to view or retrieve this document")
    content_digest: str = Field(..., description="SHA-256 fingerprint of the normalized text content")
    raw_text: Optional[str] = Field(default=None, description="Authoritative normalized full document text")
    provenance_info: DocumentProvenanceInfo = Field(..., description="Origin and ingestion lineage")
    chunks: List[DocumentChunk] = Field(default_factory=list, description="Deterministic chunk segments")
    total_chunks: int = Field(default=0, ge=0, description="Total count of generated chunks")
    created_at: str = Field(..., description="Creation ISO timestamp")
    updated_at: str = Field(..., description="Last update ISO timestamp")
    is_valid: bool = Field(default=True, description="Whether document passed all ingestion validation gates")
    validation_errors: List[str] = Field(default_factory=list, description="Validation failures if incomplete or invalid")
    advisory_notice: str = Field(default=MANDATORY_SOP_RAG_NOTICE, description="Mandatory non-execution advisory disclaimer")

    @field_validator("document_id", "tenant_id", "title")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be empty or whitespace.")
        return v.strip()


# =============================================================================
# 5. INGESTION REQUEST & RESULT CONTRACTS
# =============================================================================

class IngestionRequest(BaseModel):
    """
    Validated payload for ingesting, validating, chunking, and registering an SOP document.
    Tenant context is always bound by the authenticated server session.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(..., min_length=1, max_length=128, description="Target document identifier")
    tenant_id: Optional[str] = Field(default=None, description="Caller-supplied tenant ID (validated against server identity)")
    plant_id: Optional[str] = Field(default=None, description="Optional plant partition")
    title: str = Field(..., min_length=1, max_length=500, description="Document title")
    description: Optional[str] = Field(default=None, max_length=2000, description="Document description")
    document_type: DocumentType = Field(default=DocumentType.STANDARD_OPERATING_PROCEDURE, description="Functional type")
    operational_domain: OperationalDomain = Field(default=OperationalDomain.GENERAL, description="Domain")
    version: str = Field(default="1.0", max_length=32, description="Version string")
    lifecycle_status: DocumentLifecycleStatus = Field(default=DocumentLifecycleStatus.PUBLISHED, description="Initial lifecycle status")
    effective_from: Optional[str] = Field(default=None, description="ISO timestamp effective start")
    effective_until: Optional[str] = Field(default=None, description="ISO timestamp effective end")
    approval_metadata: Optional[DocumentApprovalMetadata] = Field(default=None, description="Approval governance")
    classification: ClassificationLevel = Field(default=ClassificationLevel.INTERNAL, description="Classification level")
    access_control_roles: List[str] = Field(default_factory=list, description="Access control roles")
    content: str = Field(..., min_length=1, description="Raw document text content")
    source_uri: Optional[str] = Field(default=None, description="Source URI or repository path")
    source_format: str = Field(default="text/plain", description="Document source format")
    chunk_size_chars: Optional[int] = Field(default=None, ge=100, le=10000, description="Override chunk size in characters")
    chunk_overlap_chars: Optional[int] = Field(default=None, ge=0, le=1000, description="Override chunk overlap in characters")

    @field_validator("content")
    @classmethod
    def validate_content_safety(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Document content must not be empty or whitespace.")
        # Reject null bytes
        if "\x00" in v:
            raise ValueError("Document content contains illegal null bytes.")
        return v


class IngestionResult(BaseModel):
    """
    Deterministic result of document ingestion.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(..., description="Ingested document identifier")
    version: str = Field(..., description="Document revision")
    tenant_id: str = Field(..., description="Tenant scope")
    lifecycle_status: DocumentLifecycleStatus = Field(..., description="Final lifecycle status")
    total_chunks: int = Field(..., ge=0, description="Number of chunks created and indexed")
    content_digest: str = Field(..., description="SHA-256 fingerprint of content")
    is_duplicate: bool = Field(default=False, description="True if identical content already existed for this version")
    is_revision: bool = Field(default=False, description="True if a new revision of an existing document")
    ingestion_status: str = Field(..., description="SUCCESS, UNCHANGED_DUPLICATE, or FAILED")
    validation_errors: List[str] = Field(default_factory=list, description="Validation issues if any")
    ingested_at: str = Field(..., description="ISO timestamp of completion")
    advisory_notice: str = Field(default=MANDATORY_SOP_RAG_NOTICE, description="Mandatory non-execution advisory notice")


# =============================================================================
# 6. RETRIEVAL REQUEST & CITATION CONTRACTS
# =============================================================================

class RetrievalRequest(BaseModel):
    """
    Scoped, validated retrieval query against eligible SOP documents and chunks.
    All authorization boundaries are evaluated server-side.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000, description="Natural language search query")
    tenant_id: Optional[str] = Field(default=None, description="Tenant scope (enforced from server identity)")
    plant_id: Optional[str] = Field(default=None, description="Optional plant scope restriction")
    operational_domains: Optional[List[OperationalDomain]] = Field(default=None, description="Filter by operational domains")
    document_types: Optional[List[DocumentType]] = Field(default=None, description="Filter by document types")
    document_ids: Optional[List[str]] = Field(default=None, description="Filter to specific document IDs")
    lifecycle_statuses: Optional[List[DocumentLifecycleStatus]] = Field(
        default=None,
        description="Filter by lifecycle status (defaults to [PUBLISHED] only)",
    )
    require_effective_at: Optional[str] = Field(
        default=None,
        description="Filter to documents effective at this ISO timestamp",
    )
    min_score: float = Field(default=0.0, ge=0.0, description="Minimum relevance score threshold")
    top_k: int = Field(default=10, ge=1, le=50, description="Maximum number of passages to return")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Retrieval query cannot be empty or whitespace.")
        return clean


class Citation(BaseModel):
    """
    Authoritative reference to a retrieved source passage.
    Preserves exact document version, heading, location, validity status, and limitations.
    Citations MUST refer to retrieved source material, never fabricated references.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    citation_id: str = Field(..., description="Stable citation identifier (e.g., CIT-1)")
    chunk_id: str = Field(..., description="Referenced chunk ID")
    document_id: str = Field(..., description="Source document ID")
    document_title: str = Field(..., description="Source document title")
    document_version: str = Field(..., description="Exact source document version")
    section_heading: Optional[str] = Field(default=None, description="Section heading context")
    page_number: Optional[int] = Field(default=None, description="Page number where available")
    content_snippet: str = Field(..., description="Retrieved passage text snippet")
    score: float = Field(..., ge=0.0, description="Relevance / BM25 lexical ranking score")
    lifecycle_status: DocumentLifecycleStatus = Field(..., description="Document lifecycle status")
    effective_from: Optional[str] = Field(default=None, description="Effective from timestamp")
    effective_until: Optional[str] = Field(default=None, description="Effective until timestamp")
    freshness_status: FreshnessStatus = Field(default=FreshnessStatus.CURRENT, description="Temporal validity assessment")
    provenance_type: EvidenceProvenance = Field(default=EvidenceProvenance.OBSERVED, description="Provenance tier")
    limitations: List[str] = Field(default_factory=list, description="Document freshness or validity limitations")

    def to_evidence_record(self, tenant_id: str, workspace_id: str = "workspace_default") -> EvidenceRecord:
        """
        Converts this Citation into a canonical Prompt 31 EvidenceRecord
        for seamless integration with the Evidence & Explainability engine.
        """
        safe_chunk_id = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", self.chunk_id)[:64]
        safe_ev_id = f"ev_sop_{safe_chunk_id}"
        return EvidenceRecord(
            evidence_id=safe_ev_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            source_type=EvidenceSourceType.SOP_DOCUMENT,
            source_record_id=self.document_id,
            title=self.document_title,
            description=f"SOP Citation {self.citation_id}: {self.section_heading or 'General'}",
            observed_at=self.effective_from,
            valid_until=self.effective_until,
            provenance=self.provenance_type,
            quality_score=1.0 if self.freshness_status == FreshnessStatus.CURRENT else 0.7,
            confidence_score=min(1.0, max(0.1, self.score / 5.0)),
            payload={
                "chunk_id": self.chunk_id,
                "version": self.document_version,
                "heading": self.section_heading,
                "score": self.score,
                "snippet": self.content_snippet,
            },
        )



class RetrievalResponse(BaseModel):
    """
    Result of a scoped SOP retrieval execution.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(..., description="Original retrieval query")
    passages: List[Citation] = Field(default_factory=list, description="Ranked retrieved passages with citations")
    total_eligible_chunks: int = Field(..., ge=0, description="Total matching chunks across eligible documents")
    returned_count: int = Field(..., ge=0, description="Count of returned passages")
    execution_time_ms: float = Field(..., ge=0.0, description="Retrieval execution time in milliseconds")
    filters_applied: Dict[str, Any] = Field(default_factory=dict, description="Active filters applied during retrieval")
    evidence_status: EvidenceSufficiencyStatus = Field(..., description="Sufficiency assessment of matching results")
    advisory_notice: str = Field(default=MANDATORY_SOP_RAG_NOTICE, description="Advisory disclaimer")


# =============================================================================
# 7. RAG QUERY & ANSWER CONTRACTS
# =============================================================================

class RAGQueryRequest(BaseModel):
    """
    End-to-end RAG question-answering request.
    Retrieves authorized evidence and synthesizes an advisory response.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000, description="Question or operational inquiry")
    tenant_id: Optional[str] = Field(default=None, description="Tenant scope (enforced from server identity)")
    plant_id: Optional[str] = Field(default=None, description="Optional plant scope restriction")
    operational_domains: Optional[List[OperationalDomain]] = Field(default=None, description="Filter domains")
    document_types: Optional[List[DocumentType]] = Field(default=None, description="Filter types")
    document_ids: Optional[List[str]] = Field(default=None, description="Filter specific documents")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of passages to incorporate into context")
    allow_generation: bool = Field(default=True, description="Whether to attempt LLM synthesis if available")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("RAG query cannot be empty or whitespace.")
        return clean


class RAGAnswer(BaseModel):
    """
    Synthesized advisory answer, decoupled from supporting evidence citations.
    Contains explicit citations, evidence sufficiency classification, confidence metadata,
    and provider transparency.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    answer_id: str = Field(..., description="Unique answer identifier")
    query: str = Field(..., description="Original user inquiry")
    answer_text: str = Field(..., description="Synthesized advisory answer or honest refusal")
    citations: List[Citation] = Field(default_factory=list, description="Authoritative source citations")
    evidence_sufficiency: EvidenceSufficiencyStatus = Field(..., description="Sufficiency evaluation of retrieved evidence")
    evidence_limitations: List[str] = Field(default_factory=list, description="Material evidence gaps, version conflicts, or staleness")
    model_provider: ModelProviderType = Field(..., description="Active generation provider or retrieval-only mode")
    model_name: Optional[str] = Field(default=None, description="Underlying model identifier if generation occurred")
    generation_occurred: bool = Field(default=False, description="True only if an LLM/synthesis model actually generated text")
    confidence_assessment: Optional[Dict[str, Any]] = Field(default=None, description="Integrated Prompt 32 confidence assessment")
    advisory_notice: str = Field(default=MANDATORY_SOP_RAG_NOTICE, description="Mandatory non-execution advisory notice")
    retrieval_context_id: str = Field(..., description="Unique correlation ID linking retrieval passages and answer")
    timestamp: str = Field(..., description="ISO timestamp of answer generation")


# =============================================================================
# 8. AUDIT RECORD CONTRACT
# =============================================================================

class SOPAuditRecord(BaseModel):
    """
    Append-only audit record for SOP ingestion, retrieval, and RAG answer events.
    Never logs credentials, full sensitive raw text, or secrets.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str = Field(..., description="Unique audit event ID")
    timestamp: str = Field(..., description="ISO timestamp of event")
    event_type: str = Field(..., description="DOCUMENT_INGESTED, RETRIEVAL_EXECUTED, RAG_ANSWERED, ACCESS_DENIED, INGESTION_FAILED")
    tenant_id: str = Field(..., description="Tenant scope")
    actor_id: str = Field(..., description="Identity of caller or system service")
    document_id: Optional[str] = Field(default=None, description="Document ID involved if applicable")
    query_hash: Optional[str] = Field(default=None, description="SHA-256 hash of query (protects sensitive parameters)")
    passage_count: int = Field(default=0, ge=0, description="Number of passages retrieved or evaluated")
    outcome: str = Field(..., description="SUCCESS, DENIED, or FAILED")
    detail: Optional[str] = Field(default=None, description="Non-sensitive operational outcome summary")
