# backend/conftest.py
"""
Pytest configuration for SageCommand V3 test suite.
CRITICAL: SAGE_ENV=test MUST be set before any backend modules are imported,
ensuring tests execute under the test environment profile while production defaults
remain fail-closed.
"""
import os

if os.environ.get("SAGE_ENV") != "production":
    os.environ["SAGE_ENV"] = "test"

import pytest

@pytest.fixture(autouse=True)
def reset_db_rate_limiters():
    try:
        from governance.rate_limiter import db_test_rate_limiter, db_connect_rate_limiter
    except ImportError:
        try:
            from backend.governance.rate_limiter import db_test_rate_limiter, db_connect_rate_limiter
        except ImportError:
            yield
            return
    db_test_rate_limiter.clear()
    db_connect_rate_limiter.clear()
    yield
    db_test_rate_limiter.clear()
    db_connect_rate_limiter.clear()

