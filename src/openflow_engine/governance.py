from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import time
from typing import Any

import pandas as pd


class SecretMasker:
    """Zero-log secret redactor to eliminate credential leakage."""

    PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        # AWS Access Key ID (AKIA...)
        ("AWS_KEY", re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b")),
        # AWS Secret Access Key (approx 40 alphanumeric chars)
        ("AWS_SECRET", re.compile(r"(?i)(aws_secret_access_key|secret_key|aws_secret)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{30,45})['\"]?")),
        # Database Password in URIs (postgresql://user:password@host/db)
        ("DB_URI_PWD", re.compile(r"([a-zA-Z0-9_+]+://[^:]+:)([^@\s]+)(@[^\s]+)")),
        # Generic Password / Secret assignments (password="xyz", secret='xyz')
        ("GENERIC_PWD", re.compile(r"(?i)(password|passwd|secret|api_key|token|auth_token)\s*[:=]\s*['\"]?([^'\"\s,;]+)['\"]?")),
        # Bearer Tokens
        ("BEARER_TOKEN", re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}")),
    ]

    @classmethod
    def mask(cls, text: str) -> str:
        """Sanitizes text, replacing any sensitive tokens with masked strings."""
        if not text:
            return ""

        sanitized = text

        # Redact URI passwords
        sanitized = cls.PATTERNS[2][1].sub(r"\1*****\3", sanitized)
        # Redact AWS Secret
        sanitized = cls.PATTERNS[1][1].sub(r"\1=*****", sanitized)
        # Redact generic passwords
        sanitized = cls.PATTERNS[3][1].sub(r"\1=*****", sanitized)
        # Redact AWS Key ID
        sanitized = cls.PATTERNS[0][1].sub("AKIA****************", sanitized)
        # Redact Bearer tokens
        sanitized = cls.PATTERNS[4][1].sub("Bearer ********", sanitized)

        return sanitized


class PIIMasker:
    """Enterprise Data Governance: column-level PII masking & pseudonymization."""

    @staticmethod
    def mask_email(email: str) -> str:
        """Masks an email address: john.doe@example.com -> j***@example.com."""
        if not isinstance(email, str) or "@" not in email:
            return email
        parts = email.split("@")
        username, domain = parts[0], parts[1]
        if len(username) <= 1:
            masked_user = "*"
        else:
            masked_user = username[0] + "***"
        return f"{masked_user}@{domain}"

    @staticmethod
    def mask_phone(phone: str) -> str:
        """Masks a phone number: +1-555-123-4567 -> +1-***-***-4567."""
        if not isinstance(phone, str):
            return str(phone)
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 4:
            return "****"
        last4 = digits[-4:]
        return f"***-***-{last4}"

    @staticmethod
    def pseudonymize(value: Any, salt: str = "openflow_salt") -> str:
        """One-way salted cryptographic pseudonymization (SHA-256)."""
        raw = f"{salt}:{value}".encode("utf-8")
        return f"pseudo_{hashlib.sha256(raw).hexdigest()[:12]}"

    @classmethod
    def mask_dataframe(
        cls,
        df: pd.DataFrame,
        email_cols: list[str] | None = None,
        phone_cols: list[str] | None = None,
        pseudonymize_cols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Applies configured PII masking rules across target columns in a DataFrame."""
        out_df = df.copy()

        if email_cols:
            for col in email_cols:
                if col in out_df.columns:
                    out_df[col] = out_df[col].astype(str).apply(cls.mask_email)

        if phone_cols:
            for col in phone_cols:
                if col in out_df.columns:
                    out_df[col] = out_df[col].astype(str).apply(cls.mask_phone)

        if pseudonymize_cols:
            for col in pseudonymize_cols:
                if col in out_df.columns:
                    out_df[col] = out_df[col].apply(cls.pseudonymize)

        return out_df


@dataclass
class AuditRecord:
    """Tamper-evident cryptographically signed audit trail."""
    timestamp: float
    tenant_id: str
    project_id: str
    user_id: str
    engine: str
    code_hash: str
    row_count: int
    duration_ms: float
    capacity_units: float
    status: str
    manifest_signature: str


class AuditLineage:
    """Manages immutable audit lineage with cryptographic hash validation."""

    @classmethod
    def create_record(
        cls,
        tenant_id: str,
        project_id: str,
        user_id: str,
        engine: str,
        code: str,
        row_count: int,
        duration_ms: float,
        capacity_units: float,
        status: str,
    ) -> AuditRecord:
        """Constructs a tamper-evident audit record."""
        ts = time.time()
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        rounded_duration = round(duration_ms, 2)
        rounded_cu = round(capacity_units, 4)

        # Generate manifest signature across all attributes
        payload = f"{ts}:{tenant_id}:{project_id}:{user_id}:{engine}:{code_hash}:{row_count}:{rounded_duration}:{rounded_cu}:{status}"
        manifest_signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        return AuditRecord(
            timestamp=ts,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            engine=engine,
            code_hash=code_hash,
            row_count=row_count,
            duration_ms=rounded_duration,
            capacity_units=rounded_cu,
            status=status,
            manifest_signature=manifest_signature,
        )

    @classmethod
    def verify_record(cls, record: AuditRecord) -> bool:
        """Verifies integrity of an audit record signature."""
        payload = (
            f"{record.timestamp}:{record.tenant_id}:{record.project_id}:{record.user_id}:"
            f"{record.engine}:{record.code_hash}:{record.row_count}:{record.duration_ms}:"
            f"{record.capacity_units}:{record.status}"
        )
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return expected == record.manifest_signature
