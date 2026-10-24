# backend/governance/rate_limiter.py
import time
from typing import Dict, Tuple
from abc import ABC, abstractmethod

try:
    from core.config import SAGE_RATE_LIMIT
except ModuleNotFoundError:
    from backend.core.config import SAGE_RATE_LIMIT


class BaseRateLimiter(ABC):
    @abstractmethod
    def is_allowed(self, client_id: str) -> Tuple[bool, int]:
        """Returns (is_allowed, remaining_requests)"""
        pass


class SlidingWindowRateLimiter(BaseRateLimiter):
    """
    Pluggable Sliding-Window Rate Limiter.
    Tracks client request timestamps within a sliding window.
    
    PER-PROCESS LIMITATION:
    This rate limiter operates entirely in memory per Python process. In multi-worker
    deployments (e.g., multiple uvicorn worker processes or containerized horizontal pods),
    the sliding-window rate limit is enforced per-process rather than globally across the
    entire cluster. Distributed cluster-wide rate limiting requires a shared distributed
    cache backend (such as Redis or Memcached).
    """
    def __init__(self, max_requests: int = SAGE_RATE_LIMIT, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}

    def is_allowed(self, client_id: str) -> Tuple[bool, int]:
        allowed, remaining, _ = self.is_allowed_with_retry_after(client_id)
        return allowed, remaining

    def is_allowed_with_retry_after(self, client_id: str) -> Tuple[bool, int, int]:
        """
        Evaluates sliding window and returns:
        (is_allowed: bool, remaining_requests: int, retry_after_seconds: int)
        """
        now = time.time()
        client_history = self.requests.get(client_id, [])
        
        # Filter timestamps outside current sliding window
        valid_history = [t for t in client_history if now - t < self.window_seconds]
        
        if len(valid_history) >= self.max_requests:
            self.requests[client_id] = valid_history
            oldest_ts = valid_history[0]
            retry_after = max(1, int(oldest_ts + self.window_seconds - now))
            return False, 0, retry_after
        
        valid_history.append(now)
        self.requests[client_id] = valid_history
        remaining = self.max_requests - len(valid_history)
        return True, remaining, 0

    def clear(self, client_id: Optional[str] = None):
        """Clears all tracking history, or history for a specific client (for test isolation)."""
        if client_id is not None:
            self.requests.pop(client_id, None)
        else:
            self.requests.clear()


rate_limiter = SlidingWindowRateLimiter()

# B6: Rate limit keyed by (tenant, user), 10 per minute on test endpoint,
# shared 10 per minute on create and legacy connect-live-db.
db_test_rate_limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)
db_connect_rate_limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)
