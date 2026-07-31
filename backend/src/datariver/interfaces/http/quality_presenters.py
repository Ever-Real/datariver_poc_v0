from __future__ import annotations

from dataclasses import asdict

from datariver.application.quality_command_contracts import (
    QualityAssetAuthoringDetail,
    QualityAuthoringField,
)
from datariver.application.quality_read_contracts import (
    QualityAssetSummary,
    QualityAssetWorkspace,
    QualityCommonRuleTemplateDetail,
    QualityCommonRuleTemplateSummary,
    QualityFieldWorkspace,
    QualityIssueSummary,
    QualityOverview,
    QualityResultSummary,
    QualityRuleSetDetail,
    QualityRuleSetSummary,
    QualityRunSummary,
)
from datariver.interfaces.http.quality_schemas import (
    QualityAssetResponse,
    QualityAssetWorkspaceItemResponse,
    QualityCommonRuleTemplateDetailItemResponse,
    QualityCommonRuleTemplateResponse,
    QualityFieldWorkspaceItemResponse,
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


def quality_asset_workspace_response(
    value: QualityAssetWorkspace,
    authoring: QualityAssetAuthoringDetail,
) -> QualityAssetWorkspaceItemResponse:
    document = asdict(value)
    summaries = {field.field_identifier: field for field in value.fields}
    document["authoring"] = asdict(authoring)
    document["fields"] = [
        {
            **asdict(field),
            **(
                asdict(summaries[field.field_identifier])
                if field.field_identifier in summaries
                else {
                    "configured_rule_count": 0,
                    "active_rule_count": 0,
                    "evaluated_rule_count": 0,
                    "passed_count": 0,
                    "advisory_failed_count": 0,
                    "blocking_failed_count": 0,
                    "latest_score_basis_points": None,
                    "latest_quality_outcome": "UNKNOWN",
                    "latest_evaluated_at": None,
                }
            ),
        }
        for field in authoring.fields
    ]
    return QualityAssetWorkspaceItemResponse.model_validate(document)


def quality_field_workspace_response(
    value: QualityFieldWorkspace,
    field: QualityAuthoringField,
) -> QualityFieldWorkspaceItemResponse:
    document = asdict(value)
    document.pop("field_identifier")
    document["field"] = asdict(field)
    return QualityFieldWorkspaceItemResponse.model_validate(document)


def quality_common_rule_template_response(
    value: QualityCommonRuleTemplateSummary,
) -> QualityCommonRuleTemplateResponse:
    return QualityCommonRuleTemplateResponse.model_validate(asdict(value))


def quality_common_rule_template_detail_response(
    value: QualityCommonRuleTemplateDetail,
) -> QualityCommonRuleTemplateDetailItemResponse:
    return QualityCommonRuleTemplateDetailItemResponse.model_validate(asdict(value))


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
