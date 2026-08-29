from __future__ import annotations

import inspect
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from datariver.application.services.governance import GovernanceService
from datariver.domain.catalog_recommendations import (
    CatalogRecommendationDraft,
    CatalogRecommendationProviderResult,
)
from datariver.domain.common import ValidationError
from datariver.interfaces.http.schemas import (
    CatalogRecommendationApproveRequest,
    CatalogRecommendationPreviewRequest,
)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("inf"), float("nan")])
def test_recommendation_confidence_is_bounded(confidence: float) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        CatalogRecommendationDraft(
            vocabulary_id=uuid4(),
            confidence=confidence,
            reason="reason",
            evidence=("evidence",),
        )


@pytest.mark.parametrize(
    ("reason", "evidence"),
    [
        ("", ("evidence",)),
        ("x" * 2_001, ("evidence",)),
        ("reason", ()),
        ("reason", tuple("evidence" for _ in range(11))),
        ("reason", ("x" * 1_001,)),
    ],
)
def test_recommendation_reason_and_evidence_are_bounded(
    reason: str,
    evidence: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        CatalogRecommendationDraft(
            vocabulary_id=uuid4(),
            confidence=0.5,
            reason=reason,
            evidence=evidence,
        )


def test_provider_result_rejects_truncation_duplicates_and_unbounded_provenance() -> None:
    vocabulary_id = uuid4()
    draft = CatalogRecommendationDraft(vocabulary_id, 0.5, "reason", ("evidence",))
    with pytest.raises(ValidationError, match="truncated"):
        CatalogRecommendationProviderResult(
            (draft,),
            "provider",
            "model",
            "prompt",
            "rule",
            truncated=True,
        )
    with pytest.raises(ValidationError, match="duplicate"):
        CatalogRecommendationProviderResult(
            (draft, draft),
            "provider",
            "model",
            "prompt",
            "rule",
        )
    with pytest.raises(ValidationError, match="provider"):
        CatalogRecommendationProviderResult(
            (draft,),
            "x" * 129,
            "model",
            "prompt",
            "rule",
        )


def test_http_contract_rejects_duplicate_or_over_bound_batches() -> None:
    vocabulary_id = uuid4()
    with pytest.raises(PydanticValidationError, match="unique"):
        CatalogRecommendationPreviewRequest(
            source_version="source-v1",
            vocabulary_ids=[vocabulary_id, vocabulary_id],
        )
    with pytest.raises(PydanticValidationError):
        CatalogRecommendationPreviewRequest(
            source_version="source-v1",
            vocabulary_ids=[uuid4() for _ in range(101)],
        )
    with pytest.raises(PydanticValidationError):
        CatalogRecommendationApproveRequest(
            targets=[{"recommendation_id": uuid4(), "expected_version": 1} for _ in range(101)],
            title="Approve",
            reason="Reviewed",
        )
    with pytest.raises(PydanticValidationError):
        CatalogRecommendationApproveRequest(
            targets=[{"recommendation_id": uuid4(), "expected_version": 1}],
            title="Approve",
            reason=" padded ",
        )


def test_catalog_atomic_extension_is_narrow_and_wired_to_one_request_session() -> None:
    ordinary = inspect.signature(GovernanceService.create_change_request)
    specialized = inspect.signature(GovernanceService.create_catalog_recommendation_change_request)
    assert "finalize_decision" not in ordinary.parameters
    assert "before_commit" not in ordinary.parameters
    assert "finalize_decision" not in specialized.parameters
    assert "before_commit" not in specialized.parameters
    assert "recommendation_finalizer" in specialized.parameters

    root = Path(__file__).resolve().parents[3]
    route = (root / "backend/src/datariver/interfaces/http/routes/catalog.py").read_text(
        encoding="utf-8"
    )
    factory = route.split("def _recommendation_service", maxsplit=1)[1].split(
        "def _recommendation_response", maxsplit=1
    )[0]
    assert "transaction_session = session" in factory
    assert "session=transaction_session" in factory
    assert "SqlCatalogRecommendationStore(transaction_session)" in factory
