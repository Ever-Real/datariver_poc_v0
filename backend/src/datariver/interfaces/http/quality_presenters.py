from __future__ import annotations

from dataclasses import asdict

from datariver.application.quality_read_contracts import (
    QualityAssetSummary,
    QualityIssueSummary,
    QualityOverview,
    QualityResultSummary,
    QualityRuleSetDetail,
    QualityRuleSetSummary,
    QualityRunSummary,
)
from datariver.interfaces.http.quality_schemas import (
    QualityAssetResponse,
    QualityIssueResponse,
    QualityOverviewResponse,
    QualityResultResponse,
    QualityRuleSetDetailItemResponse,
    QualityRuleSetResponse,
    QualityRunResponse,
)


def quality_overview_response(value: QualityOverview) -> QualityOverviewResponse:
    return QualityOverviewResponse.model_validate(asdict(value))


def quality_asset_response(value: QualityAssetSummary) -> QualityAssetResponse:
    return QualityAssetResponse.model_validate(asdict(value))


def quality_rule_set_response(value: QualityRuleSetSummary) -> QualityRuleSetResponse:
    return QualityRuleSetResponse.model_validate(asdict(value))


def quality_rule_set_detail_response(
    value: QualityRuleSetDetail,
) -> QualityRuleSetDetailItemResponse:
    return QualityRuleSetDetailItemResponse.model_validate(asdict(value))


def quality_run_response(value: QualityRunSummary) -> QualityRunResponse:
    return QualityRunResponse.model_validate(asdict(value))


def quality_result_response(value: QualityResultSummary) -> QualityResultResponse:
    document = asdict(value)
    document["missing_ratio"] = float(value.missing_ratio)
    document["unexpected_ratio"] = float(value.unexpected_ratio)
    return QualityResultResponse.model_validate(document)


def quality_issue_response(value: QualityIssueSummary) -> QualityIssueResponse:
    return QualityIssueResponse.model_validate(asdict(value))
