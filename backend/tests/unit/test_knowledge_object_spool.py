from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from datariver.application.ports import ObjectStore
from datariver.domain.knowledge_pipeline import KnowledgeSourceSnapshot
from datariver.infrastructure.knowledge.object_store import (
    ObjectStoreKnowledgeSourceReader,
    ObjectStoreSpooledKnowledgeSource,
)


class _ObjectStore:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def iter_object_chunks(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> AsyncIterator[bytes]:
        del bucket, object_key
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_knowledge_source_is_hash_verified_into_owner_local_spool_not_joined_bytes(
    tmp_path: Path,
) -> None:
    payload = b"%PDF-" + (b"x" * 8_192)
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="private/source.pdf",
        storage_version="manifest-v1",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=1,
    )
    reader = ObjectStoreKnowledgeSourceReader(
        object_store=cast(ObjectStore, _ObjectStore((payload[:100], payload[100:]))),
        memory_spool_bytes=4_096,
        spool_directory=str(tmp_path),
    )

    spooled = await reader.spool_snapshot(source=source)
    try:
        assert isinstance(spooled, ObjectStoreSpooledKnowledgeSource)
        assert spooled.size_bytes == len(payload)
        assert spooled.content_sha256 == source.content_sha256
        assert spooled.stream.read() == payload
        assert spooled.rolled_to_disk
    finally:
        spooled.close()
