from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from datariver.application.errors import ExternalDependencyError
from datariver.application.governance_document_storage_names import (
    governance_document_attachment_filename,
)
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.governance_documents import (
    MAXIMUM_ATTACHMENT_BYTES,
    GovernanceDocumentAttachment,
)

MAXIMUM_GOVERNANCE_DOCUMENT_ATTACHMENT_BYTES = MAXIMUM_ATTACHMENT_BYTES
_CLASSIFICATION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def governance_document_attachment_key(
    *,
    workspace_id: UUID,
    document_id: UUID,
    version_id: UUID,
    attachment_id: UUID,
    storage_filename: str | None = None,
) -> str:
    identifiers = (workspace_id, document_id, version_id, attachment_id)
    if any(not isinstance(identifier, UUID) or identifier.int == 0 for identifier in identifiers):
        raise ValueError("Governance document attachment identities must be non-zero UUID values.")
    prefix = (
        "governance/documents/v1/"
        f"{workspace_id}/{document_id}/{version_id}/attachments/{attachment_id}"
    )
    if storage_filename is None:
        return prefix
    if (
        not storage_filename
        or len(storage_filename) > 255
        or "/" in storage_filename
        or "\\" in storage_filename
        or storage_filename in {".", ".."}
    ):
        raise ValidationError("Governance document attachment storage filename is invalid.")
    return f"{prefix}/{storage_filename}"


@dataclass(frozen=True, slots=True)
class GovernanceDocumentAttachmentWrite:
    workspace_id: UUID
    document_id: UUID
    version_id: UUID
    attachment_id: UUID
    document_title: str
    registered_at: datetime
    serial_number: int
    original_name: str
    classification: str
    content: bytes

    def __post_init__(self) -> None:
        storage_filename = governance_document_attachment_filename(
            title=self.document_title,
            registered_at=self.registered_at,
            serial_number=self.serial_number,
            original_name=self.original_name,
        )
        governance_document_attachment_key(
            workspace_id=self.workspace_id,
            document_id=self.document_id,
            version_id=self.version_id,
            attachment_id=self.attachment_id,
            storage_filename=storage_filename,
        )
        if _CLASSIFICATION_PATTERN.fullmatch(self.classification) is None:
            raise ValidationError("Governance document attachment classification is invalid.")
        if not 1 <= len(self.content) <= MAXIMUM_ATTACHMENT_BYTES:
            raise ValidationError("Governance document attachment size is outside the safe range.")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def storage_filename(self) -> str:
        return governance_document_attachment_filename(
            title=self.document_title,
            registered_at=self.registered_at,
            serial_number=self.serial_number,
            original_name=self.original_name,
        )


@dataclass(frozen=True, slots=True)
class GovernanceDocumentAttachmentReceipt:
    bucket: str
    object_key: str
    provider_version_id: str
    etag: str
    provider_checksum: str
    size_bytes: int
    content_sha256: str
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class GovernanceDocumentAttachmentSource:
    attachment: GovernanceDocumentAttachment
    bucket: str
    object_key: str
    provider_version_id: str

    def __post_init__(self) -> None:
        if not self.bucket or not self.object_key or not self.provider_version_id:
            raise ValueError("Governance document attachment source evidence is incomplete.")


@dataclass(frozen=True, slots=True)
class GovernanceDocumentAttachmentDownload:
    attachment: GovernanceDocumentAttachment
    url: str
    expires_at_epoch_seconds: int


class GovernanceDocumentAttachmentCollisionError(ConflictError):
    def __init__(self, *, provider_code: str) -> None:
        super().__init__(
            "A governance document attachment key already contains different evidence.",
            details={
                "code": "GOVERNANCE_DOCUMENT_ATTACHMENT_COLLISION",
                "provider_code": provider_code,
            },
        )


class GovernanceDocumentAttachmentExternalError(ExternalDependencyError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        provider_code: str,
        ambiguous_commit: bool,
    ) -> None:
        super().__init__(
            message,
            dependency="governance_document_attachment_store",
            retryable=retryable,
            provider_code=provider_code,
            ambiguous_commit=ambiguous_commit,
        )


class GovernanceDocumentAttachmentStore(Protocol):
    """Create and verify immutable attachment evidence without destructive operations."""

    async def ensure_attachment(
        self,
        write: GovernanceDocumentAttachmentWrite,
    ) -> GovernanceDocumentAttachmentReceipt: ...

    async def presign_download(
        self,
        source: GovernanceDocumentAttachmentSource,
        *,
        expires_seconds: int,
    ) -> str: ...
