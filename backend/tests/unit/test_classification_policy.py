from __future__ import annotations

from typing import cast
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import (
    ClassificationAccessPosture,
    ClassificationAccessSnapshot,
    ClassificationRuleRecord,
)
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.classification_access import ChatMode, SearchMode
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

    classification_sets = [value for value in compiled.params.values() if isinstance(value, list)]
    assert [0, 1, 2] in classification_sets
    assert all(int(Classification.RESTRICTED) not in values for values in classification_sets)


def test_catalog_sql_scope_requires_exact_governed_restricted_scope() -> None:
    workspace_id = uuid4()
    system_id = uuid4()
    domain_id = uuid4()
    granted_asset_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.RESTRICTED,
        allowed_system_ids=frozenset({system_id}),
        allowed_domain_ids=frozenset({domain_id}),
    )
    rules = tuple(
        ClassificationRuleRecord(
            classification=classification,
            search_mode=(
                SearchMode.EXPLICIT_GRANT_ONLY
                if classification is Classification.RESTRICTED
                else SearchMode.ABAC
            ),
            chat_mode=ChatMode.DENY,
            provider_profile_version_id=None,
        )
        for classification in Classification
    )
    access = ClassificationAccessSnapshot(
        posture=ClassificationAccessPosture.GOVERNED,
        policy_id=uuid4(),
        policy_hash="a" * 64,
        policy_version=2,
        required_jurisdiction="jurisdiction-a",
        authorization_generation=7,
        rules=rules,
        restricted_resource_ids=frozenset({granted_asset_id}),
        restricted_system_ids=frozenset(),
        restricted_domain_ids=frozenset(),
        nearest_validity_boundary=None,
    )
    reader = SqlCatalogIndexReader(cast(AsyncSession, object()))
    statement = select(AssetProjectionModel.id).where(
        and_(*reader._scope_conditions(subject, access))
    )
    compiled = statement.compile()

    expanding_values = [value for value in compiled.params.values() if isinstance(value, list)]
    assert [0, 1, 2] in expanding_values
    assert [granted_asset_id] in expanding_values
    assert [system_id] in expanding_values
    assert [domain_id] in expanding_values
