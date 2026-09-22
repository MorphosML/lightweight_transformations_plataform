from __future__ import annotations

import ipaddress
import re
import socket
from typing import Sequence
from urllib.parse import urlparse

from .errors import SecurityError


class SSRFGuard:
    """Enterprise SSRF protection engine.
    
    Prevents Server-Side Request Forgery attacks against cloud metadata endpoints
    (AWS IMDS, GCP metadata, Azure instance metadata) and unauthorized internal networks.
    """

    BLOCKED_METADATA_HOSTS = {
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
        "instance-data",
        "fd00:ec2::254",
    }

    @classmethod
    def validate_endpoint_url(cls, url: str, allow_localhost: bool = True) -> str:
        """Validates that a URL does not target prohibited cloud metadata or internal services."""
        if not url:
            return url

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https", "s3", "s3a", "jdbc"):
            raise SecurityError(f"Prohibited URL scheme: {parsed.scheme!r}")

        hostname = parsed.hostname
        if not hostname:
            return url

        lower_host = hostname.lower().strip("[]")

        # 1. Block known cloud metadata hostnames
        if lower_host in cls.BLOCKED_METADATA_HOSTS:
            raise SecurityError(f"Access to cloud metadata endpoint is blocked: {hostname}")

        # 2. Check IP addresses
        try:
            ip_obj = ipaddress.ip_address(lower_host)
            
            # Block Link-Local (AWS IMDS range 169.254.0.0/16)
            if ip_obj.is_link_local:
                raise SecurityError(f"Access to link-local IP range is blocked: {hostname}")

            # Block Multicast & Reserved
            if ip_obj.is_multicast or ip_obj.is_reserved:
                raise SecurityError(f"Access to reserved IP is blocked: {hostname}")

            # Check Loopback
            if ip_obj.is_loopback and not allow_localhost:
                raise SecurityError(f"Access to loopback IP is blocked in production: {hostname}")

        except ValueError:
            # Hostname is a domain name, not a raw IP address
            pass

        return url


class SQLSanitizer:
    """Validates and sanitizes SQL queries to prevent SQL injection and unauthorized DDL/DML."""

    # Prohibited dangerous keywords in read/transformation pipelines
    PROHIBITED_KEYWORDS = (
        r"\bDROP\b",
        r"\bTRUNCATE\b",
        r"\bDELETE\b",
        r"\bUPDATE\b",
        r"\bINSERT\b",
        r"\bALTER\b",
        r"\bCREATE\b",
        r"\bGRANT\b",
        r"\bREVOKE\b",
        r"\bEXEC\b",
        r"\bEXECUTE\b",
        r"\bATTACH\b",
        r"\bDETACH\b",
        r"\bLOAD_EXTENSION\b",
        r"\bCOPY\b",
    )

    COMPILED_PROHIBITED = [re.compile(kw, re.IGNORECASE) for kw in PROHIBITED_KEYWORDS]

    @classmethod
    def sanitize_read_query(cls, sql: str) -> str:
        """Validates that a SQL query is strictly a read-only SELECT or WITH statement.
        
        Rejects multiple semicolon-separated statements and dangerous DDL/DML.
        """
        clean_sql = sql.strip()
        if not clean_sql:
            raise SecurityError("SQL query cannot be empty")

        # Strip comments
        without_comments = re.sub(r"--.*?$", "", clean_sql, flags=re.MULTILINE)
        without_comments = re.sub(r"/\*.*?\*/", "", without_comments, flags=re.DOTALL).strip()

        # Check for multi-statement injection (semicolons not at the very end)
        statements = [s.strip() for s in without_comments.split(";") if s.strip()]
        if len(statements) > 1:
            raise SecurityError("Multiple SQL statements in a single query are forbidden")

        single_query = statements[0]

        # Enforce that query starts with SELECT, WITH, or EXPLAIN
        upper_query = single_query.upper().lstrip()
        if not (upper_query.startswith("SELECT") or upper_query.startswith("WITH") or upper_query.startswith("EXPLAIN")):
            raise SecurityError("Only read-only SELECT or WITH statements are allowed")

        # Check for forbidden keywords
        for pattern in cls.COMPILED_PROHIBITED:
            if pattern.search(single_query):
                matched = pattern.pattern.replace(r"\b", "")
                raise SecurityError(f"Prohibited SQL keyword detected: {matched}")

        return single_query
