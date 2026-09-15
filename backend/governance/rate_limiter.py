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
    Tracks client request timestamps within a 60-second window.
    """
    def __init__(self, max_requests: int = SAGE_RATE_LIMIT, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}

    def is_allowed(self, client_id: str) -> Tuple[bool, int]:
        now = time.time()
        client_history = self.requests.get(client_id, [])
        
        # Filter timestamps outside current sliding window
        valid_history = [t for t in client_history if now - t < self.window_seconds]
        
        if len(valid_history) >= self.max_requests:
            self.requests[client_id] = valid_history
            remaining = 0
            return False, remaining
        
        valid_history.append(now)
        self.requests[client_id] = valid_history
        remaining = self.max_requests - len(valid_history)
        return True, remaining


rate_limiter = SlidingWindowRateLimiter()
