from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from datariver.application.dto import ChatEvidence
from datariver.domain.authz import Classification


def build_evidence_chunk(
    *,
    workspace_id: UUID,
    resource_id: UUID,
    classification: Classification,
    system_id: UUID | None,
    domain_id: UUID | None,
    owner_department_id: UUID | None,
    name: str,
    description: str | None,
    source_locator: str,
    source_version: str,
    effective_from: datetime,
    effective_until: datetime | None = None,
    extraction_method: str,
    source_type: str = "CATALOG_ASSET",
) -> ChatEvidence:
    if (
        not name.strip()
        or not source_locator.strip()
        or not source_version.strip()
        or not extraction_method.strip()
        or not source_type.strip()
    ):
        raise ValueError("Evidence identity and source fields must not be empty.")
    if effective_from.tzinfo is None or (
        effective_until is not None and effective_until.tzinfo is None
    ):
        raise ValueError("Evidence effective timestamps must include a timezone.")
    if effective_until is not None and effective_until < effective_from:
        raise ValueError("Evidence effective_until must not precede effective_from.")
    document = _evidence_document(
        workspace_id=workspace_id,
        resource_id=resource_id,
        classification=classification,
        system_id=system_id,
        domain_id=domain_id,
        owner_department_id=owner_department_id,
        name=name,
        description=description,
        source_locator=source_locator,
        source_version=source_version,
        effective_from=effective_from,
        effective_until=effective_until,
        extraction_method=extraction_method,
        source_type=source_type,
    )
    content_hash = hashlib.sha256(_canonical_bytes(document)).hexdigest()
    return ChatEvidence(
        chunk_id=uuid5(NAMESPACE_URL, f"urn:datariver:evidence-chunk:{content_hash}"),
        workspace_id=workspace_id,
        resource_id=resource_id,
        classification=classification,
        system_id=system_id,
        domain_id=domain_id,
        owner_department_id=owner_department_id,
        name=name,
        description=description,
        source_locator=source_locator,
        source_version=source_version,
        content_hash=content_hash,
        effective_from=effective_from,
        effective_until=effective_until,
        extraction_method=extraction_method,
        source_type=source_type,
    )


def evidence_chunk_is_valid(chunk: ChatEvidence) -> bool:
    expected = build_evidence_chunk(
        workspace_id=chunk.workspace_id,
        resource_id=chunk.resource_id,
        classification=chunk.classification,
        system_id=chunk.system_id,
        domain_id=chunk.domain_id,
        owner_department_id=chunk.owner_department_id,
        name=chunk.name,
        description=chunk.description,
        source_locator=chunk.source_locator,
        source_version=chunk.source_version,
        effective_from=chunk.effective_from,
        effective_until=chunk.effective_until,
        extraction_method=chunk.extraction_method,
        source_type=chunk.source_type,
    )
    return expected.chunk_id == chunk.chunk_id and expected.content_hash == chunk.content_hash


def _evidence_document(
    *,
    workspace_id: UUID,
    resource_id: UUID,
    classification: Classification,
    system_id: UUID | None,
    domain_id: UUID | None,
    owner_department_id: UUID | None,
    name: str,
    description: str | None,
    source_locator: str,
    source_version: str,
    effective_from: datetime,
    effective_until: datetime | None,
    extraction_method: str,
    source_type: str,
) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "resource_id": str(resource_id),
        "classification": int(classification),
        "authorization_scope": {
            "system_id": str(system_id) if system_id is not None else None,
            "domain_id": str(domain_id) if domain_id is not None else None,
            "owner_department_id": (
                str(owner_department_id) if owner_department_id is not None else None
            ),
        },
        "name": name,
        "description": description,
        "source_type": source_type,
        "source_locator": source_locator,
        "source_version": source_version,
        "effective_from": effective_from.isoformat(),
        "effective_until": effective_until.isoformat() if effective_until is not None else None,
        "extraction_method": extraction_method,
    }


def _canonical_bytes(document: dict[str, object]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
