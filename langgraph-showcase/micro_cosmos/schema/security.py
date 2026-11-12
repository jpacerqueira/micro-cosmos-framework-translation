"""Security analysis schema — findings from the Security Agent."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from micro_cosmos.schema.artifact import Artifact


class SecuritySeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class SecurityCategory(str, Enum):
    INJECTION = "INJECTION"
    AUTH = "AUTH"
    CRYPTO = "CRYPTO"
    SECRETS = "SECRETS"
    VALIDATION = "VALIDATION"
    EXPOSURE = "EXPOSURE"
    DESERIALIZATION = "DESERIALIZATION"
    PATH = "PATH"
    SSRF = "SSRF"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    OTHER = "OTHER"


class SecurityFinding(Artifact):
    id: str = Field(description="Stable short ID, e.g. SEC-001")
    title: str
    description: str
    severity: SecuritySeverity
    category: SecurityCategory
    location: str = Field(description="file:line, context name, or component")
    confirmed: bool = Field(description="True = confirmed finding, False = hypothesis")
    remediation: str
    cwe_id: str = Field(default="", description="CWE reference e.g. CWE-89")
    affects_migration: bool = Field(
        default=False,
        description="True if this finding persists or worsens in the target architecture",
    )


class SecurityReport(Artifact):
    source_lang: str = Field(default="")
    target_lang: str = Field(default="")
    scope_summary: str = Field(default="")
    findings: list[SecurityFinding] = Field(default_factory=list)
    source_architecture_risk: str = Field(
        default="MEDIUM",
        description="Overall risk for the source codebase: CRITICAL | HIGH | MEDIUM | LOW",
    )
    destination_architecture_risk: str = Field(
        default="UNKNOWN",
        description="Security risk assessment of the proposed target architecture",
    )
    risk_ranking: list[str] = Field(
        default_factory=list,
        description="Finding IDs sorted highest-risk first",
    )
    recommended_fixes: list[str] = Field(default_factory=list)
    follow_up_checks: list[str] = Field(default_factory=list)
    migration_security_notes: list[str] = Field(
        default_factory=list,
        description="Security considerations specific to this migration",
    )
