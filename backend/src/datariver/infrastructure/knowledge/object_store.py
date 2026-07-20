from __future__ import annotations

from datariver.application.ports import ObjectStore
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import MAX_SOURCE_BYTES, KnowledgeSourceSnapshot


class ObjectStoreKnowledgeSourceReader:
    """Reads only the immutable bucket/key recorded in a governed source snapshot."""

    def __init__(self, *, object_store: ObjectStore) -> None:
        self._object_store = object_store

    async def read_snapshot(self, *, source: KnowledgeSourceSnapshot) -> bytes:
        if source.byte_size > MAX_SOURCE_BYTES:
            raise ValidationError("The knowledge source exceeds the governed byte limit.")
        payload = bytearray()
        async for chunk in self._object_store.iter_object_chunks(
            bucket=source.bucket,
            object_key=source.object_key,
        ):
            payload.extend(chunk)
            if len(payload) > source.byte_size:
                raise ValidationError("The knowledge source grew after its immutable snapshot.")
        return bytes(payload)
