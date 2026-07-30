export type GovernanceDocumentCapabilityState = 'AVAILABLE' | 'DENIED' | 'UNAVAILABLE'

export type GovernanceDocumentCapabilityId =
  | 'read'
  | 'create'
  | 'edit'
  | 'review'
  | 'publish'
  | 'archive'
  | 'template_manage'
  | 'artifact_storage'
  | 'knowledge_projection'

export interface GovernanceDocumentCapabilityAxis {
  id: GovernanceDocumentCapabilityId
  state: GovernanceDocumentCapabilityState
  reason_code: string | null
}

export interface GovernanceDocumentCapability {
  contract_version: 'GOVERNANCE_DOCUMENT_CAPABILITY_V1'
  observed_at: string
  valid_until: string
  cache_scope: string
  axes: GovernanceDocumentCapabilityAxis[]
  limits: {
    max_html_bytes: number
    max_attachment_bytes: number
    max_attachments_per_version: number
  }
}

export type GovernanceDocumentKind = 'DOCUMENT' | 'TEMPLATE'

export type GovernanceDocumentCategory =
  | 'POLICY'
  | 'STANDARD_TERMINOLOGY'
  | 'SECURITY_GUIDE'
  | 'OTHER'

export type GovernanceDocumentState = 'DRAFT' | 'ACTIVE' | 'ARCHIVED'

export type GovernanceDocumentVersionState =
  | 'DRAFT'
  | 'IN_REVIEW'
  | 'PUBLISHED'
  | 'REJECTED'
  | 'SUPERSEDED'

export type GovernanceDocumentAction =
  | 'read'
  | 'create_version'
  | 'submit'
  | 'review'
  | 'publish'
  | 'archive'
  | 'add_attachment'
  | 'instantiate_template'

export type GovernanceDocumentSourceFormat = 'HTML' | 'MARKDOWN' | 'DOCX'

export interface GovernancePageMeta {
  next_cursor: string | null
  limit: number
}

export interface GovernanceReadEnvelope {
  cache_scope: string
  observed_at: string
  authorization_valid_until: string
}

export interface GovernanceDocumentSummary {
  document_id: string
  workspace_id: string
  kind: GovernanceDocumentKind
  category: GovernanceDocumentCategory
  title: string
  summary: string
  classification: number
  state: GovernanceDocumentState
  owner_subject_id: string
  current_published_version_id: string | null
  current_version_number: number | null
  created_at: string
  updated_at: string
  version: number
  allowed_actions: GovernanceDocumentAction[]
}

export interface GovernanceDocumentListResponse extends GovernanceReadEnvelope {
  items: GovernanceDocumentSummary[]
  page: GovernancePageMeta
}

export interface GovernanceDocumentVersion {
  version_id: string
  workspace_id: string
  document_id: string
  version_number: number
  version_tag: string
  state: GovernanceDocumentVersionState
  title: string
  summary: string
  applicability_scope: string
  sanitized_html: string
  plain_text: string
  content_sha256: string
  size_bytes: number
  sanitizer_policy_version: string
  sanitizer_policy_sha256: string
  source_format: GovernanceDocumentSourceFormat
  source_template_version_id: string | null
  author_id: string
  submitted_at: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  published_at: string | null
  artifact_state: 'PENDING' | 'STORED' | 'FAILED'
  knowledge_state: 'PENDING' | 'PROJECTING' | 'READY' | 'FAILED'
  created_at: string
  version: number
}

export interface GovernanceDocumentAttachment {
  attachment_id: string
  workspace_id: string
  document_id: string
  document_version_id: string
  original_name: string
  content_type: string
  size_bytes: number
  content_sha256: string
  uploaded_by: string
  created_at: string
}

export interface GovernanceDocumentReview {
  review_id: string
  workspace_id: string
  document_id: string
  document_version_id: string
  decision: 'APPROVE' | 'REJECT'
  reviewer_id: string
  reason: string
  policy_decision_id: string
  authentication_assurance: string
  created_at: string
}

export interface GovernanceDocumentDetail {
  document: GovernanceDocumentSummary
  versions: GovernanceDocumentVersion[]
  reviews: GovernanceDocumentReview[]
  attachments: GovernanceDocumentAttachment[]
}

export interface GovernanceDocumentDetailResponse extends GovernanceReadEnvelope {
  item: GovernanceDocumentDetail
}

export interface GovernanceDocumentCreateRequest {
  kind: GovernanceDocumentKind
  category: GovernanceDocumentCategory
  title: string
  summary: string
  classification: number
  applicability_scope: string
  sanitized_html: string | null
  source_template_version_id: string | null
}

export interface GovernanceDocumentVersionCreateRequest {
  title: string
  summary?: string | null
  applicability_scope: string
  sanitized_html: string
  source_template_version_id?: string | null
}

export interface GovernanceDocumentReviewRequest {
  decision: 'APPROVE' | 'REJECT'
  reason: string
}

export interface GovernanceDocumentCommandResponse {
  item: GovernanceDocumentDetail
}

export interface GovernanceDocumentBlueprint {
  blueprint_id: string
  blueprint_version: 'GOVERNANCE_DOCUMENT_BLUEPRINTS_V1'
  category: Exclude<GovernanceDocumentCategory, 'OTHER'>
  title: string
  summary: string
  applicability_scope: string
  sanitized_html: string
  content_sha256: string
  sanitizer_policy_version: string
  sanitizer_policy_sha256: string
}

export interface GovernanceDocumentBlueprintListResponse {
  contract_version: 'GOVERNANCE_DOCUMENT_BLUEPRINTS_V1'
  items: GovernanceDocumentBlueprint[]
}

export interface GovernanceKnowledgeEvidence {
  chunk_id: string
  document_id: string
  document_version_id: string
  document_title: string
  version_tag: string
  ordinal: number
  excerpt: string
  content_sha256: string
  score_basis_points: number
  classification: number
  published_at: string
}

export interface GovernanceKnowledgeEvidenceResponse extends GovernanceReadEnvelope {
  items: GovernanceKnowledgeEvidence[]
}
