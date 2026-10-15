# backend/tools/autonomy_context.py
"""
SageCommand V3 — Agent Autonomy Execution Context Provider
Prompt 38 — Server-authoritative runtime context binding for LangGraph agents,
ActionTool, and Mission Orchestration.

Invariants:
- Trusted caller identity MUST come from server-injected runtime context.
- Model-visible argument schemas MUST NOT allow agents or LLMs to manufacture identity or autonomy levels.
- Tools FAIL CLOSED immediately if trusted server identity context is unavailable.
- Context is thread-safe and async-safe via Python ContextVar.
"""

from contextvars import ContextVar, Token
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Tuple

try:
    from core.auth import Identity
    from data.schemas.autonomy_contract import SubjectType
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity
    from backend.data.schemas.autonomy_contract import SubjectType

# Thread-safe, async-safe context variables for server-authoritative caller identity and subject binding
_autonomy_identity_context_var: ContextVar[Optional[Identity]] = ContextVar(
    "autonomy_identity_context", default=None
)
_autonomy_subject_context_var: ContextVar[Optional[Tuple[SubjectType, str]]] = ContextVar(
    "autonomy_subject_context", default=None
)


def set_active_autonomy_identity(identity: Optional[Identity]) -> Token:
    """Binds trusted Identity context for agent autonomy evaluation."""
    return _autonomy_identity_context_var.set(identity)


def reset_active_autonomy_identity(token: Token) -> None:
    """Resets active autonomy identity context."""
    _autonomy_identity_context_var.reset(token)


def get_active_autonomy_identity() -> Optional[Identity]:
    """Retrieves active trusted Identity from server context."""
    return _autonomy_identity_context_var.get()


def set_active_autonomy_subject(subject_type: SubjectType, subject_id: str) -> Token:
    """Binds active governed subject (e.g. AGENT, 'agent_copilot')."""
    return _autonomy_subject_context_var.set((subject_type, subject_id.strip()))


def reset_active_autonomy_subject(token: Token) -> None:
    """Resets active autonomy subject context."""
    _autonomy_subject_context_var.reset(token)


def get_active_autonomy_subject() -> Tuple[SubjectType, str]:
    """Retrieves active governed subject or defaults to (SubjectType.AGENT, 'agent_default')."""
    val = _autonomy_subject_context_var.get()
    if val:
        return val
    return (SubjectType.AGENT, "agent_default")


@contextmanager
def active_autonomy_context(identity: Optional[Identity], subject_type: SubjectType = SubjectType.AGENT, subject_id: str = "agent_default"):
    """
    Token-safe synchronous context manager for authoritative autonomy execution.
    Guarantees reset of context variables in finally block, preventing cross-request leaks.
    """
    ident_token = set_active_autonomy_identity(identity)
    subj_token = set_active_autonomy_subject(subject_type, subject_id)
    try:
        yield (identity, subject_type, subject_id)
    finally:
        reset_active_autonomy_identity(ident_token)
        reset_active_autonomy_subject(subj_token)


@asynccontextmanager
async def async_active_autonomy_context(identity: Optional[Identity], subject_type: SubjectType = SubjectType.AGENT, subject_id: str = "agent_default"):
    """
    Token-safe asynchronous context manager for authoritative autonomy execution.
    Guarantees reset of context variables in finally block, preventing cross-request leaks.
    """
    ident_token = set_active_autonomy_identity(identity)
    subj_token = set_active_autonomy_subject(subject_type, subject_id)
    try:
        yield (identity, subject_type, subject_id)
    finally:
        reset_active_autonomy_identity(ident_token)
        reset_active_autonomy_subject(subj_token)
