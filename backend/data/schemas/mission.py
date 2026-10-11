# backend/data/schemas/mission.py
import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class MissionObject(BaseModel):
    """
    SageCommand V3 Autonomous Mission Object.
    Represents high-level operational directives assigned to the multi-agent system.
    """
    mission_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique mission UUID")
    title: str = Field(description="Short mission name, e.g. Prevent Line 4 shutdown")
    objective: str = Field(description="Primary operational objective statement")
    constraints: List[str] = Field(default_factory=list, description="Budgetary, time, or physical constraints")
    allowed_actions: List[str] = Field(default_factory=list, description="Action types permitted under this mission")
    risk_tolerance: str = Field(default="LOW", description="Risk tolerance threshold (LOW, MEDIUM, HIGH)")
    deadline: Optional[str] = Field(default=None, description="ISO-8601 deadline timestamp")
    success_criteria: List[str] = Field(default_factory=list, description="Verifiable success condition benchmarks")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="Creation timestamp")


# =============================================================================
# Re-export Prompt 35 Canonical Mission Contracts
# =============================================================================
try:
    from data.schemas.mission_contract import (
        MANDATORY_MISSION_NOTICE,
        SCHEMA_VERSION,
        MissionStatus,
        MissionType,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
        ConstraintType,
        MissionScope,
        MissionConstraint,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        Mission,
        MissionCreateRequest,
        MissionUpdateRequest,
        MissionReviewRequest,
        MissionValidationResponse,
        MissionRevisionRecord,
        MissionAuditRecord,
        VALID_LIFECYCLE_TRANSITIONS,
        is_valid_lifecycle_transition,
        validate_mission_dependencies,
    )
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.mission_contract import (
        MANDATORY_MISSION_NOTICE,
        SCHEMA_VERSION,
        MissionStatus,
        MissionType,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
        ConstraintType,
        MissionScope,
        MissionConstraint,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        Mission,
        MissionCreateRequest,
        MissionUpdateRequest,
        MissionReviewRequest,
        MissionValidationResponse,
        MissionRevisionRecord,
        MissionAuditRecord,
        VALID_LIFECYCLE_TRANSITIONS,
        is_valid_lifecycle_transition,
        validate_mission_dependencies,
    )
