# backend/gateway/secret_provider.py
"""
SageCommand V3 — Secret Provider Abstraction
Manages sensitive database credentials out-of-band using secret handles/references.
Prevents plain-text passwords from being exposed to LLMs, LangGraph state, logs, or API payloads.
Extensible for enterprise secrets engines (e.g., HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, GCP Secret Manager).
"""

import abc
import secrets
import threading
from typing import Dict, Optional


class SecretProvider(abc.ABC):
    """
    Abstract interface for managing database secrets and credentials.
    """

    @abc.abstractmethod
    def store_secret(self, secret_value: str, label: Optional[str] = None) -> str:
        """Stores a secret and returns a secret reference handle."""
        pass

    @abc.abstractmethod
    def get_secret(self, secret_ref: str) -> Optional[str]:
        """Retrieves raw secret value given a valid reference handle."""
        pass

    @abc.abstractmethod
    def remove_secret(self, secret_ref: str) -> bool:
        """Removes a secret from the vault."""
        pass


class EnvSecretProvider(SecretProvider):
    """
    Thread-safe in-memory secret provider for local development, testing, and containerized deployments.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._vault: Dict[str, str] = {}

    def store_secret(self, secret_value: str, label: Optional[str] = None) -> str:
        if not secret_value:
            return ""
        secret_id = f"sec_{secrets.token_hex(8)}"
        with self._lock:
            self._vault[secret_id] = secret_value
        return secret_id

    def get_secret(self, secret_ref: str) -> Optional[str]:
        if not secret_ref:
            return None
        with self._lock:
            return self._vault.get(secret_ref)

    def remove_secret(self, secret_ref: str) -> bool:
        if not secret_ref:
            return False
        with self._lock:
            return self._vault.pop(secret_ref, None) is not None


# Global secret provider instance
secret_provider = EnvSecretProvider()
