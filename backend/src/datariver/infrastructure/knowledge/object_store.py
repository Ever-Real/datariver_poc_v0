from __future__ import annotations

import hashlib
from dataclasses import dataclass
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, cast

from datariver.application.knowledge_pipeline_ports import (
    SpooledKnowledgeSource as SpooledKnowledgeSourcePort,
)
from datariver.application.ports import ObjectStore
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import MAX_SOURCE_BYTES, KnowledgeSourceSnapshot


@dataclass(slots=True)
class ObjectStoreSpooledKnowledgeSource:
    stream: BinaryIO
    size_bytes: int
    content_sha256: str

    @property
    def rolled_to_disk(self) -> bool:
        return bool(getattr(self.stream, "_rolled", False))

    def close(self) -> None:
        self.stream.close()


class ObjectStoreKnowledgeSourceReader:
    """Reads only the immutable bucket/key recorded in a governed source snapshot."""

    def __init__(
        self,
        *,
        object_store: ObjectStore,
        memory_spool_bytes: int = 1_048_576,
        spool_directory: str | None = None,
    ) -> None:
        if not 4_096 <= memory_spool_bytes <= MAX_SOURCE_BYTES:
            raise ValueError("The Knowledge source memory spool limit is invalid.")
        self._object_store = object_store
        self._memory_spool_bytes = memory_spool_bytes
        self._spool_directory = spool_directory

    async def read_snapshot(self, *, source: KnowledgeSourceSnapshot) -> bytes:
        spooled = await self.spool_snapshot(source=source)
        try:
            return spooled.stream.read()
        finally:
            spooled.close()

    async def spool_snapshot(
        self,
        *,
        source: KnowledgeSourceSnapshot,
    ) -> SpooledKnowledgeSourcePort:
        if source.byte_size > MAX_SOURCE_BYTES:
            raise ValidationError("The knowledge source exceeds the governed byte limit.")
        stream = SpooledTemporaryFile(
            max_size=self._memory_spool_bytes,
            mode="w+b",
            dir=self._spool_directory,
        )
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            async for chunk in self._object_store.iter_object_chunks(
                bucket=source.bucket,
                object_key=source.object_key,
            ):
                size_bytes += len(chunk)
                if size_bytes > source.byte_size or size_bytes > MAX_SOURCE_BYTES:
                    raise ValidationError("The knowledge source grew after its immutable snapshot.")
                digest.update(chunk)
                stream.write(chunk)
            content_sha256 = digest.hexdigest()
            source.verify_observation(
                byte_size=size_bytes,
                content_sha256=content_sha256,
            )
            stream.seek(0)
            return ObjectStoreSpooledKnowledgeSource(
                stream=cast(BinaryIO, stream),
                size_bytes=size_bytes,
                content_sha256=content_sha256,
            )
        except Exception:
            stream.close()
            raise
