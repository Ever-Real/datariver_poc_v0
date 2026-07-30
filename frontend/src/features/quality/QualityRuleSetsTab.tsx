import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import type {
  QualityAsset,
  QualityAssetDetailResponse,
  QualityAuthoringField,
  QualityAuthoringLogicalType,
  QualityAuthoringRuleKind,
  QualityCapabilityAxis,
  QualityRuleBatchProposalRequest,
  QualityRuleDefinition,
  QualityRuleDefinitionCapability,
  QualityRuleDraftRequest,
  QualityRuleSetSummary,
  QualityRuleSetVersionSummary,
  QualityRuleSeverity,
} from '../../api/types'
import { newIdempotencyKey } from '../../api/client'
import { ErrorNotice } from '../../components/ErrorNotice'
import { CursorPagination } from '../../components/common/CursorPagination'
import { DenseDataTable } from '../../components/common/DenseDataTable'
import { Dialog } from '../../components/common/Dialog'
import { qualityQueryKey } from './qualityApi'
import type { QualityApi, QualitySecurityBoundary } from './qualityApi'
import {
  countText,
  dateTimeText,
  optionalText,
  QualityAxisLock,
  QualityStatus,
} from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'
import { useQualityCursorPage } from './useQualityCursorPage'

interface RuleDraftForm {
  field_identifier: string
  kind: QualityAuthoringRuleKind
  severity: QualityRuleSeverity
  min_value: string
  max_value: string
  inclusive_min: boolean
  inclusive_max: boolean
}

const RANGE_LOGICAL_TYPES = new Set<QualityAuthoringLogicalType>([
  'DECIMAL',
  'DATE',
  'TIMESTAMP',
])

export function QualityRuleSetsTab({
  api,
  boundary,
  axes,
  selectedRuleSetId,
  onSelectedRuleSet,
  onBoundaryInvalid,
}: {
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: Map<string, QualityCapabilityAxis>
  selectedRuleSetId?: string
  onSelectedRuleSet: (id?: string) => void
  onBoundaryInvalid: () => void
}) {
  const queryClient = useQueryClient()
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
  const [editorOpen, setEditorOpen] = useState(false)
  const [namePrefix, setNamePrefix] = useState('')
  const [drafts, setDrafts] = useState<RuleDraftForm[]>([])
  const [proposalBusy, setProposalBusy] = useState(false)
  const [proposalError, setProposalError] = useState<unknown>()
  const [proposalNotice, setProposalNotice] = useState<string>()
  const [commandBusy, setCommandBusy] = useState<string>()
  const [commandError, setCommandError] = useState<unknown>()
  const [commandNotice, setCommandNotice] = useState<string>()
  const [reviewVersionId, setReviewVersionId] = useState<string>()
  const [reviewDecision, setReviewDecision] = useState<'APPROVE' | 'REJECT'>('APPROVE')
  const [reviewReason, setReviewReason] = useState('')
  const rules = useQualityCursorPage({
    boundary,
    resource: 'rule-sets',
    load: (cursor, signal) => api.ruleSets(cursor, signal),
    onBoundaryInvalid,
  })
  const assets = useQualityCursorPage({
    boundary,
    resource: 'assets',
    load: (cursor, signal) => api.assets(cursor, signal),
    onBoundaryInvalid,
  })
  const definitions = useQuery({
    queryKey: qualityQueryKey(boundary, 'rule-definitions'),
    queryFn: ({ signal }) => api.ruleDefinitions(signal),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const detail = useQuery({
    queryKey: qualityQueryKey(boundary, 'rule-set-detail', selectedRuleSetId),
    queryFn: ({ signal }) => api.ruleSet(
      selectedRuleSetId ?? '',
      boundary.cacheScope,
      signal,
    ),
    enabled: Boolean(selectedRuleSetId),
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const authoringAvailable = axes.get('rule_authoring')?.state === 'AVAILABLE'
  const authoringDetails = useQueries({
    queries: selectedAssetIds.map((assetId) => ({
      queryKey: qualityQueryKey(boundary, 'asset-detail', assetId),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.asset(
        assetId,
        boundary.cacheScope,
        signal,
      ),
      enabled: authoringAvailable,
      staleTime: 0,
      gcTime: 30_000,
      retry: false,
    })),
  })

  useEffect(() => {
    if (isAuthorizationBoundaryError(definitions.error)) onBoundaryInvalid()
  }, [definitions.error, onBoundaryInvalid])
  useEffect(() => {
    if (!isAuthorizationBoundaryError(detail.error)) return
    onSelectedRuleSet(undefined)
    onBoundaryInvalid()
  }, [detail.error, onBoundaryInvalid, onSelectedRuleSet])
  const authoringAuthorizationError = authoringDetails.some((query) => (
    isAuthorizationBoundaryError(query.error)
  ))
  useEffect(() => {
    if (authoringAuthorizationError) onBoundaryInvalid()
  }, [authoringAuthorizationError, onBoundaryInvalid])
  useEffect(() => {
    setSelectedAssetIds([])
    setEditorOpen(false)
  }, [
    assets.pageIndex,
    boundary.workspaceId,
    boundary.subjectId,
    boundary.securityEpoch,
    boundary.authorizationRevision,
    boundary.cacheScope,
  ])

  const selectedSummary = detail.data?.rule_set
    ?? rules.data?.items.find((item) => item.rule_set_id === selectedRuleSetId)
  const catalogKinds = useMemo(() => new Set(
    (definitions.data?.items ?? [])
      .filter((definition) => definition.available)
      .map((definition) => definition.kind),
  ), [definitions.data])
  const commonFields = useMemo(() => commonAuthoringFields(
    authoringDetails.map((query) => query.data),
    selectedAssetIds.length,
    catalogKinds,
  ), [authoringDetails, catalogKinds, selectedAssetIds.length])
  const authoringPending = selectedAssetIds.length > 0
    && authoringDetails.some((query) => query.isPending)
  const authoringError = authoringDetails.find((query) => query.error)?.error
  const authoringReady = selectedAssetIds.length > 0
    && authoringDetails.length === selectedAssetIds.length
    && authoringDetails.every((query) => query.data?.authoring.state === 'READY')
    && commonFields.length > 0
  const visibleAssetIds = (assets.data?.items ?? []).map((asset) => asset.asset_id)
  const allVisibleSelected = visibleAssetIds.length > 0
    && visibleAssetIds.every((assetId) => selectedAssetIds.includes(assetId))

  const toggleAsset = (assetId: string, checked: boolean) => {
    setProposalNotice(undefined)
    setEditorOpen(false)
    setSelectedAssetIds((current) => {
      if (!checked) return current.filter((candidate) => candidate !== assetId)
      if (current.includes(assetId) || current.length >= 25) return current
      return [...current, assetId]
    })
  }
  const openEditor = () => {
    const first = commonFields[0]
    if (!first) return
    const draft = defaultDraft(first)
    if (!draft) return
    setNamePrefix('')
    setDrafts([draft])
    setProposalError(undefined)
    setEditorOpen(true)
  }
  const submitProposal = async () => {
    const payload = proposalPayload(namePrefix, selectedAssetIds, drafts, commonFields)
    if (!payload) {
      setProposalError(new Error('이름, 필드 및 RANGE 경계값을 확인하세요.'))
      return
    }
    setProposalBusy(true)
    setProposalError(undefined)
    try {
      const result = await api.proposeRuleSets(
        payload,
        newIdempotencyKey('quality-rule-proposal'),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'rule-sets') }),
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'assets') }),
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'asset-detail') }),
      ])
      setProposalNotice(
        `${countText(result.items.length)}개 자산의 Rule Set 제안을 저장했습니다.${result.replayed ? ' 동일 요청 재생 결과입니다.' : ''}`,
      )
      setSelectedAssetIds([])
      setEditorOpen(false)
    } catch (error) {
      if (isAuthorizationBoundaryError(error)) onBoundaryInvalid()
      setProposalError(error)
    } finally {
      setProposalBusy(false)
    }
  }
  const activateVersion = async (version: QualityRuleSetVersionSummary) => {
    if (!detail.data || axes.get('activation')?.state !== 'AVAILABLE') return
    setCommandBusy(version.version_id)
    setCommandError(undefined)
    setCommandNotice(undefined)
    try {
      await api.activateRuleVersion(
        detail.data.rule_set.rule_set_id,
        version.version_id,
        version.version,
        newIdempotencyKey('quality-rule-activation'),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'rule-sets') }),
        queryClient.invalidateQueries({
          queryKey: qualityQueryKey(
            boundary,
            'rule-set-detail',
            detail.data.rule_set.rule_set_id,
          ),
        }),
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'overview') }),
      ])
      setCommandNotice(`v${version.version_number} 활성화를 완료했습니다.`)
    } catch (error) {
      if (isAuthorizationBoundaryError(error)) onBoundaryInvalid()
      setCommandError(error)
    } finally {
      setCommandBusy(undefined)
    }
  }
  const reviewVersion = async (version: QualityRuleSetVersionSummary) => {
    const reason = reviewReason.trim()
    if (
      !detail.data
      || axes.get('review')?.state !== 'AVAILABLE'
      || version.author_id === boundary.subjectId
      || !reason
      || reason.length > 4_000
    ) return
    setCommandBusy(version.version_id)
    setCommandError(undefined)
    setCommandNotice(undefined)
    try {
      await api.reviewRuleVersion(
        detail.data.rule_set.rule_set_id,
        version.version_id,
        version.version,
        { decision: reviewDecision, reason },
        newIdempotencyKey('quality-rule-review'),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'rule-sets') }),
        queryClient.invalidateQueries({
          queryKey: qualityQueryKey(
            boundary,
            'rule-set-detail',
            detail.data.rule_set.rule_set_id,
          ),
        }),
      ])
      setCommandNotice(
        `v${version.version_number} 검토를 ${reviewDecision === 'APPROVE' ? '승인' : '반려'}했습니다.`,
      )
      setReviewVersionId(undefined)
      setReviewReason('')
    } catch (error) {
      if (isAuthorizationBoundaryError(error)) onBoundaryInvalid()
      setCommandError(error)
    } finally {
      setCommandBusy(undefined)
    }
  }
  const requestManualRun = async () => {
    if (!detail.data || axes.get('manual_execution')?.state !== 'AVAILABLE') return
    setCommandBusy('manual-run')
    setCommandError(undefined)
    setCommandNotice(undefined)
    try {
      const result = await api.requestManualRun(
        detail.data.rule_set.rule_set_id,
        newIdempotencyKey('quality-manual-run'),
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'runs') }),
        queryClient.invalidateQueries({ queryKey: qualityQueryKey(boundary, 'overview') }),
      ])
      setCommandNotice(
        `수동 실행 ${result.run_id}을(를) 요청했습니다.${result.replayed ? ' 동일 요청 재생 결과입니다.' : ''}`,
      )
    } catch (error) {
      if (isAuthorizationBoundaryError(error)) onBoundaryInvalid()
      setCommandError(error)
    } finally {
      setCommandBusy(undefined)
    }
  }

  const ruleColumns = useMemo<ColumnDef<QualityRuleSetSummary>[]>(() => [
    { accessorKey: 'name', header: 'Rule Set', size: 210, enableSorting: false },
    { accessorKey: 'asset_name', header: '대상 자산', size: 180, enableSorting: false },
    { accessorKey: 'state', header: '상태', size: 100, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.state} /> },
    { accessorKey: 'active_version_number', header: '활성 버전', size: 90, enableSorting: false, cell: ({ row }) => row.original.active_version_number ? `v${row.original.active_version_number}` : '—' },
    { accessorKey: 'active_version_state', header: '버전 상태', size: 120, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.active_version_state} /> },
    { accessorKey: 'rule_count', header: 'Rule 수', size: 80, enableSorting: false, cell: ({ row }) => countText(row.original.rule_count) },
    { accessorKey: 'updated_at', header: '최근 변경', size: 170, enableSorting: false, cell: ({ row }) => dateTimeText(row.original.updated_at) },
  ], [])
  const assetColumns = useMemo<ColumnDef<QualityAsset>[]>(() => [
    {
      id: 'selection',
      header: '선택',
      size: 64,
      enableSorting: false,
      cell: ({ row }) => <input
        type="checkbox"
        aria-label={`${row.original.name} 선택`}
        checked={selectedAssetIds.includes(row.original.asset_id)}
        disabled={!authoringAvailable}
        onChange={(event) => toggleAsset(row.original.asset_id, event.target.checked)}
      />,
    },
    { accessorKey: 'name', header: '자산', size: 190, enableSorting: false },
    { accessorKey: 'platform', header: 'Platform', size: 100, enableSorting: false, cell: ({ row }) => optionalText(row.original.platform) },
    { accessorKey: 'database_name', header: 'Database', size: 120, enableSorting: false, cell: ({ row }) => optionalText(row.original.database_name) },
    { accessorKey: 'schema_name', header: 'Schema', size: 120, enableSorting: false, cell: ({ row }) => optionalText(row.original.schema_name) },
    { accessorKey: 'classification', header: '등급', size: 100, enableSorting: false },
    { accessorKey: 'profile_readiness', header: 'Profile', size: 120, enableSorting: false, cell: ({ row }) => <QualityStatus value={row.original.profile_readiness} /> },
    { accessorKey: 'active_rule_set_count', header: '활성 Rule Set', size: 110, enableSorting: false, cell: ({ row }) => countText(row.original.active_rule_set_count) },
  ], [authoringAvailable, selectedAssetIds])

  return <section className="quality-tab-content">
    <header className="quality-section-header">
      <div><span className="eyebrow">Immutable versions · maker-checker</span><h2>Rule Set 관리</h2><p>서버 authoring 계약으로 검증된 필드를 선택해 여러 자산에 하나의 원자적 제안을 생성합니다.</p></div>
    </header>
    <div className="quality-capability-locks" aria-label="Rule 관리 capability">
      <QualityAxisLock axis={axes.get('rule_authoring')} title="Rule 작성 잠김" />
      <QualityAxisLock axis={axes.get('activation')} title="독립 활성화 잠김" />
      <QualityAxisLock axis={axes.get('scheduling')} title="예약 실행 잠김" />
    </div>
    {definitions.error && <ErrorNotice error={definitions.error} />}
    <section className="panel quality-list-panel" aria-labelledby="quality-rule-set-list-title">
      <header><div><span className="eyebrow">Server cursor page</span><h3 id="quality-rule-set-list-title">Rule Sets</h3></div></header>
      {rules.error && <ErrorNotice error={rules.error} />}
      <DenseDataTable
        caption="품질 Rule Set 목록"
        columns={ruleColumns}
        data={rules.data?.items ?? []}
        getRowId={(row) => row.rule_set_id}
        loading={rules.isPending}
        emptyMessage="현재 권한 범위에서 조회 가능한 Rule Set이 없습니다."
        selectedRowId={selectedRuleSetId}
        onRowActivate={(row) => {
          setCommandError(undefined)
          setCommandNotice(undefined)
          onSelectedRuleSet(row.rule_set_id)
        }}
      />
      <CursorPagination {...rules.pagination} label="품질 Rule Set 페이지 탐색" />
    </section>
    <section className="panel quality-list-panel" aria-labelledby="quality-asset-list-title">
      <header>
        <div><span className="eyebrow">Authoring directory · permission scoped</span><h3 id="quality-asset-list-title">대상 자산</h3></div>
        {authoringAvailable && <div className="action-row">
          <button
            type="button"
            className="button button-secondary"
            disabled={visibleAssetIds.length === 0}
            onClick={() => {
              setEditorOpen(false)
              setSelectedAssetIds(allVisibleSelected ? [] : visibleAssetIds.slice(0, 25))
            }}
          >
            {allVisibleSelected ? '현재 페이지 선택 해제' : '현재 페이지 전체 선택'}
          </button>
          <button
            type="button"
            className="button"
            disabled={!authoringReady || authoringPending || Boolean(authoringError)}
            onClick={openEditor}
          >
            {countText(selectedAssetIds.length)}개 자산에 Rule 제안
          </button>
        </div>}
      </header>
      {axes.get('profile_readiness')?.state !== 'AVAILABLE' && <QualityAxisLock axis={axes.get('profile_readiness')} title="Profile 상세 readiness 잠김" />}
      {assets.error && <ErrorNotice error={assets.error} />}
      {authoringError && <ErrorNotice error={authoringError} />}
      {authoringPending && <p role="status">선택 자산의 authoring 계약을 확인하는 중입니다.</p>}
      {selectedAssetIds.length > 0 && !authoringPending && !authoringError && !authoringReady && (
        <p className="callout" role="status">선택 자산 모두에 공통으로 적용 가능한 서버 필드와 Rule 종류가 없습니다.</p>
      )}
      {proposalNotice && <p className="notice notice-success" role="status">{proposalNotice}</p>}
      <DenseDataTable
        caption="품질 대상 자산 목록"
        columns={assetColumns}
        data={assets.data?.items ?? []}
        getRowId={(row) => row.asset_id}
        loading={assets.isPending}
        emptyMessage="현재 권한 범위에서 조회 가능한 품질 대상 자산이 없습니다."
      />
      <CursorPagination {...assets.pagination} label="품질 대상 자산 페이지 탐색" />
    </section>
    <section className="panel quality-rule-contract" aria-labelledby="quality-rule-contract-title">
      <header><div><span className="eyebrow">Typed allowlist</span><h3 id="quality-rule-contract-title">지원 Rule 계약</h3></div></header>
      {definitions.isPending ? <p role="status">Rule 계약을 확인하는 중입니다.</p> : (
        definitions.data?.items.length
          ? <RuleCatalog definitions={definitions.data.items} />
          : <p className="quality-empty" role="status">서버가 제공한 typed Rule 계약이 없습니다.</p>
      )}
    </section>
    <RuleProposalDialog
      open={editorOpen}
      selectedCount={selectedAssetIds.length}
      commonFields={commonFields}
      namePrefix={namePrefix}
      drafts={drafts}
      busy={proposalBusy}
      error={proposalError}
      onNamePrefix={setNamePrefix}
      onDrafts={setDrafts}
      onSubmit={() => void submitProposal()}
      onClose={() => {
        if (!proposalBusy) setEditorOpen(false)
      }}
    />
    <Dialog
      open={Boolean(selectedRuleSetId)}
      title={selectedSummary ? `${selectedSummary.name} · Rule Set` : 'Rule Set'}
      description="선택 시 권한 범위 안의 immutable version과 typed Rule을 지연 조회합니다."
      onRequestClose={() => {
        if (!commandBusy) onSelectedRuleSet(undefined)
      }}
    >
      {detail.isPending && <p className="quality-loading" role="status">Rule Set 상세를 확인하는 중입니다.</p>}
      {detail.error && <ErrorNotice error={detail.error} />}
      {Boolean(commandError) && <ErrorNotice error={commandError} />}
      {commandNotice && <p className="notice notice-success" role="status">{commandNotice}</p>}
      {detail.data && <>
        <dl className="quality-detail-list">
          <div><dt>대상 자산</dt><dd>{detail.data.rule_set.asset_name}</dd></div>
          <div><dt>Lifecycle</dt><dd><QualityStatus value={detail.data.rule_set.state} /></dd></div>
          <div><dt>활성 버전</dt><dd>{detail.data.rule_set.active_version_number ? `v${detail.data.rule_set.active_version_number}` : '—'}</dd></div>
          <div><dt>버전 상태</dt><dd><QualityStatus value={detail.data.rule_set.active_version_state} /></dd></div>
          <div><dt>Rule 수</dt><dd>{countText(detail.data.rule_set.rule_count)}</dd></div>
          <div><dt>최근 변경</dt><dd>{dateTimeText(detail.data.rule_set.updated_at)}</dd></div>
        </dl>
        <RuleSetVersions
          versions={detail.data.versions}
          reviewerSubjectId={boundary.subjectId}
          reviewAvailable={axes.get('review')?.state === 'AVAILABLE'}
          activationAvailable={axes.get('activation')?.state === 'AVAILABLE'}
          busyVersionId={commandBusy}
          reviewVersionId={reviewVersionId}
          reviewDecision={reviewDecision}
          reviewReason={reviewReason}
          onReviewOpen={(version) => {
            setReviewVersionId(version.version_id)
            setReviewDecision('APPROVE')
            setReviewReason('')
          }}
          onReviewDecision={setReviewDecision}
          onReviewReason={setReviewReason}
          onReview={(version) => void reviewVersion(version)}
          onReviewCancel={() => {
            setReviewVersionId(undefined)
            setReviewReason('')
          }}
          onActivate={(version) => void activateVersion(version)}
        />
        <RuleSetDefinitions definitions={detail.data.definitions} />
        {axes.get('manual_execution')?.state === 'AVAILABLE'
          ? <div className="action-row">
            <button
              type="button"
              className="button"
              disabled={Boolean(commandBusy) || !detail.data.rule_set.active_version_id}
              onClick={() => void requestManualRun()}
            >
              {commandBusy === 'manual-run' ? '실행 요청 중…' : '활성 버전 수동 실행'}
            </button>
          </div>
          : <QualityAxisLock axis={axes.get('manual_execution')} title="수동 실행 잠김" />}
      </>}
    </Dialog>
  </section>
}

function RuleCatalog({ definitions }: { definitions: QualityRuleDefinitionCapability[] }) {
  return <ul>{definitions.map((definition) => <li key={definition.kind}>
    <QualityStatus value={definition.available ? 'AVAILABLE' : 'UNAVAILABLE'} />
    <strong>{definition.kind}</strong>
    {!definition.available && <span>{definition.reason_code ?? '비활성'}</span>}
  </li>)}</ul>
}

function RuleProposalDialog({
  open,
  selectedCount,
  commonFields,
  namePrefix,
  drafts,
  busy,
  error,
  onNamePrefix,
  onDrafts,
  onSubmit,
  onClose,
}: {
  open: boolean
  selectedCount: number
  commonFields: QualityAuthoringField[]
  namePrefix: string
  drafts: RuleDraftForm[]
  busy: boolean
  error: unknown
  onNamePrefix: (value: string) => void
  onDrafts: (value: RuleDraftForm[]) => void
  onSubmit: () => void
  onClose: () => void
}) {
  const addDraft = () => {
    const first = commonFields[0]
    const draft = first ? defaultDraft(first) : undefined
    if (draft && drafts.length < 100) onDrafts([...drafts, draft])
  }
  const updateDraft = (index: number, next: RuleDraftForm) => {
    onDrafts(drafts.map((draft, candidate) => candidate === index ? next : draft))
  }
  const valid = proposalPayload(namePrefix, ['selection-placeholder'], drafts, commonFields) !== null

  return <Dialog
    open={open}
    title="Rule Set 일괄 제안"
    description={`선택한 ${countText(selectedCount)}개 자산에 동일한 typed Rule을 단일 트랜잭션으로 제안합니다.`}
    size="large"
    onRequestClose={onClose}
    footer={<>
      <button type="button" className="button button-secondary" disabled={busy} onClick={onClose}>취소</button>
      <button type="button" className="button" disabled={busy || !valid} onClick={onSubmit}>
        {busy ? '제안 저장 중…' : '일괄 제안 저장'}
      </button>
    </>}
  >
    {Boolean(error) && <ErrorNotice error={error} />}
    <div className="grid gap-3">
      <label className="grid gap-1 text-xs font-bold">
        Rule Set 이름 접두어
        <input
          required
          minLength={1}
          maxLength={100}
          value={namePrefix}
          disabled={busy}
          onChange={(event) => onNamePrefix(event.target.value)}
          placeholder="자산명 앞에 붙일 관리용 이름"
        />
      </label>
      <p className="callout">필드 식별자와 지원 Rule 종류는 선택 자산들의 서버 authoring 계약 교집합만 표시됩니다.</p>
      {drafts.map((draft, index) => {
        const field = commonFields.find((candidate) => (
          candidate.field_identifier === draft.field_identifier
        ))
        return <fieldset key={`${index}-${draft.field_identifier}`} className="grid gap-3 rounded-enterprise border border-slate-300 p-3">
          <legend>Rule {index + 1}</legend>
          <label className="grid gap-1 text-xs font-bold">
            필드
            <select
              value={draft.field_identifier}
              disabled={busy}
              onChange={(event) => {
                const nextField = commonFields.find((candidate) => (
                  candidate.field_identifier === event.target.value
                ))
                const next = nextField ? defaultDraft(nextField) : undefined
                if (next) updateDraft(index, { ...next, severity: draft.severity })
              }}
            >
              {commonFields.map((candidate) => (
                <option key={candidate.field_identifier} value={candidate.field_identifier}>
                  {candidate.display_path} · {candidate.logical_type}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-bold">
            Rule 종류
            <select
              value={draft.kind}
              disabled={busy}
              onChange={(event) => updateDraft(index, {
                ...draft,
                kind: event.target.value as QualityAuthoringRuleKind,
                min_value: '',
                max_value: '',
              })}
            >
              {(field?.supported_rule_kinds ?? []).map((kind) => <option key={kind}>{kind}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-bold">
            실패 등급
            <select
              value={draft.severity}
              disabled={busy}
              onChange={(event) => updateDraft(index, {
                ...draft,
                severity: event.target.value as QualityRuleSeverity,
              })}
            >
              <option>BLOCKING</option>
              <option>ADVISORY</option>
            </select>
          </label>
          {draft.kind === 'RANGE' && field && <RangeFields
            field={field}
            draft={draft}
            disabled={busy}
            onChange={(next) => updateDraft(index, next)}
          />}
          <button
            type="button"
            className="button button-secondary"
            disabled={busy || drafts.length === 1}
            onClick={() => onDrafts(drafts.filter((_, candidate) => candidate !== index))}
          >
            Rule 제거
          </button>
        </fieldset>
      })}
      <button
        type="button"
        className="button button-secondary"
        disabled={busy || drafts.length >= 100}
        onClick={addDraft}
      >
        Rule 추가
      </button>
    </div>
  </Dialog>
}

function RangeFields({
  field,
  draft,
  disabled,
  onChange,
}: {
  field: QualityAuthoringField
  draft: RuleDraftForm
  disabled: boolean
  onChange: (value: RuleDraftForm) => void
}) {
  const inputType = field.logical_type === 'DATE' ? 'date' : 'text'
  const placeholder = field.logical_type === 'TIMESTAMP'
    ? 'ISO 8601 timestamp with timezone'
    : field.logical_type === 'DECIMAL' ? '정확한 10진수' : undefined
  return <>
    <p className="callout">범위 타입: {field.logical_type}</p>
    <label className="grid gap-1 text-xs font-bold">
      최소값
      <input
        required
        type={inputType}
        maxLength={100}
        value={draft.min_value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange({ ...draft, min_value: event.target.value })}
      />
    </label>
    <label className="grid gap-1 text-xs font-bold">
      최대값
      <input
        required
        type={inputType}
        maxLength={100}
        value={draft.max_value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange({ ...draft, max_value: event.target.value })}
      />
    </label>
    <label>
      <input
        type="checkbox"
        checked={draft.inclusive_min}
        disabled={disabled}
        onChange={(event) => onChange({ ...draft, inclusive_min: event.target.checked })}
      /> 최소값 포함
    </label>
    <label>
      <input
        type="checkbox"
        checked={draft.inclusive_max}
        disabled={disabled}
        onChange={(event) => onChange({ ...draft, inclusive_max: event.target.checked })}
      /> 최대값 포함
    </label>
  </>
}

function RuleSetVersions({
  versions,
  reviewerSubjectId,
  reviewAvailable,
  activationAvailable,
  busyVersionId,
  reviewVersionId,
  reviewDecision,
  reviewReason,
  onReviewOpen,
  onReviewDecision,
  onReviewReason,
  onReview,
  onReviewCancel,
  onActivate,
}: {
  versions: QualityRuleSetVersionSummary[]
  reviewerSubjectId: string
  reviewAvailable: boolean
  activationAvailable: boolean
  busyVersionId?: string
  reviewVersionId?: string
  reviewDecision: 'APPROVE' | 'REJECT'
  reviewReason: string
  onReviewOpen: (version: QualityRuleSetVersionSummary) => void
  onReviewDecision: (value: 'APPROVE' | 'REJECT') => void
  onReviewReason: (value: string) => void
  onReview: (version: QualityRuleSetVersionSummary) => void
  onReviewCancel: () => void
  onActivate: (version: QualityRuleSetVersionSummary) => void
}) {
  return <section className="quality-results" aria-labelledby="quality-rule-version-title">
    <h3 id="quality-rule-version-title">버전 이력</h3>
    {versions.length === 0
      ? <p className="quality-empty" role="status">저장된 Rule Set 버전이 없습니다.</p>
      : <ul className="quality-history-list">{versions.map((version) => <li key={version.version_id}>
        <strong>v{version.version_number}</strong>
        <QualityStatus value={version.state} />
        <span>{countText(version.rule_count)}개 Rule</span>
        <span>{version.schedule_mode}</span>
        <span>{dateTimeText(version.updated_at)}</span>
        {reviewAvailable
          && version.state === 'PROPOSED'
          && version.author_id !== reviewerSubjectId
          && reviewVersionId !== version.version_id
          && <button
            type="button"
            className="button button-secondary"
            disabled={Boolean(busyVersionId)}
            onClick={() => onReviewOpen(version)}
          >
            이 버전 검토
          </button>}
        {reviewVersionId === version.version_id && <fieldset className="grid gap-2">
          <legend>v{version.version_number} 독립 검토</legend>
          <label>
            결정
            <select
              value={reviewDecision}
              disabled={Boolean(busyVersionId)}
              onChange={(event) => onReviewDecision(
                event.target.value as 'APPROVE' | 'REJECT',
              )}
            >
              <option value="APPROVE">승인</option>
              <option value="REJECT">반려</option>
            </select>
          </label>
          <label>
            검토 사유
            <textarea
              required
              maxLength={4_000}
              value={reviewReason}
              disabled={Boolean(busyVersionId)}
              onChange={(event) => onReviewReason(event.target.value)}
            />
          </label>
          <div className="action-row">
            <button
              type="button"
              className="button button-secondary"
              disabled={Boolean(busyVersionId)}
              onClick={onReviewCancel}
            >
              취소
            </button>
            <button
              type="button"
              className="button"
              disabled={Boolean(busyVersionId) || !reviewReason.trim()}
              onClick={() => onReview(version)}
            >
              {busyVersionId === version.version_id ? '검토 저장 중…' : '검토 결정 저장'}
            </button>
          </div>
        </fieldset>}
        {activationAvailable && version.state === 'APPROVED' && <button
          type="button"
          className="button button-secondary"
          disabled={Boolean(busyVersionId)}
          onClick={() => onActivate(version)}
        >
          {busyVersionId === version.version_id ? '활성화 중…' : '이 버전 활성화'}
        </button>}
      </li>)}</ul>}
  </section>
}

function RuleSetDefinitions({ definitions }: { definitions: QualityRuleDefinition[] }) {
  return <section className="quality-results" aria-labelledby="quality-rule-definition-title">
    <h3 id="quality-rule-definition-title">Typed Rule Definitions</h3>
    {definitions.length === 0
      ? <p className="quality-empty" role="status">저장된 typed Rule이 없습니다.</p>
      : <ol className="quality-history-list">{definitions.map((definition) => <li key={definition.rule_definition_id}>
        <strong>{definition.field_identifier}</strong>
        <span>{definition.kind}</span>
        <QualityStatus value={definition.severity} />
      </li>)}</ol>}
  </section>
}

function commonAuthoringFields(
  details: Array<QualityAssetDetailResponse | undefined>,
  selectedCount: number,
  catalogKinds: ReadonlySet<string>,
): QualityAuthoringField[] {
  if (
    selectedCount === 0
    || details.length !== selectedCount
    || details.some((detail) => detail?.authoring.state !== 'READY')
  ) {
    return []
  }
  const complete = details as QualityAssetDetailResponse[]
  const first = complete[0]
  if (!first) return []
  return first.authoring.fields.flatMap((field) => {
    const supported = field.supported_rule_kinds.filter((kind) => (
      catalogKinds.has(kind)
      && (kind !== 'RANGE' || RANGE_LOGICAL_TYPES.has(field.logical_type))
      && complete.every((detail) => {
        const candidate = detail.authoring.fields.find((item) => (
          item.field_identifier === field.field_identifier
        ))
        return Boolean(
          candidate
          && candidate.logical_type === field.logical_type
          && candidate.supported_rule_kinds.includes(kind),
        )
      })
    ))
    return supported.length > 0 ? [{ ...field, supported_rule_kinds: supported }] : []
  })
}

function defaultDraft(field: QualityAuthoringField): RuleDraftForm | undefined {
  const kind = field.supported_rule_kinds[0]
  if (!kind) return undefined
  return {
    field_identifier: field.field_identifier,
    kind,
    severity: 'BLOCKING',
    min_value: '',
    max_value: '',
    inclusive_min: true,
    inclusive_max: true,
  }
}

function proposalPayload(
  namePrefix: string,
  assetIds: string[],
  drafts: RuleDraftForm[],
  commonFields: QualityAuthoringField[],
): QualityRuleBatchProposalRequest | null {
  const prefix = namePrefix.trim()
  if (
    !prefix
    || prefix.length > 100
    || assetIds.length < 1
    || assetIds.length > 25
    || new Set(assetIds).size !== assetIds.length
    || drafts.length < 1
    || drafts.length > 100
  ) {
    return null
  }
  const rules: QualityRuleDraftRequest[] = []
  const identities = new Set<string>()
  for (const draft of drafts) {
    const field = commonFields.find((candidate) => (
      candidate.field_identifier === draft.field_identifier
    ))
    if (!field || !field.supported_rule_kinds.includes(draft.kind)) return null
    const identity = `${draft.field_identifier}\u0000${draft.kind}`
    if (identities.has(identity)) return null
    identities.add(identity)
    if (draft.kind === 'NOT_NULL') {
      rules.push({
        field_identifier: draft.field_identifier,
        kind: draft.kind,
        severity: draft.severity,
        parameters: {},
      })
      continue
    }
    if (
      !RANGE_LOGICAL_TYPES.has(field.logical_type)
      || !draft.min_value.trim()
      || !draft.max_value.trim()
    ) {
      return null
    }
    rules.push({
      field_identifier: draft.field_identifier,
      kind: draft.kind,
      severity: draft.severity,
      parameters: {
        value_type: field.logical_type,
        min_value: draft.min_value.trim(),
        max_value: draft.max_value.trim(),
        inclusive_min: draft.inclusive_min,
        inclusive_max: draft.inclusive_max,
      },
    })
  }
  return {
    name_prefix: prefix,
    asset_ids: assetIds,
    rules,
  }
}
