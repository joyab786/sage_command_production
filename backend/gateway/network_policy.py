# backend/gateway/network_policy.py
"""
SageCommand V3 — Network Policy & SSRF Guardrail Engine (Prompt 39 Correction 5h)
Protects external database connection endpoints against Server-Side Request Forgery (SSRF),
DNS rebinding, unauthorized private network scanning, cloud metadata access, and unauthorized port usage.
"""

import ipaddress
import os
import socket
from enum import Enum
from typing import List, Optional, Union

try:
    from core.config import (
        SAGE_ENV,
        IS_PRODUCTION,
        SAGE_DB_NETWORK_POLICY,
        SAGE_DB_ALLOWED_HOSTS,
        SAGE_DB_ALLOWED_PORTS
    )
    from governance.audit import log_security_event
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_ENV,
        IS_PRODUCTION,
        SAGE_DB_NETWORK_POLICY,
        SAGE_DB_ALLOWED_HOSTS,
        SAGE_DB_ALLOWED_PORTS
    )
    from backend.governance.audit import log_security_event


UNIFORM_SSRF_ERROR_MESSAGE = "Database host connection refused, blocked, or unreachable."


class NetworkPolicy(str, Enum):
    RESTRICTED = "RESTRICTED"            # Default: Block loopback/private/metadata unless in ALLOWED_HOSTS
    PRIVATE_ALLOWED = "PRIVATE_ALLOWED"   # Allow private IPs, block loopback & cloud metadata
    INTERNAL_ONLY = "INTERNAL_ONLY"      # Only allow internal/private IPs, block public IPs
    ALLOWLIST = "ALLOWLIST"              # Only allow hostnames explicitly listed in ALLOWED_HOSTS


class DatabasePolicyBlockedError(PermissionError):
    """Raised when a database connection request violates the SSRF network security policy."""
    pass


# -------------------------------------------------------------------------
# B3: Never Allowlistable Networks & IP Ranges
# -------------------------------------------------------------------------
NEVER_ALLOWLISTABLE_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),       # IPv4 Link-Local / Cloud Metadata (AWS, Azure, GCP)
    ipaddress.ip_network("fe80::/10"),            # IPv6 Link-Local
    ipaddress.ip_network("fd00:ec2::254/128"),    # AWS IPv6 IMDSv2 metadata
    ipaddress.ip_network("0.0.0.0/8"),            # Current network (RFC 1122)
    ipaddress.ip_network("::/128"),               # IPv6 unspecified address
    ipaddress.ip_network("224.0.0.0/4"),          # IPv4 Multicast
    ipaddress.ip_network("ff00::/8"),             # IPv6 Multicast
    ipaddress.ip_network("240.0.0.0/4"),          # IPv4 Reserved for future use (RFC 1112)
    ipaddress.ip_network("100.100.100.200/32"),   # Alibaba Cloud IMDS metadata
]

# Loopback definitions (B4)
LOOPBACK_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]

# Private IP ranges (B4)
PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),          # Class A private
    ipaddress.ip_network("172.16.0.0/12"),       # Class B private
    ipaddress.ip_network("192.168.0.0/16"),      # Class C private
    ipaddress.ip_network("100.64.0.0/10"),       # Shared address space / CGNAT (RFC 6598)
    ipaddress.ip_network("fc00::/7"),            # IPv6 Unique Local Address / ULA (RFC 4193)
]


def normalize_and_unwrap_ip(ip_str: str) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address]:
    """
    Parses and normalizes an IP address with ipaddress.
    Rejects unusual encodings (octal, hex literals, decimal integer representations).
    Unwraps IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) and 6to4 (2002::/16) to IPv4.
    """
    raw = ip_str.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]

    # Reject unusual IP encodings like octal (0177.0.0.1), integer literals (2130706433), or hex
    if raw.isdigit() or raw.startswith("0x") or raw.startswith("0X"):
        raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

    if "." in raw:
        parts = raw.split(".")
        if len(parts) == 4:
            for part in parts:
                if part.startswith("0x") or part.startswith("0X"):
                    raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)
                if len(part) > 1 and part.startswith("0"):
                    # Octal notation detected
                    raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

    # Let ipaddress parse literal IP. Raises ValueError if raw is a hostname.
    ip = ipaddress.ip_address(raw)

    # Unwrap IPv4-mapped IPv6 (::ffff:x.x.x.x)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return ip.ipv4_mapped
        # Unwrap 6to4 (2002::/16)
        if ip in ipaddress.ip_network("2002::/16"):
            v4_bytes = ip.packed[2:6]
            return ipaddress.IPv4Address(v4_bytes)

    return ip


def resolve_all_ip_records(host: str) -> List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    """
    Resolves hostname to ALL A (IPv4) and AAAA (IPv6) records via socket.getaddrinfo.
    Returns normalized IP address objects. Raises DatabasePolicyBlockedError if resolution fails
    or if an unusual encoding is supplied.
    """
    clean_host = host.strip()
    if clean_host.startswith("[") and clean_host.endswith("]"):
        clean_host = clean_host[1:-1]

    # Check if host is already a literal IP
    try:
        norm_lit = normalize_and_unwrap_ip(clean_host)
        return [norm_lit]
    except DatabasePolicyBlockedError:
        raise
    except ValueError:
        # Not an IP literal, fall through to DNS resolution
        pass


    try:
        addr_infos = socket.getaddrinfo(clean_host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (socket.gaierror, socket.error) as gai:
        raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE) from gai
    except Exception as exc:
        raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE) from exc

    if not addr_infos:
        raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

    resolved_ips: List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]] = []
    seen = set()
    for entry in addr_infos:
        sockaddr = entry[4]
        ip_raw = sockaddr[0]
        try:
            norm_ip = normalize_and_unwrap_ip(ip_raw)
            ip_str = str(norm_ip)
            if ip_str not in seen:
                seen.add(ip_str)
                resolved_ips.append(norm_ip)
        except DatabasePolicyBlockedError:
            raise
        except Exception as e:
            raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE) from e

    if not resolved_ips:
        raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

    return resolved_ips


class NetworkPolicyEngine:
    """
    Evaluates database connection targets against strict SSRF and network security policies.
    Enforces record resolution, IP normalization, never-allowlistable checks, environment loopback gating,
    production private range allowlisting, and address pinning.
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

    def is_never_allowlistable(self, ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
        """Check if an IP falls within any never-allowlistable network (B3)."""
        for net in NEVER_ALLOWLISTABLE_NETWORKS:
            if ip in net:
                return True
        return False

    def is_loopback(self, host: str, ip: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]] = None) -> bool:
        """Check if hostname or IP is loopback/localhost."""
        host_lower = host.lower().strip()
        if host_lower in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "::", "[::1]", "0:0:0:0:0:0:0:1"):
            return True
        if host_lower.startswith("127."):
            return True
        if ip:
            if ip.is_loopback or ip.is_unspecified:
                return True
            for net in LOOPBACK_NETWORKS:
                if ip in net:
                    return True
        return False

    def is_private_ip(self, ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
        """Check if IP falls into RFC1918, RFC6598 (CGNAT), or RFC4193 (ULA) private ranges."""
        if ip.is_private:
            return True
        for net in PRIVATE_NETWORKS:
            if ip in net:
                return True
        return False

    def is_host_allowlisted(self, host: str, ip: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]] = None) -> bool:
        """Checks if hostname or IP matches the configured allowlist (exact name, IP, or CIDR)."""
        host_clean = host.strip().lower()
        if host_clean in self.allowed_hosts:
            return True

        if ip:
            ip_str = str(ip).lower()
            if ip_str in self.allowed_hosts:
                return True
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
        # In non-production, if localhost or 127.0.0.1 is allowlisted, any loopback is allowlisted
        current_env = os.environ.get("SAGE_ENV", SAGE_ENV).strip().lower()
        if current_env in ("development", "test"):
            if any(h in self.allowed_hosts for h in ("localhost", "127.0.0.1", "::1")):
                if host_clean in ("localhost", "127.0.0.1", "::1") or (ip and ip.is_loopback):
                    return True

        return False

    def validate_host_and_port(
        self,
        host: str,
        port: Optional[int] = None,
        scheme: str = "postgresql",
        policy_override: Optional[str] = None
    ) -> str:
        """
        Validates target host and port against active network policy.
        B1: Resolves host to ALL A and AAAA records; rejects if ANY resolved address is blocked.
        B2: Returns pinned IP address string to prevent DNS rebinding.
        B3: Rejects never-allowlistable networks unconditionally.
        B4: Loopback allowed only in dev/test; private ranges in production require explicit allowlisting.
        B5: Uniform error code and message on violation.
        """
        active_policy = NetworkPolicy(policy_override) if policy_override else self.default_policy
        host_clean = host.strip().lower()

        # 1. Local SQLite handling: Skip network IP resolution for local files
        if scheme.lower() in ("sqlite", "sqlite3"):
            forbidden_targets = ["/etc/passwd", "/etc/shadow", "/proc/", "/dev/", "\\windows\\system32", "c:\\windows"]
            if any(forbidden in host_clean for forbidden in forbidden_targets):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "SQLite path traversal / system file target", "target": host},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)
            return host_clean

        # 2. Port Validation (B5: Keep existing port allowlist)
        if port is not None and self.allowed_ports:
            if port not in self.allowed_ports and not (host_clean in self.allowed_hosts):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "Port not in allowed ports list", "port": port, "allowed_ports": self.allowed_ports},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

        # 3. Resolve to ALL A and AAAA records (B1)
        current_env = os.environ.get("SAGE_ENV", SAGE_ENV).strip().lower()
        is_prod = (current_env not in ("development", "test"))

        try:
            resolved_ips = resolve_all_ip_records(host_clean)
        except DatabasePolicyBlockedError:
            if self.is_host_allowlisted(host_clean) and not is_prod:
                return host_clean
            raise

        # 4. Check every resolved IP address (B1: Reject if ANY resolved address is blocked)
        for ip in resolved_ips:
            # B3: Never allowlistable check
            if self.is_never_allowlistable(ip):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "SSRF Never-Allowlistable target blocked", "host": host_clean, "resolved_ip": str(ip)},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

            # Cloud metadata hostnames
            if host_clean in ("metadata.google.internal", "metadata.local", "instance-data"):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "SSRF Cloud metadata hostname blocked", "host": host_clean},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

            # B4: Loopback allowed ONLY when SAGE_ENV is development or test
            is_loop = self.is_loopback(host_clean, ip)
            if is_loop:
                if is_prod:
                    log_security_event(
                        "DATABASE_CONNECTION_REJECTED",
                        {"reason": "SSRF Loopback target blocked in production", "host": host_clean, "resolved_ip": str(ip)},
                        severity="WARNING"
                    )
                    raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)
                # In development/test mode, check if allowlisted when policy is RESTRICTED or ALLOWLIST
                if active_policy in (NetworkPolicy.RESTRICTED, NetworkPolicy.ALLOWLIST) and not self.is_host_allowlisted(host_clean, ip):
                    log_security_event(
                        "DATABASE_CONNECTION_REJECTED",
                        {"reason": "SSRF Loopback target blocked under RESTRICTED policy (not in allowed_hosts)", "host": host_clean, "resolved_ip": str(ip)},
                        severity="WARNING"
                    )
                    raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)
                continue


            # B4: Private ranges in production allowed ONLY when explicitly in SAGE_DB_ALLOWED_HOSTS
            if self.is_private_ip(ip):
                if is_prod:
                    if not self.is_host_allowlisted(host_clean, ip):
                        log_security_event(
                            "DATABASE_CONNECTION_REJECTED",
                            {"reason": "SSRF Private network IP blocked in production (not in SAGE_DB_ALLOWED_HOSTS)", "host": host_clean, "resolved_ip": str(ip)},
                            severity="WARNING"
                        )
                        raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)
                else:
                    # In non-production, check policy setting
                    if active_policy == NetworkPolicy.RESTRICTED and not self.is_host_allowlisted(host_clean, ip):
                        log_security_event(
                            "DATABASE_CONNECTION_REJECTED",
                            {"reason": "SSRF Private IP target blocked under RESTRICTED policy", "host": host_clean, "resolved_ip": str(ip)},
                            severity="WARNING"
                        )
                        raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

            # Strict ALLOWLIST policy
            if active_policy == NetworkPolicy.ALLOWLIST and not self.is_host_allowlisted(host_clean, ip):
                log_security_event(
                    "DATABASE_CONNECTION_REJECTED",
                    {"reason": "Host not in strict allowlist", "host": host_clean, "resolved_ip": str(ip)},
                    severity="WARNING"
                )
                raise DatabasePolicyBlockedError(UNIFORM_SSRF_ERROR_MESSAGE)

        # B2: Return the pinned IP address (first validated record)
        pinned_ip = str(resolved_ips[0])
        return pinned_ip


# Default singleton instance
network_policy_engine = NetworkPolicyEngine()
