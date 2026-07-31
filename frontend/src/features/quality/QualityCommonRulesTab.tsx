import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Search } from 'lucide-react'
import type {
  QualityAsset,
  QualityAssetDetailResponse,
  QualityCapabilityAxis,
  QualityCommonRuleTemplate,
  QualityCommonRuleTemplateCreateRequest,
  QualityRuleDraftRequest,
  QualityRuleSeverity,
} from '../../api/types'
import { newIdempotencyKey } from '../../api/client'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'
import { qualityQueryKey, type QualityApi, type QualitySecurityBoundary } from './qualityApi'
import {
  countText,
  dateTimeText,
  optionalText,
  QualityStatus,
} from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'

interface TemplateRuleDraft {
  field_identifier: string
  kind: 'NOT_NULL' | 'RANGE'
  severity: QualityRuleSeverity
  value_type: 'DECIMAL' | 'DATE' | 'TIMESTAMP'
  min_value: string
  max_value: string
}

const emptyRule = (): TemplateRuleDraft => ({
  field_identifier: '',
  kind: 'NOT_NULL',
  severity: 'BLOCKING',
  value_type: 'DECIMAL',
  min_value: '',
  max_value: '',
})

export function QualityCommonRulesTab({
  api,
  boundary,
  axes,
  selectedTemplateId,
  onSelectedTemplate,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: Map<string, QualityCapabilityAxis>
  selectedTemplateId?: string
  onSelectedTemplate: (templateId?: string) => void
  onBoundaryInvalid: () => void
}) {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [mappingOpen, setMappingOpen] = useState(false)
  const [notice, setNotice] = useState<string>()
  const templates = useQuery({
    queryKey: qualityQueryKey(boundary, 'common-rule-templates'),
    queryFn: ({ signal }) => api.commonRuleTemplates(boundary.cacheScope, signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const detail = useQuery({
    queryKey: qualityQueryKey(
      boundary,
      'common-rule-template-detail',
      selectedTemplateId,
    ),
    queryFn: ({ signal }) => api.commonRuleTemplate(
      selectedTemplateId ?? '',
      boundary.cacheScope,
      signal,
    ),
    enabled: Boolean(selectedTemplateId),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (
      isAuthorizationBoundaryError(templates.error)
      || isAuthorizationBoundaryError(detail.error)
    ) {
      onBoundaryInvalid()
    }
  }, [detail.error, onBoundaryInvalid, templates.error])
  useEffect(() => {
    if (selectedTemplateId || !templates.data?.items[0]) return
    onSelectedTemplate(templates.data.items[0].template_id)
  }, [onSelectedTemplate, selectedTemplateId, templates.data?.items])

  const refreshTemplates = async (templateId?: string) => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: qualityQueryKey(boundary, 'common-rule-templates'),
      }),
      queryClient.invalidateQueries({
        queryKey: qualityQueryKey(
          boundary,
          'common-rule-template-detail',
          templateId ?? selectedTemplateId,
        ),
      }),
    ])
  }

  return <section className="quality-template-workspace">
    <header className="quality-section-header">
      <div>
        <span className="eyebrow">Create once · apply many</span>
        <h2>공통 룰셋 관리</h2>
        <p>자주 쓰는 품질 검사를 공통 템플릿으로 만들고 여러 스키마·테이블에 한 번에 적용합니다.</p>
      </div>
      {axes.get('rule_authoring')?.state !== 'DENIED' && (
        <button className="button" type="button" onClick={() => setCreateOpen(true)}>
          <Plus size={14} aria-hidden="true" /> 공통 룰 만들기
        </button>
      )}
    </header>
    <RuleMappingReadiness axis={axes.get('rule_authoring')} />
    {notice && <p className="notice notice-success" role="status">{notice}</p>}
    {templates.error && <ErrorNotice error={templates.error} />}
    <div className="quality-template-grid">
      <aside className="quality-template-list panel" aria-label="공통 룰셋 목록">
        <header><strong>공통 룰</strong><span>{countText(templates.data?.items.length)}개</span></header>
        {templates.isPending && <p className="quality-loading">공통 룰을 불러오는 중입니다.</p>}
        {!templates.isPending && templates.data?.items.length === 0 && (
          <div className="quality-template-empty">
            <strong>아직 공통 룰이 없습니다</strong>
            <span>반복해서 사용할 검사를 먼저 만들어 보세요.</span>
          </div>
        )}
        {templates.data?.items.map((template) => <button
          key={template.template_id}
          type="button"
          className={`quality-template-item${template.template_id === selectedTemplateId ? ' selected' : ''}`}
          aria-pressed={template.template_id === selectedTemplateId}
          onClick={() => onSelectedTemplate(template.template_id)}
        >
          <div><strong>{template.name}</strong><small>{template.description || '설명 없음'}</small></div>
          <span>{countText(template.rules.length)} rules · {countText(template.mapping_count)} tables</span>
        </button>)}
      </aside>
      <section className="quality-template-detail panel">
        {!selectedTemplateId && (
          <div className="quality-asset-placeholder">
            <strong>공통 룰을 선택하세요</strong>
            <span>룰 정의와 적용 중인 테이블을 비교할 수 있습니다.</span>
          </div>
        )}
        {detail.isPending && selectedTemplateId && (
          <p className="quality-loading">공통 룰 상세를 불러오는 중입니다.</p>
        )}
        {detail.error && <ErrorNotice error={detail.error} />}
        {detail.data && <>
          <header className="quality-template-detail-header">
            <div>
              <span className="eyebrow">Reusable quality template</span>
              <h2>{detail.data.template.name}</h2>
              <p>{detail.data.template.description || '별도 설명이 없습니다.'}</p>
            </div>
            <button
              className="button"
              type="button"
              disabled={axes.get('rule_authoring')?.state !== 'AVAILABLE'}
              title={axes.get('rule_authoring')?.state === 'AVAILABLE'
                ? '여러 테이블에 공통 룰 적용'
                : '배포 소유 필드 디렉터리와 품질 보존 정책이 준비되어야 합니다.'}
              onClick={() => setMappingOpen(true)}
            >
              {axes.get('rule_authoring')?.state === 'AVAILABLE'
                ? '여러 테이블에 적용'
                : '적용 준비 필요'}
            </button>
          </header>
          <TemplateRuleList template={detail.data.template} />
          <section className="quality-template-mappings" aria-labelledby="template-mapping-title">
            <header>
              <div>
                <span className="eyebrow">Applied assets comparison</span>
                <h3 id="template-mapping-title">적용 중인 테이블</h3>
              </div>
              <strong>{countText(detail.data.mappings.length)}개</strong>
            </header>
            {detail.data.mappings.length === 0
              ? <p className="quality-empty">이 공통 룰을 적용한 테이블이 아직 없습니다.</p>
              : <div className="quality-compact-table-scroll">
                <table className="quality-compact-table">
                  <thead><tr><th>테이블</th><th>Platform</th><th>Database</th><th>Schema</th><th>적용일</th></tr></thead>
                  <tbody>{detail.data.mappings.map((mapping) => <tr key={mapping.asset_id}>
                    <td><strong>{mapping.asset_name}</strong><small>{mapping.rule_set_name}</small></td>
                    <td>{optionalText(mapping.platform)}</td>
                    <td>{optionalText(mapping.database_name)}</td>
                    <td>{optionalText(mapping.schema_name)}</td>
                    <td>{dateTimeText(mapping.mapped_at)}</td>
                  </tr>)}</tbody>
                </table>
              </div>}
          </section>
        </>}
      </section>
    </div>
    <CreateTemplateDialog
      open={createOpen}
      api={api}
      onBoundaryInvalid={onBoundaryInvalid}
      onClose={() => setCreateOpen(false)}
      onCreated={async (templateId, replayed) => {
        setCreateOpen(false)
        await refreshTemplates(templateId)
        onSelectedTemplate(templateId)
        setNotice(`공통 룰을 만들었습니다.${replayed ? ' 동일 요청 재생 결과입니다.' : ''}`)
      }}
    />
    {detail.data && <MappingDialog
      open={mappingOpen}
      api={api}
      boundary={boundary}
      template={detail.data.template}
      mappedAssetIds={new Set(detail.data.mappings.map((mapping) => mapping.asset_id))}
      onBoundaryInvalid={onBoundaryInvalid}
      onClose={() => setMappingOpen(false)}
      onMapped={async (count, replayed) => {
        setMappingOpen(false)
        await Promise.all([
          refreshTemplates(detail.data.template.template_id),
          queryClient.invalidateQueries({
            queryKey: qualityQueryKey(boundary, 'assets'),
          }),
          queryClient.invalidateQueries({
            queryKey: qualityQueryKey(boundary, 'asset-workspace'),
          }),
        ])
        setNotice(`${countText(count)}개 테이블에 적용했습니다.${replayed ? ' 동일 요청 재생 결과입니다.' : ''}`)
      }}
    />}
  </section>
}

function RuleMappingReadiness({
  axis,
}: {
  axis: QualityCapabilityAxis | undefined
}) {
  if (axis?.state === 'AVAILABLE') return null
  const denied = axis?.state === 'DENIED'
  return <section className={`quality-mapping-readiness${denied ? ' denied' : ''}`} role="status">
    <div>
      <strong>{denied ? '공통 룰 적용 권한이 없습니다' : '공통 룰은 만들 수 있고, 일괄 적용은 준비 중입니다'}</strong>
      <span>{denied
        ? 'Workspace의 품질 룰 제안 권한을 확인해 주세요.'
        : 'Admin 권한과 별개로 서버가 검증한 V2 필드 identity 디렉터리와 V3/V4 품질 보존 정책이 모두 준비되어야 여러 테이블에 안전하게 적용할 수 있습니다.'}</span>
    </div>
    {axis?.reason_code && <code>{axis.reason_code}</code>}
  </section>
}

function TemplateRuleList({ template }: { template: QualityCommonRuleTemplate }) {
  return <section className="quality-template-rules" aria-labelledby="template-rules-title">
    <header><h3 id="template-rules-title">룰 정의</h3><span>{countText(template.rules.length)}개</span></header>
    <ul>{template.rules.map((rule, index) => <li key={`${rule.field_identifier}-${rule.kind}`}>
      <span>{index + 1}</span>
      <div><strong>{rule.field_identifier}</strong><small>{rule.kind === 'NOT_NULL' ? '빈 값 허용 안 함' : '허용 범위 검사'}</small></div>
      <QualityStatus value={rule.severity} />
      {rule.kind === 'RANGE' && (
        <code>{String(rule.parameters.min_value)} ≤ value ≤ {String(rule.parameters.max_value)}</code>
      )}
    </li>)}</ul>
  </section>
}

function CreateTemplateDialog({
  open,
  api,
  onClose,
  onCreated,
  onBoundaryInvalid,
}: {
  open: boolean
  api: QualityApi
  onClose: () => void
  onCreated: (templateId: string, replayed: boolean) => Promise<void>
  onBoundaryInvalid: () => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [rules, setRules] = useState<TemplateRuleDraft[]>([emptyRule()])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()

  useEffect(() => {
    if (!open) return
    setName('')
    setDescription('')
    setRules([emptyRule()])
    setError(undefined)
  }, [open])

  const payload = templatePayload(name, description, rules)
  const submit = async () => {
    if (!payload) return
    setBusy(true)
    setError(undefined)
    try {
      const value = await api.createCommonRuleTemplate(
        payload,
        newIdempotencyKey('quality-common-template'),
      )
      await onCreated(value.template_id, value.replayed)
    } catch (next) {
      if (isAuthorizationBoundaryError(next)) onBoundaryInvalid()
      setError(next)
    } finally {
      setBusy(false)
    }
  }

  return <Dialog
    open={open}
    title="공통 룰 만들기"
    description="테이블과 독립적인 재사용 템플릿을 먼저 정의합니다. 적용할 때 호환되는 필드가 있는지 다시 확인합니다."
    size="large"
    onRequestClose={() => { if (!busy) onClose() }}
    footer={<>
      <button className="button button-secondary" type="button" disabled={busy} onClick={onClose}>취소</button>
      <button className="button" type="button" disabled={busy || !payload} onClick={() => void submit()}>
        {busy ? '저장 중…' : '공통 룰 저장'}
      </button>
    </>}
  >
    {Boolean(error) && <ErrorNotice error={error} />}
    <div className="quality-template-form">
      <label>이름<input value={name} maxLength={100} onChange={(event) => setName(event.target.value)} placeholder="예: 고객 이메일 필수값" /></label>
      <label>설명<textarea value={description} maxLength={1000} onChange={(event) => setDescription(event.target.value)} placeholder="언제 사용하는 룰인지 간단히 설명" /></label>
      <div className="quality-template-regex-note">
        이메일 정규식 등 REGEX 룰은 안전 실행 계약이 준비될 때까지 선택할 수 없습니다. 현재는 Not Null과 범위 검사를 지원합니다.
      </div>
      {rules.map((rule, index) => <fieldset key={index} className="quality-template-rule-editor">
        <legend>Rule {index + 1}</legend>
        <label>대상 필드<input value={rule.field_identifier} maxLength={255} onChange={(event) => updateRule(setRules, rules, index, { ...rule, field_identifier: event.target.value })} placeholder="예: email 또는 amount" /></label>
        <label>검사<select value={rule.kind} onChange={(event) => updateRule(setRules, rules, index, { ...rule, kind: event.target.value as TemplateRuleDraft['kind'] })}><option value="NOT_NULL">Not Null</option><option value="RANGE">특정 범위</option></select></label>
        <label>실패 수준<select value={rule.severity} onChange={(event) => updateRule(setRules, rules, index, { ...rule, severity: event.target.value as QualityRuleSeverity })}><option value="BLOCKING">Fail</option><option value="ADVISORY">Warn</option></select></label>
        {rule.kind === 'RANGE' && <>
          <label>값 형식<select value={rule.value_type} onChange={(event) => updateRule(setRules, rules, index, { ...rule, value_type: event.target.value as TemplateRuleDraft['value_type'] })}><option value="DECIMAL">숫자</option><option value="DATE">날짜</option><option value="TIMESTAMP">일시</option></select></label>
          <label>최소값<input value={rule.min_value} maxLength={100} onChange={(event) => updateRule(setRules, rules, index, { ...rule, min_value: event.target.value })} /></label>
          <label>최대값<input value={rule.max_value} maxLength={100} onChange={(event) => updateRule(setRules, rules, index, { ...rule, max_value: event.target.value })} /></label>
        </>}
        <button className="button button-secondary" type="button" disabled={rules.length === 1} onClick={() => setRules(rules.filter((_, candidate) => candidate !== index))}>Rule 제거</button>
      </fieldset>)}
      <button className="button button-secondary" type="button" disabled={rules.length >= 100} onClick={() => setRules([...rules, emptyRule()])}><Plus size={13} /> Rule 추가</button>
    </div>
  </Dialog>
}

function MappingDialog({
  open,
  api,
  boundary,
  template,
  mappedAssetIds,
  onClose,
  onMapped,
  onBoundaryInvalid,
}: {
  open: boolean
  api: QualityApi
  boundary: QualitySecurityBoundary
  template: QualityCommonRuleTemplate
  mappedAssetIds: ReadonlySet<string>
  onClose: () => void
  onMapped: (count: number, replayed: boolean) => Promise<void>
  onBoundaryInvalid: () => void
}) {
  const [draftQuery, setDraftQuery] = useState('')
  const [draftSchema, setDraftSchema] = useState('')
  const [query, setQuery] = useState('')
  const [schema, setSchema] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const assets = useQuery({
    queryKey: qualityQueryKey(boundary, 'assets', 'template-mapping', query, schema),
    queryFn: ({ signal }) => api.assets(undefined, signal, {
      query,
      schema,
      limit: 100,
    }),
    enabled: open,
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const details = useQueries({
    queries: selected.map((assetId) => ({
      queryKey: qualityQueryKey(boundary, 'asset-detail', assetId),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.asset(
        assetId,
        boundary.cacheScope,
        signal,
      ),
      enabled: open,
      staleTime: 0,
      gcTime: 30_000,
      retry: false,
    })),
  })
  const compatibility = useMemo(
    () => new Map(selected.map((assetId, index) => [
      assetId,
      templateCompatible(template, details[index]?.data),
    ])),
    [details, selected, template],
  )
  const selectedReady = selected.length > 0
    && selected.length <= 25
    && details.every((detail) => !detail.isPending && !detail.error)
    && selected.every((assetId) => compatibility.get(assetId) === true)

  useEffect(() => {
    if (!open) return
    setDraftQuery('')
    setDraftSchema('')
    setQuery('')
    setSchema('')
    setSelected([])
    setError(undefined)
  }, [open, template.template_id])
  const authorizationError = details.some((detail) => isAuthorizationBoundaryError(detail.error))
  useEffect(() => {
    if (isAuthorizationBoundaryError(assets.error) || authorizationError) {
      onBoundaryInvalid()
    }
  }, [assets.error, authorizationError, onBoundaryInvalid])

  const search = (event: FormEvent) => {
    event.preventDefault()
    setQuery(draftQuery.trim())
    setSchema(draftSchema.trim())
  }
  const toggle = (assetId: string, checked: boolean) => {
    setSelected((current) => {
      if (!checked) return current.filter((value) => value !== assetId)
      if (current.includes(assetId) || current.length >= 25) return current
      return [...current, assetId]
    })
  }
  const map = async () => {
    if (!selectedReady) return
    setBusy(true)
    setError(undefined)
    try {
      const value = await api.mapCommonRuleTemplate(
        template.template_id,
        selected,
        newIdempotencyKey('quality-common-mapping'),
      )
      await onMapped(value.items.length, value.replayed)
    } catch (next) {
      if (isAuthorizationBoundaryError(next)) onBoundaryInvalid()
      setError(next)
    } finally {
      setBusy(false)
    }
  }

  return <Dialog
    open={open}
    title={`${template.name} · 여러 테이블에 적용`}
    description="스키마와 테이블을 검색하고 최대 25개를 선택해 한 번에 적용합니다."
    size="large"
    onRequestClose={() => { if (!busy) onClose() }}
    footer={<>
      <span className="quality-mapping-selection">{countText(selected.length)}개 선택</span>
      <button className="button button-secondary" type="button" disabled={busy} onClick={onClose}>취소</button>
      <button className="button" type="button" disabled={busy || !selectedReady} onClick={() => void map()}>
        {busy ? '적용 중…' : `${countText(selected.length)}개 테이블에 적용`}
      </button>
    </>}
  >
    {Boolean(error) && <ErrorNotice error={error} />}
    <form className="quality-mapping-search" onSubmit={search}>
      <Search size={15} aria-hidden="true" />
      <label>테이블 검색<input value={draftQuery} maxLength={200} onChange={(event) => setDraftQuery(event.target.value)} placeholder="테이블·데이터베이스·플랫폼" /></label>
      <label>스키마<input value={draftSchema} maxLength={255} onChange={(event) => setDraftSchema(event.target.value)} placeholder="정확한 스키마명" /></label>
      <button className="button" type="submit">검색</button>
    </form>
    {assets.error && <ErrorNotice error={assets.error} />}
    <div className="quality-mapping-table-scroll">
      <table className="quality-compact-table">
        <thead><tr><th>선택</th><th>테이블</th><th>Platform</th><th>Database</th><th>Schema</th><th>호환성</th></tr></thead>
        <tbody>{assets.data?.items.map((asset) => {
          const alreadyMapped = mappedAssetIds.has(asset.asset_id)
          const checked = selected.includes(asset.asset_id)
          return <MappingAssetRow
            key={asset.asset_id}
            asset={asset}
            checked={checked}
            alreadyMapped={alreadyMapped}
            compatible={compatibility.get(asset.asset_id)}
            onToggle={(value) => toggle(asset.asset_id, value)}
          />
        })}</tbody>
      </table>
      {assets.isPending && <p className="quality-loading">적용 대상을 검색하는 중입니다.</p>}
      {!assets.isPending && assets.data?.items.length === 0 && <p className="quality-empty">검색 조건에 맞는 테이블이 없습니다.</p>}
    </div>
    {selected.length > 0 && !selectedReady && (
      <p className="callout" role="status">선택한 테이블의 필드와 룰 호환성을 확인 중이거나, 동일한 필드·타입을 지원하지 않는 테이블이 포함되어 있습니다.</p>
    )}
  </Dialog>
}

function MappingAssetRow({
  asset,
  checked,
  alreadyMapped,
  compatible,
  onToggle,
}: {
  asset: QualityAsset
  checked: boolean
  alreadyMapped: boolean
  compatible?: boolean
  onToggle: (checked: boolean) => void
}) {
  return <tr>
    <td><input type="checkbox" aria-label={`${asset.name} 선택`} checked={checked} disabled={alreadyMapped} onChange={(event) => onToggle(event.target.checked)} /></td>
    <td><strong>{asset.name}</strong></td>
    <td>{optionalText(asset.platform)}</td>
    <td>{optionalText(asset.database_name)}</td>
    <td>{optionalText(asset.schema_name)}</td>
    <td>{alreadyMapped
      ? <span className="quality-compatibility mapped">적용됨</span>
      : !checked
        ? <span className="quality-compatibility">선택 후 확인</span>
        : compatible === undefined
          ? <span className="quality-compatibility checking">확인 중</span>
          : compatible
            ? <span className="quality-compatibility compatible">적용 가능</span>
            : <span className="quality-compatibility incompatible">필드 불일치</span>}
    </td>
  </tr>
}

function templateCompatible(
  template: QualityCommonRuleTemplate,
  detail: QualityAssetDetailResponse | undefined,
): boolean | undefined {
  if (!detail) return undefined
  if (detail.authoring.state !== 'READY') return false
  return template.rules.every((rule) => detail.authoring.fields.some((field) => (
    field.field_identifier === rule.field_identifier
    && field.supported_rule_kinds.includes(rule.kind)
    && (
      rule.kind !== 'RANGE'
      || field.logical_type === rule.parameters.value_type
    )
  )))
}

function templatePayload(
  name: string,
  description: string,
  drafts: TemplateRuleDraft[],
): QualityCommonRuleTemplateCreateRequest | null {
  const normalizedName = name.trim()
  if (
    !normalizedName
    || normalizedName.length > 100
    || description.length > 1000
    || drafts.length < 1
    || drafts.length > 100
  ) return null
  const identities = new Set<string>()
  const rules: QualityRuleDraftRequest[] = []
  for (const draft of drafts) {
    const field = draft.field_identifier.trim()
    const identity = `${field}\u0000${draft.kind}`
    if (!field || field.length > 255 || identities.has(identity)) return null
    identities.add(identity)
    if (draft.kind === 'NOT_NULL') {
      rules.push({
        field_identifier: field,
        kind: draft.kind,
        severity: draft.severity,
        parameters: {},
      })
      continue
    }
    if (!draft.min_value.trim() || !draft.max_value.trim()) return null
    rules.push({
      field_identifier: field,
      kind: draft.kind,
      severity: draft.severity,
      parameters: {
        value_type: draft.value_type,
        min_value: draft.min_value.trim(),
        max_value: draft.max_value.trim(),
        inclusive_min: true,
        inclusive_max: true,
      },
    })
  }
  return {
    name: normalizedName,
    description: description.trim() || null,
    rules,
  }
}

function updateRule(
  setRules: (rules: TemplateRuleDraft[]) => void,
  rules: TemplateRuleDraft[],
  index: number,
  value: TemplateRuleDraft,
) {
  setRules(rules.map((rule, candidate) => candidate === index ? value : rule))
}
