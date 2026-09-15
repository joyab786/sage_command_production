# backend/services/audit_ledger.py
"""
SageCommand V3 — Authoritative Audit & Decision Ledger Service
Manages trusted event ingestion, secret redaction, cryptographic hashing,
multi-tenant query evaluation, and decision record reconstruction.

Invariants:
- The ledger is passive and observational.
- Client payloads are sanitized and redacted before persistence.
- Zero operational side-effects or execution triggers occur on event append.
"""

import time
import uuid
from typing import Dict, List, Optional, Any, Callable

try:
    from core.config import SAGE_AUDIT_MAX_PAYLOAD_SIZE
    from governance.redaction import sanitize_payload
    from data.schemas.ledger_contract import (
        LedgerEvent,
        LedgerActor,
        ModelProvenance,
        EventCategory,
        EventStatus,
        ActorType,
        DecisionRecord,
        EventType,
    )
    from services.ledger_repository import (
        AuditLedgerRepository,
        default_ledger_repository,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_AUDIT_MAX_PAYLOAD_SIZE
    from backend.governance.redaction import sanitize_payload
    from backend.data.schemas.ledger_contract import (
        LedgerEvent,
        LedgerActor,
        ModelProvenance,
        EventCategory,
        EventStatus,
        ActorType,
        DecisionRecord,
        EventType,
    )
    from backend.services.ledger_repository import (
        AuditLedgerRepository,
        default_ledger_repository,
    )


class AuditLedgerService:
    """
    Authoritative Audit Ledger Service.
    Serves as the central append-only ledger for all security, operational, and AI decisions.
    """

    def __init__(self, repository: Optional[AuditLedgerRepository] = None):
        self.repository = repository or default_ledger_repository
        self._subscribers: List[Callable[[LedgerEvent], None]] = []

    def subscribe(self, callback: Callable[[LedgerEvent], None]):
        """Subscribes an event listener (e.g. WebSocket broadcaster)."""
        self._subscribers.append(callback)

    def record_event(
        self,
        event_type: str,
        actor: LedgerActor,
        tenant_id: str,
        category: EventCategory = EventCategory.SYSTEM,
        event_status: EventStatus = EventStatus.SUCCESS,
        workspace_id: str = "workspace_default",
        session_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        action_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        data_mode: str = "REAL",
        payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        model_provenance: Optional[ModelProvenance] = None,
        policy_version: Optional[str] = None,
        authorization_version: Optional[str] = None,
        event_id: Optional[str] = None,
        occurred_at: Optional[str] = None
    ) -> LedgerEvent:
        """
        Records an append-only, tamper-evident audit event.
        Automatically performs deep secret redaction and SHA-256 fingerprinting.
        """
        now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        t_occurred = occurred_at or now_utc
        t_recorded = now_utc
        e_id = event_id or f"evt_{uuid.uuid4().hex[:16]}"

        # 1. Deep Recursive Redaction and Payload Bounding
        clean_payload = sanitize_payload(payload or {}, max_size_bytes=SAGE_AUDIT_MAX_PAYLOAD_SIZE)
        clean_metadata = sanitize_payload(metadata or {}, max_size_bytes=SAGE_AUDIT_MAX_PAYLOAD_SIZE)

        # 2. Build Canonical Event Object
        event = LedgerEvent(
            event_id=e_id,
            event_type=str(event_type),
            event_version="v1",
            category=category,
            event_status=event_status,
            occurred_at=t_occurred,
            recorded_at=t_recorded,
            tenant_id=tenant_id,
            workspace_id=workspace_id or "workspace_default",
            session_id=session_id,
            plant_id=plant_id,
            actor=actor,
            request_id=request_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action_id=action_id,
            mission_id=mission_id,
            incident_id=incident_id,
            data_mode=data_mode,
            payload=clean_payload if isinstance(clean_payload, dict) else {"details": clean_payload},
            metadata=clean_metadata if isinstance(clean_metadata, dict) else {"details": clean_metadata},
            model_provenance=model_provenance,
            policy_version=policy_version,
            authorization_version=authorization_version
        )

        # 3. Compute Deterministic Hash
        event.finalize_hash()

        # 4. Append to Storage
        stored_event = self.repository.append(event)

        # 5. Notify in-process subscribers (e.g. WebSockets)
        for sub in self._subscribers:
            try:
                sub(stored_event)
            except Exception:
                pass

        return stored_event

    def record_security_event_bridge(
        self,
        event_name: str,
        details: Dict[str, Any],
        user_id: str = "anonymous",
        severity: str = "INFO",
        tenant_id: str = "tenant_default",
        session_id: Optional[str] = None
    ) -> LedgerEvent:
        """
        Bridges legacy log_security_event calls into the persistent Ledger.
        """
        actor = LedgerActor(
            actor_type=ActorType.ADMIN if "admin" in user_id.lower() else ActorType.USER,
            actor_id=user_id,
            acting_user_id=user_id
        )
        return self.record_event(
            event_type=event_name,
            actor=actor,
            tenant_id=tenant_id,
            category=EventCategory.SECURITY,
            session_id=session_id,
            payload=details,
            metadata={"severity": severity}
        )

    def get_timeline(
        self,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        action_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50
    ) -> List[LedgerEvent]:
        """Returns ordered chronological timeline of events."""
        return self.repository.get_timeline(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            action_id=action_id,
            incident_id=incident_id,
            workspace_id=workspace_id,
            session_id=session_id,
            limit=limit
        )

    def get_decision_record(self, action_id: str, tenant_id: str) -> Optional[DecisionRecord]:
        """
        Reconstructs high-level DecisionRecord connecting:
        Evidence -> Action Proposal -> Authorization -> Policy Decision -> Deferred Approvals/Executions.
        """
        events = self.repository.get_decision_events(action_id, tenant_id)
        if not events:
            return None

        # Identify key lifecycle events
        proposal_evt: Optional[LedgerEvent] = None
        authz_evt: Optional[LedgerEvent] = None
        policy_evt: Optional[LedgerEvent] = None
        sim_evt: Optional[LedgerEvent] = None

        for e in events:
            if e.event_type == EventType.ACTION_PROPOSED.value:
                proposal_evt = e
            elif e.event_type in (EventType.AUTHORIZATION_ALLOWED.value, EventType.AUTHORIZATION_DENIED.value):
                authz_evt = e
            elif e.event_type in (
                EventType.POLICY_ALLOWED.value,
                EventType.POLICY_DENIED.value,
                EventType.POLICY_APPROVAL_REQUIRED.value,
                EventType.POLICY_HOLD.value
            ):
                policy_evt = e
            elif e.event_type == EventType.ACTION_SIMULATION_COMPLETED.value:
                sim_evt = e

        anchor_evt = proposal_evt or events[0]
        payload = anchor_evt.payload or {}

        evidence_list = payload.get("evidence", [])
        if not isinstance(evidence_list, list):
            evidence_list = []

        return DecisionRecord(
            decision_id=f"dec_{action_id}",
            decision_type="ACTION_PROPOSAL",
            subject_type="ACTION",
            subject_id=action_id,
            tenant_id=anchor_evt.tenant_id,
            workspace_id=anchor_evt.workspace_id,
            session_id=anchor_evt.session_id,
            plant_id=anchor_evt.plant_id,
            actor=anchor_evt.actor,
            action_id=action_id,
            incident_id=anchor_evt.incident_id,
            mission_id=anchor_evt.mission_id,
            evidence_refs=evidence_list,
            authorization_decision_id=authz_evt.event_id if authz_evt else None,
            policy_decision_id=policy_evt.event_id if policy_evt else None,
            approval_id="NOT_AVAILABLE",
            execution_id="NOT_AVAILABLE",
            verification_id="NOT_AVAILABLE",
            decision=policy_evt.event_type if policy_evt else (authz_evt.event_type if authz_evt else "PROPOSED"),
            reason=payload.get("reason", {}).get("summary", "") if isinstance(payload.get("reason"), dict) else str(payload.get("reason", "")),
            risk_level=payload.get("system_risk_level", "LOW"),
            data_mode=anchor_evt.data_mode,
            model_provenance=anchor_evt.model_provenance,
            created_at=anchor_evt.occurred_at
        )


# Global singleton instance
audit_ledger = AuditLedgerService()
