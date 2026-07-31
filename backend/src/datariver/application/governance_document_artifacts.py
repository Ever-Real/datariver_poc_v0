from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from datariver.application.errors import ExternalDependencyError
from datariver.application.governance_document_storage_names import (
    governance_document_storage_stem,
)
from datariver.domain.common import ConflictError, ValidationError

GOVERNANCE_DOCUMENT_ARTIFACT_PREFIX = "governance/documents/v1"
MAXIMUM_GOVERNANCE_DOCUMENT_HTML_BYTES = 1_048_576
MAXIMUM_GOVERNANCE_DOCUMENT_MANIFEST_BYTES = 256 * 1024

_VERSION_TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_POLICY_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_CLASSIFICATION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class GovernanceDocumentArtifactStage(StrEnum):
    CONTENT = "CONTENT"
    MANIFEST = "MANIFEST"


@dataclass(frozen=True, slots=True)
class GovernanceDocumentArtifactKeys:
    content_key: str
    manifest_key: str


def governance_document_artifact_keys(
    *,
    workspace_id: UUID,
    document_id: UUID,
    version_id: UUID,
    document_title: str,
    registered_at: datetime,
    version_number: int,
) -> GovernanceDocumentArtifactKeys:
    identifiers = (workspace_id, document_id, version_id)
    if any(not isinstance(identifier, UUID) or identifier.int == 0 for identifier in identifiers):
        raise ValueError("Governance document artifact identities must be non-zero UUID values.")
    version_prefix = (
        f"{GOVERNANCE_DOCUMENT_ARTIFACT_PREFIX}/{workspace_id}/{document_id}/{version_id}"
    )
    storage_stem = governance_document_storage_stem(
        prefix="doc_governance",
        title=document_title,
        registered_at=registered_at,
        serial_number=version_number,
    )
    return GovernanceDocumentArtifactKeys(
        content_key=f"{version_prefix}/{storage_stem}.html",
        manifest_key=f"{version_prefix}/{storage_stem}.manifest.json",
    )


@dataclass(frozen=True, slots=True)
class GovernanceDocumentArtifactWrite:
    workspace_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str
    registered_at: datetime
    version_number: int
    version_tag: str
    sanitizer_policy_version: str
    sanitizer_policy_sha256: str
    classification: str
    content_html: bytes
    manifest_json: bytes

    def __post_init__(self) -> None:
        governance_document_artifact_keys(
            workspace_id=self.workspace_id,
            document_id=self.document_id,
            version_id=self.version_id,
            document_title=self.document_title,
            registered_at=self.registered_at,
            version_number=self.version_number,
        )
        if not 1 <= self.version_number <= 2_147_483_647:
            raise ValidationError("Governance document version number is outside the safe range.")
        if _VERSION_TAG_PATTERN.fullmatch(self.version_tag) is None:
            raise ValidationError("Governance document version tag is invalid.")
        if _POLICY_VERSION_PATTERN.fullmatch(self.sanitizer_policy_version) is None:
            raise ValidationError("Governance document sanitizer policy version is invalid.")
        if re.fullmatch(r"^[0-9a-f]{64}$", self.sanitizer_policy_sha256) is None:
            raise ValidationError("Governance document sanitizer policy hash is invalid.")
        if _CLASSIFICATION_PATTERN.fullmatch(self.classification) is None:
            raise ValidationError("Governance document classification is invalid.")
        _validate_utf8_payload(
            self.content_html,
            label="HTML",
            maximum_bytes=MAXIMUM_GOVERNANCE_DOCUMENT_HTML_BYTES,
        )
        _validate_utf8_payload(
            self.manifest_json,
            label="manifest",
            maximum_bytes=MAXIMUM_GOVERNANCE_DOCUMENT_MANIFEST_BYTES,
        )
        try:
            manifest = json.loads(self.manifest_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(
                "Governance document manifest is not valid UTF-8 JSON."
            ) from error
        if not isinstance(manifest, dict):
            raise ValidationError("Governance document manifest must be a JSON object.")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content_html).hexdigest()

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.manifest_json).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernanceDocumentObjectReceipt:
    bucket: str
    object_key: str
    provider_version_id: str
    etag: str
    provider_checksum: str
    size_bytes: int
    content_sha256: str
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class GovernanceDocumentArtifactReceipt:
    content: GovernanceDocumentObjectReceipt
    manifest: GovernanceDocumentObjectReceipt


class GovernanceDocumentArtifactCollisionError(ConflictError):
    def __init__(
        self,
        *,
        stage: GovernanceDocumentArtifactStage,
        content_committed: bool,
        provider_code: str,
    ) -> None:
        super().__init__(
            "A governance document artifact key already contains different evidence.",
            details={
                "code": "GOVERNANCE_DOCUMENT_ARTIFACT_COLLISION",
                "artifact_stage": stage.value,
                "content_committed": content_committed,
                "provider_code": provider_code,
            },
        )


class GovernanceDocumentArtifactExternalError(ExternalDependencyError):
    def __init__(
        self,
        message: str,
        *,
        stage: GovernanceDocumentArtifactStage,
        retryable: bool,
        provider_code: str,
        ambiguous_commit: bool,
        content_committed: bool,
    ) -> None:
        super().__init__(
            message,
            dependency="governance_document_artifact_store",
            retryable=retryable,
            provider_code=provider_code,
            ambiguous_commit=ambiguous_commit,
        )
        self.details.update(
            {
                "artifact_stage": stage.value,
                "content_committed": content_committed,
            }
        )


class GovernanceDocumentArtifactStore(Protocol):
    """Create and fully verify one immutable document version.

    The port deliberately exposes no delete, copy, presign, list, or raw provider operation.
    """

    async def ensure_version_artifacts(
        self,
        write: GovernanceDocumentArtifactWrite,
    ) -> GovernanceDocumentArtifactReceipt: ...


def _validate_utf8_payload(content: bytes, *, label: str, maximum_bytes: int) -> None:
    if not content or len(content) > maximum_bytes:
        raise ValidationError(f"Governance document {label} size is outside the safe range.")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"Governance document {label} must be valid UTF-8.") from error
