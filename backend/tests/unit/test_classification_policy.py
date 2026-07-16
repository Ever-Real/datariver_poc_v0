from __future__ import annotations

from typing import cast
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.classification_policy import (
    unconfigured_chat_ceiling,
    unconfigured_chat_evidence_allowed,
    unconfigured_search_ceiling,
)
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.models.catalog import AssetProjectionModel


def test_unconfigured_access_floors_fail_closed_for_protected_classes() -> None:
    assert unconfigured_search_ceiling(Classification.RESTRICTED) is Classification.CONFIDENTIAL
    assert unconfigured_chat_ceiling(Classification.RESTRICTED) is Classification.INTERNAL
    assert unconfigured_chat_evidence_allowed(Classification.INTERNAL)
    assert not unconfigured_chat_evidence_allowed(Classification.CONFIDENTIAL)
    assert not unconfigured_chat_evidence_allowed(Classification.RESTRICTED)


def test_catalog_sql_scope_excludes_restricted_without_governed_grant() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.RESTRICTED,
    )
    reader = SqlCatalogIndexReader(cast(AsyncSession, object()))
    statement = select(AssetProjectionModel.id).where(and_(*reader._scope_conditions(subject)))
    compiled = statement.compile()

    assert int(Classification.CONFIDENTIAL) in compiled.params.values()
    assert int(Classification.RESTRICTED) not in compiled.params.values()
