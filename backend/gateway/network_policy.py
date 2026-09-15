# backend/gateway/network_policy.py
"""
SageCommand V3 — Network Policy & SSRF Guardrail Engine
Protects external database connection endpoints against Server-Side Request Forgery (SSRF),
unauthorized private network scanning, cloud metadata access, and unauthorized port usage.
"""

import ipaddress
import os
import socket
from enum import Enum
from typing import List, Optional

try:
    from core.config import (
        SAGE_DB_NETWORK_POLICY,
        SAGE_DB_ALLOWED_HOSTS,
        SAGE_DB_ALLOWED_PORTS
    )
    from governance.audit import log_security_event
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_DB_NETWORK_POLICY,
        SAGE_DB_ALLOWED_HOSTS,
        SAGE_DB_ALLOWED_PORTS
    )
    from backend.governance.audit import log_security_event


class NetworkPolicy(str, Enum):
    RESTRICTED = "RESTRICTED"          # Default: Block loopback/private/metadata unless in ALLOWED_HOSTS
    PRIVATE_ALLOWED = "PRIVATE_ALLOWED" # Allow private IPs, block loopback & cloud metadata
    INTERNAL_ONLY = "INTERNAL_ONLY"    # Only allow internal/private IPs, block public IPs
    ALLOWLIST = "ALLOWLIST"            # Only allow hostnames explicitly listed in ALLOWED_HOSTS


class DatabasePolicyBlockedError(PermissionError):
    """Raised when a database connection request violates the SSRF network security policy."""
    pass


class NetworkPolicyEngine:
    """
    Evaluates database connection targets against strict SSRF and network security policies.
    """

    def __init__(
        self,
        default_policy: str = SAGE_DB_NETWORK_POLICY,
        allowed_hosts: Optional[List[str]] = None,
        allowed_ports: Optional[List[int]] = None
    ):
        self.default_policy = NetworkPolicy(default_policy)
        self.allowed_hosts = [h.lower().strip() for h in (allowed_hosts if allowed_hosts is not None else SAGE_DB_ALLOWED_HOSTS)]
        self.allowed_ports = allowed_ports if allowed_ports is not None else SAGE_DB_ALLOWED_PORTS

    def is_loopback(self, host: str, ip: Optional[ipaddress.IPv4Address | ipaddress.IPv6Address] = None) -> bool:
        """Check if hostname or IP is loopback/localhost."""
        host_lower = host.lower().strip()
        if host_lower in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "::", "[::1]", "0:0:0:0:0:0:0:1"):
            return True
        if host_lower.startswith("127."):
            return True
        if ip:
            return ip.is_loopback or ip.is_unspecified
        return False

    def is_metadata_endpoint(self, host: str, ip: Optional[ipaddress.IPv4Address | ipaddress.IPv6Address] = None) -> bool:
        """Check if target host or IP is cloud metadata (169.254.169.254 / link-local / instance metadata)."""
        host_lower = host.lower().strip()
        if host_lower.startswith("169.254."):
            return True
        if host_lower in ("metadata.google.internal", "metadata.local", "instance-data"):
            return True
        if ip:
            return ip.is_link_local
        return False

    def is_private_ip(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """Check if IP falls into RFC1918 or RFC4193 private ranges."""
        return ip.is_private

    def resolve_ip(self, host: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """Safely attempt to resolve hostname to IP object."""
        host_clean = host.strip()
        if host_clean.startswith("[") and host_clean.endswith("]"):
            host_clean = host_clean[1:-1]
        try:
            # Check if host is already an IP address
            return ipaddress.ip_address(host_clean)
        except ValueError:
            pass

        try:
            addr_info = socket.getaddrinfo(host_clean, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            if addr_info:
                raw_ip = addr_info[0][4][0]
                return ipaddress.ip_address(raw_ip)
        except (socket.gaierror, socket.error):
            return None
        return None

    def is_host_allowlisted(self, host: str, ip: Optional[ipaddress.IPv4Address | ipaddress.IPv6Address] = None) -> bool:
        """Checks if hostname or IP matches the configured allowlist (exact name, IP, or CIDR)."""
        host_clean = host.strip().lower()
        if host_clean in self.allowed_hosts:
            return True

        if ip:
            for entry in self.allowed_hosts:
                if "/" in entry:
                    try:
                        net = ipaddress.ip_network(entry, strict=False)
                        if ip in net:
                            return True
                    except ValueError:
                        continue
                else:
                    try:
                        entry_ip = ipaddress.ip_address(entry)
                        if ip == entry_ip:
                            return True
                    except ValueError:
                        continue
        return False

    def validate_host_and_port(
        self,
        host: str,
        port: Optional[int] = None,
        scheme: str = "postgresql",
        policy_override: Optional[str] = None
    ) -> bool:
        """
        Validates target host and port against active network policy.
        Raises DatabasePolicyBlockedError on violation.
        """
        active_policy = NetworkPolicy(policy_override) if policy_override else self.default_policy
        host_clean = host.strip().lower()

        # 1. SQLite handling: Skip network IP checks for local SQLite
        if scheme.lower() in ("sqlite", "sqlite3"):
            # Check for path traversal or sensitive file targets in SQLite path
            forbidden_targets = ["/etc/passwd", "/etc/shadow", "/proc/", "/dev/", "\\windows\\system32", "c:\\windows"]
            if any(forbidden in host_clean for forbidden in forbidden_targets):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "SQLite path traversal / system file target", "target": host},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(f"Access Denied: SQLite database target '{host}' accesses restricted system paths.")
            return True

        # Resolve IP for network checks
        ip_obj = self.resolve_ip(host_clean)

        # 2. Port Validation
        if port is not None and self.allowed_ports:
            if port not in self.allowed_ports and not self.is_host_allowlisted(host_clean, ip_obj):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "Port not in allowed ports list", "port": port, "allowed_ports": self.allowed_ports},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(
                    f"Access Denied: Port {port} is not in the allowed database ports list ({self.allowed_ports})."
                )

        # 3. Always block Cloud Metadata endpoints (169.254.x.x / link-local) unless explicitly allowlisted
        if self.is_metadata_endpoint(host_clean, ip_obj) and not (host_clean in self.allowed_hosts):
            log_security_event(
                "DATABASE_CONNECTION_REJECTED",
                {"reason": "SSRF Cloud Metadata target blocked", "host": host_clean},
                severity="WARNING"
            )
            raise DatabasePolicyBlockedError("Access Denied: Connection to cloud metadata endpoint (169.254.x.x) is prohibited.")

        # 4. If target is explicitly allowlisted by host or CIDR, permit access (metadata check passed)
        if self.is_host_allowlisted(host_clean, ip_obj):
            return True

        # 5. Evaluate Policy Rules
        if active_policy == NetworkPolicy.ALLOWLIST:
            log_security_event(
                "DATABASE_CONNECTION_REJECTED",
                {"reason": "Host not in strict allowlist", "host": host_clean, "policy": active_policy.value},
                severity="WARNING"
            )
            raise DatabasePolicyBlockedError(f"Access Denied: Host '{host_clean}' is not in the explicit database allowlist.")

        if active_policy == NetworkPolicy.RESTRICTED:
            if self.is_loopback(host_clean, ip_obj):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "SSRF Loopback target blocked under RESTRICTED policy", "host": host_clean},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(f"Access Denied: Loopback destination '{host_clean}' blocked under RESTRICTED network policy.")

            if ip_obj and self.is_private_ip(ip_obj):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "SSRF Private IP target blocked under RESTRICTED policy", "host": host_clean, "ip": str(ip_obj)},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(
                    f"Access Denied: Connection to private network IP '{ip_obj}' is blocked under RESTRICTED policy. "
                    "Use SAGE_DB_NETWORK_POLICY=PRIVATE_ALLOWED or add host to SAGE_DB_ALLOWED_HOSTS."
                )

        elif active_policy == NetworkPolicy.PRIVATE_ALLOWED:
            if self.is_loopback(host_clean, ip_obj):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "SSRF Loopback target blocked under PRIVATE_ALLOWED policy", "host": host_clean},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(f"Access Denied: Loopback target '{host_clean}' is prohibited.")

        elif active_policy == NetworkPolicy.INTERNAL_ONLY:
            if ip_obj and not self.is_private_ip(ip_obj) and not self.is_loopback(host_clean, ip_obj):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "Public IP blocked under INTERNAL_ONLY policy", "host": host_clean, "ip": str(ip_obj)},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(f"Access Denied: Connection to public IP '{ip_obj}' is blocked under INTERNAL_ONLY policy.")

        return True


# Default instance
network_policy_engine = NetworkPolicyEngine()
