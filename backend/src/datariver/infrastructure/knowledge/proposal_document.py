from __future__ import annotations

import hashlib
from tempfile import SpooledTemporaryFile

from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalDocument,
    KnowledgeStudioProposalJobClaim,
)
from datariver.application.ports import ObjectStore
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.knowledge_studio_proposal_jobs import (
    KnowledgeStudioAcceptedUploadPin,
)

MAXIMUM_PROPOSAL_DOCUMENT_BYTES = 10 * 1024 * 1024


class ObjectStoreKnowledgeStudioProposalDocumentReader:
    """Read one claim-fenced immutable document without exposing its coordinates."""

    def __init__(
        self,
        *,
        object_store: ObjectStore,
        memory_spool_bytes: int,
        spool_directory: str,
    ) -> None:
        if not 4_096 <= memory_spool_bytes <= MAXIMUM_PROPOSAL_DOCUMENT_BYTES:
            raise ValueError("The Knowledge Studio Proposal memory spool limit is invalid.")
        if not spool_directory.startswith("/") or ".." in spool_directory.split("/"):
            raise ValueError("The Knowledge Studio Proposal spool directory is invalid.")
        self._object_store = object_store
        self._memory_spool_bytes = memory_spool_bytes
        self._spool_directory = spool_directory

    async def read_document(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalDocument:
        source = claim.pins.source
        locator = claim.source_locator
        if not isinstance(source, KnowledgeStudioAcceptedUploadPin) or locator is None:
            raise ConflictError(
                "The claimed Proposal job has no document source.",
                details={"code": "STALE_SOURCE_LOCATOR"},
            )
        if source.size_bytes > MAXIMUM_PROPOSAL_DOCUMENT_BYTES:
            raise ValidationError(
                "The accepted Knowledge Studio document exceeds its governed byte limit."
            )
        digest = hashlib.sha256()
        size_bytes = 0
        with SpooledTemporaryFile(
            max_size=self._memory_spool_bytes,
            mode="w+b",
            dir=self._spool_directory,
        ) as stream:
            async for chunk in self._object_store.iter_object_chunks(
                bucket=locator.bucket,
                object_key=locator.object_key,
            ):
                size_bytes += len(chunk)
                if size_bytes > source.size_bytes or size_bytes > MAXIMUM_PROPOSAL_DOCUMENT_BYTES:
                    raise ConflictError(
                        "The accepted Proposal document grew after its immutable pin.",
                        details={"code": "STALE_SOURCE_CONTENT"},
                    )
                digest.update(chunk)
                stream.write(chunk)
            if size_bytes != source.size_bytes or digest.hexdigest() != source.content_sha256:
                raise ConflictError(
                    "The accepted Proposal document no longer matches its immutable pin.",
                    details={"code": "STALE_SOURCE_CONTENT"},
                )
            stream.seek(0)
            content = stream.read()
        return KnowledgeStudioProposalDocument(
            filename=source.filename,
            media_type=source.media_type,
            content=content,
        )
