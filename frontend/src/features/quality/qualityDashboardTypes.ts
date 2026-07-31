import type {
  QualityExpectationOutcome,
  QualityOutcome,
  QualityRuleKind,
  QualityRuleSeverity,
} from '../../api/types'

export type QualityIndicatorId = 'ACCURACY' | 'COMPLETENESS' | 'TIMELINESS'

export interface QualityManagedRuleSet {
  indicator_id: QualityIndicatorId
  name: string
  definition: string
  calculation: string
  target_grain: 'FIELD' | 'TABLE'
  rule_kinds: QualityRuleKind[]
  contract_version: 'QUALITY_MANAGED_INDICATORS_V1'
}

export interface QualityDashboardRisk {
  risk_id: string
  asset_id: string
  asset_name: string
  field_identifier: string | null
  severity: QualityRuleSeverity
  outcome: Exclude<QualityExpectationOutcome, 'PASS'>
  score_basis_points: number | null
  evaluated_count: number | null
  failed_count: number | null
  observed_at: string | null
  detail: string
}

export interface QualityDashboardIndicator {
  indicator_id: QualityIndicatorId
  counted_target_count: number
  target_count: number
  coverage_basis_points: number | null
  score_basis_points: number | null
  outcome: QualityOutcome
  risk_count: number
  evaluated_value_count: number
  report_state: 'FACTS_ONLY' | 'LLM_GENERATED' | 'UNAVAILABLE'
  report_reason_code: string | null
  report_summary: string
  risks: QualityDashboardRisk[]
}

export interface QualitySchemaDashboard {
  schema_id: string
  platform: string | null
  database_name: string | null
  schema_name: string | null
  table_count: number
  covered_table_count: number
  indicators: QualityDashboardIndicator[]
}

export interface QualityDashboard {
  contract_version: 'QUALITY_DASHBOARD_V1'
  cache_scope: string
  observed_at: string
  authorization_valid_until: string
  as_of: string
  schema_count: number
  table_count: number
  active_rule_set_count: number
  common_rule_template_count: number
  covered_table_count: number
  table_coverage_basis_points: number | null
  managed_rule_sets: QualityManagedRuleSet[]
  schemas: QualitySchemaDashboard[]
  schemas_truncated: boolean
}
