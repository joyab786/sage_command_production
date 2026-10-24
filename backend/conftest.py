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
