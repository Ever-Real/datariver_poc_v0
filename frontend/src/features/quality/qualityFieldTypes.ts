import type {
  QualityAsset,
  QualityAssetAuthoring,
  QualityAuthoringField,
  QualityAuthoringLogicalType,
  QualityAuthoringRuleKind,
  QualityOutcome,
  QualityRuleDraftRequest,
  QualityRuleSetSummary,
  QualityRuleSetVersionState,
  QualityRuleSeverity,
  QualityRunState,
  QualityRunSummary,
  QualityTrendPoint,
} from '../../api/types'

export interface QualityScorePolicy {
  policy_id: 'UNWEIGHTED_RULE_PASS_RATE_V1'
  policy_version: 1
  policy_hash: string
  calculation: string
  pass_condition: string
  warn_condition: string
  fail_condition: string
  unknown_condition: string
}

export interface QualityAssetField extends QualityAuthoringField {
  configured_rule_count: number
  active_rule_count: number
  evaluated_rule_count: number
  passed_count: number
  advisory_failed_count: number
  blocking_failed_count: number
  latest_score_basis_points: number | null
  latest_quality_outcome: QualityOutcome
  latest_evaluated_at: string | null
}

export interface QualityAssetFieldWorkspace {
  asset: QualityAsset
  rule_sets: QualityRuleSetSummary[]
  runs: QualityRunSummary[]
  trend: QualityTrendPoint[]
  authoring: QualityAssetAuthoring
  fields: QualityAssetField[]
  score_policy: QualityScorePolicy
}

export interface QualityFieldRule {
  rule_definition_id: string
  rule_set_id: string
  rule_set_name: string
  version_id: string
  version_number: number
  version_state: Extract<QualityRuleSetVersionState, 'PROPOSED' | 'APPROVED' | 'ACTIVE'>
  kind: QualityAuthoringRuleKind
  severity: QualityRuleSeverity
  parameters: Record<string, unknown>
}

export interface QualityFieldRun {
  run_id: string
  rule_set_id: string
  rule_set_name: string
  state: QualityRunState
  run_quality_outcome: QualityOutcome
  field_quality_outcome: QualityOutcome
  score_basis_points: number | null
  passed_count: number
  advisory_failed_count: number
  blocking_failed_count: number
  evaluated_value_count: number
  missing_count: number
  unexpected_count: number
  created_at: string
  completed_at: string | null
  failure_code: string | null
}

export interface QualityFieldWorkspace {
  asset_id: string
  field: QualityAuthoringField
  rules: QualityFieldRule[]
  runs: QualityFieldRun[]
  trend: QualityTrendPoint[]
  score_policy: QualityScorePolicy
}

export interface QualityRuleTargetRequest {
  asset_id: string
  rules: QualityRuleDraftRequest[]
}

export interface QualityTargetedRuleProposalRequest {
  name_prefix: string
  targets: QualityRuleTargetRequest[]
}

export interface QualityTemplateFieldBindingRequest {
  template_rule_ordinal: number
  field_identifier: string
  parameters_override?: Record<string, unknown> | null
}

export interface QualityTemplateTargetRequest {
  asset_id: string
  bindings: QualityTemplateFieldBindingRequest[]
}

export interface QualityTemplateMappingRequest {
  targets: QualityTemplateTargetRequest[]
}

export interface QualityFieldSelection {
  asset_id: string
  asset_name: string
  platform?: string | null
  database_name?: string | null
  schema_name?: string | null
  field_identifier: string
  display_path: string
  logical_type: QualityAuthoringLogicalType
  supported_rule_kinds: QualityAuthoringRuleKind[]
}
