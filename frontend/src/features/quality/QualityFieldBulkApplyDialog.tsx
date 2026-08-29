import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type {
  QualityCapabilityAxis,
  QualityCommonRuleTemplate,
  QualityRuleDraftRequest,
  QualityRuleSeverity,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'
import { qualityQueryKey, type QualityApi, type QualitySecurityBoundary } from './qualityApi'
import type {
  QualityFieldSelection,
  QualityTemplateFieldBindingRequest,
} from './qualityFieldTypes'
import { countText } from './QualityShared'
import { isAuthorizationBoundaryError } from './useBoundedQualityRunPolling'

type SourceMode = 'NEW' | 'TEMPLATE'
type RangeType = 'DECIMAL' | 'DATE' | 'TIMESTAMP'

interface RangeParameters {
  value_type: RangeType
  min_value: string
  max_value: string
  inclusive_min: boolean
  inclusive_max: boolean
}

export function QualityFieldBulkApplyDialog({
  open,
  api,
  boundary,
  axes,
  selections,
  lockedTemplate,
  onClose,
  onApplied,
  onBoundaryInvalid,
}: {
  open: boolean
  api: QualityApi
  boundary: QualitySecurityBoundary
  axes: ReadonlyMap<string, QualityCapabilityAxis>
  selections: QualityFieldSelection[]
  lockedTemplate?: QualityCommonRuleTemplate
  onClose: () => void
  onApplied: (count: number, replayed: boolean) => Promise<void>
  onBoundaryInvalid: () => void
}) {
  const [mode, setMode] = useState<SourceMode>(lockedTemplate ? 'TEMPLATE' : 'NEW')
  const [templateId, setTemplateId] = useState(lockedTemplate?.template_id ?? '')
  const [name, setName] = useState('필드 품질 룰')
  const [kind, setKind] = useState<'NOT_NULL' | 'RANGE'>('NOT_NULL')
  const [severity, setSeverity] = useState<QualityRuleSeverity>('BLOCKING')
  const [parameters, setParameters] = useState<Record<string, RangeParameters>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>()
  const submissionIdentity = useRef<{ signature: string; key: string } | undefined>(undefined)
  const templates = useQuery({
    queryKey: qualityQueryKey(boundary, 'common-rule-templates', 'field-bulk-dialog'),
    queryFn: ({ signal }) => api.commonRuleTemplates(boundary.cacheScope, signal),
    enabled: open && !lockedTemplate,
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const template = lockedTemplate
    ?? templates.data?.items.find((item) => item.template_id === templateId)
  const bindings = useMemo(
    () => template ? templateBindings(template, selections) : [],
    [selections, template],
  )
  const newTargets = useMemo(
    () => selections.filter((selection) => selection.supported_rule_kinds.includes(kind)),
    [kind, selections],
  )
  const rangeEntries = useMemo(() => {
    if (mode === 'NEW') {
      if (kind !== 'RANGE') return []
      return newTargets.flatMap((selection) => {
        const valueType = rangeType(selection.logical_type)
        return valueType ? [{ key: selectionKey(selection), selection, valueType }] : []
      })
    }
    return bindings.flatMap(({ selection, binding, rule }) => {
      if (rule.kind !== 'RANGE') return []
      const valueType = rangeType(selection.logical_type)
      return valueType ? [{ key: bindingKey(selection, binding.template_rule_ordinal), selection, valueType }] : []
    })
  }, [bindings, kind, mode, newTargets])

  useEffect(() => {
    if (!open) return
    setMode(lockedTemplate ? 'TEMPLATE' : 'NEW')
    setTemplateId(lockedTemplate?.template_id ?? '')
    setName(lockedTemplate?.name ?? '필드 품질 룰')
    setKind('NOT_NULL')
    setSeverity('BLOCKING')
    setParameters({})
    setError(undefined)
    submissionIdentity.current = undefined
  }, [lockedTemplate, open])
  useEffect(() => {
    setParameters((current) => {
      const next = { ...current }
      for (const entry of rangeEntries) {
        if (!next[entry.key]) {
          next[entry.key] = defaultRange(entry.valueType, templateRangeParameters(template, entry))
        }
      }
      return next
    })
  }, [rangeEntries, template])
  useEffect(() => {
    if (isAuthorizationBoundaryError(templates.error)) onBoundaryInvalid()
  }, [onBoundaryInvalid, templates.error])

  const groupedTemplateTargets = groupTemplateTargets(bindings, parameters)
  const groupedNewTargets = groupNewTargets(newTargets, kind, severity, parameters)
  const targetGroups = mode === 'TEMPLATE' ? groupedTemplateTargets : groupedNewTargets
  const withinServerBounds = targetGroups.length <= 25
    && targetGroups.every((target) => (
      ('bindings' in target ? target.bindings.length : target.rules.length) <= 100
    ))

  const valid = axes.get('rule_authoring')?.state === 'AVAILABLE'
    && selections.length > 0
    && (mode === 'TEMPLATE' ? Boolean(template && bindings.length > 0) : Boolean(name.trim() && newTargets.length > 0))
    && rangeEntries.every((entry) => validRange(parameters[entry.key]))
    && withinServerBounds

  const submit = async () => {
    if (!valid) return
    setBusy(true)
    setError(undefined)
    try {
      const result = mode === 'TEMPLATE' && template
        ? await (() => {
            const payload = { targets: groupedTemplateTargets }
            return api.mapCommonRuleTemplate(
              template.template_id,
              payload,
              stableSubmissionKey(submissionIdentity, 'quality-template-field-map', payload),
            )
          })()
        : await (() => {
            const payload = {
              name_prefix: name.trim(),
              targets: groupedNewTargets,
            }
            return api.proposeTargetedRuleSets(
              payload,
              stableSubmissionKey(submissionIdentity, 'quality-field-rule', payload),
            )
          })()
      await onApplied(result.items.length, result.replayed)
    } catch (next) {
      if (isAuthorizationBoundaryError(next)) onBoundaryInvalid()
      setError(next)
    } finally {
      setBusy(false)
    }
  }

  return <Dialog
    open={open}
    title="선택 필드에 품질 룰 적용"
    description={`${countText(selections.length)}개 필드의 룰과 파라미터를 적용 전에 확인합니다.`}
    size="large"
    onRequestClose={() => { if (!busy) onClose() }}
    footer={<>
      <span>{countText(new Set(selections.map((item) => item.asset_id)).size)}개 테이블 · {countText(selections.length)}개 필드</span>
      <button type="button" className="button button-secondary" disabled={busy} onClick={onClose}>취소</button>
      <button type="button" className="button" disabled={busy || !valid} onClick={() => void submit()}>{busy ? '적용 중…' : '룰 적용'}</button>
    </>}
  >
    {Boolean(error) && <ErrorNotice error={error} />}
    {!lockedTemplate && <fieldset className="quality-bulk-source">
      <legend>1. 룰 소스</legend>
      <label><input type="radio" checked={mode === 'NEW'} onChange={() => setMode('NEW')} /> 신규 룰</label>
      <label><input type="radio" checked={mode === 'TEMPLATE'} onChange={() => setMode('TEMPLATE')} /> 공통 룰 샘플</label>
      {mode === 'TEMPLATE' && <select aria-label="공통 룰셋 선택" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
        <option value="">공통 룰셋 선택</option>
        {templates.data?.items.map((item) => <option key={item.template_id} value={item.template_id}>{item.name}</option>)}
      </select>}
    </fieldset>}
    {mode === 'NEW' && <fieldset className="quality-bulk-rule">
      <legend>2. 신규 룰 정의</legend>
      <label>룰셋 이름<input value={name} maxLength={100} onChange={(event) => setName(event.target.value)} /></label>
      <label>검사<select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="NOT_NULL">Not Null</option><option value="RANGE">Range</option></select></label>
      <label>실패 수준<select value={severity} onChange={(event) => setSeverity(event.target.value as QualityRuleSeverity)}><option value="BLOCKING">Fail</option><option value="ADVISORY">Warn</option></select></label>
    </fieldset>}
    {mode === 'TEMPLATE' && template && <section className="quality-bulk-template-summary">
      <strong>{template.name}</strong><span>{countText(bindings.length)}개 호환 룰-필드 조합</span>
    </section>}
    <RangeParameterEditor entries={rangeEntries} parameters={parameters} onChange={setParameters} />
    <section className="quality-bulk-schedule-readiness">
      <strong>3. 적용 전 확인</strong>
      <p>확인 후 적용하면 {countText(targetGroups.length)}개 테이블의 server-authoritative PROPOSED 룰셋과 매핑을 저장합니다. GX 실행과 스케줄 등록은 포함되지 않습니다.</p>
      <p>스케줄 등록은 현재 read-only입니다. {axes.get('scheduling')?.reason_code ?? 'SCHEDULE_PROFILE_ATTESTATION_UNAVAILABLE'}</p>
    </section>
    {!withinServerBounds && <p className="callout" role="status">
      한 번에 최대 25개 테이블, 테이블별 100개 룰까지 적용할 수 있습니다. 선택 범위를 줄여 주세요.
    </p>}
    {mode === 'NEW' && newTargets.length !== selections.length && <p className="callout" role="status">
      선택 필드 중 {countText(selections.length - newTargets.length)}개는 현재 룰 타입과 호환되지 않아 적용 대상에서 제외됩니다.
    </p>}
  </Dialog>
}

function RangeParameterEditor({
  entries,
  parameters,
  onChange,
}: {
  entries: Array<{ key: string; selection: QualityFieldSelection; valueType: RangeType }>
  parameters: Record<string, RangeParameters>
  onChange: (value: Record<string, RangeParameters>) => void
}) {
  const types = [...new Set(entries.map((entry) => entry.valueType))]
  if (entries.length === 0) return null
  const update = (key: string, value: RangeParameters) => onChange({ ...parameters, [key]: value })
  const applyType = (type: RangeType, source: RangeParameters) => onChange({
    ...parameters,
    ...Object.fromEntries(entries.filter((entry) => entry.valueType === type).map((entry) => [entry.key, source])),
  })
  return <fieldset className="quality-bulk-parameters">
    <legend>2. RANGE 파라미터 · 일괄 또는 개별 입력</legend>
    {types.map((type) => {
      const first = entries.find((entry) => entry.valueType === type)
      const value = first ? parameters[first.key] : undefined
      if (!first || !value) return null
      return <div key={type} className="quality-bulk-batch-parameter">
        <strong>{type} 일괄값</strong>
        <RangeInputs value={value} onChange={(next) => applyType(type, next)} />
      </div>
    })}
    <div className="quality-bulk-field-parameters">{entries.map((entry) => {
      const value = parameters[entry.key]
      if (!value) return null
      return <div key={entry.key}>
        <span>{entry.selection.asset_name} · {entry.selection.display_path}</span>
        <RangeInputs value={value} onChange={(next) => update(entry.key, next)} />
      </div>
    })}</div>
  </fieldset>
}

function RangeInputs({ value, onChange }: { value: RangeParameters; onChange: (value: RangeParameters) => void }) {
  return <div className="quality-range-inputs">
    <label>최소값<input value={value.min_value} maxLength={100} onChange={(event) => onChange({ ...value, min_value: event.target.value })} /></label>
    <label>최대값<input value={value.max_value} maxLength={100} onChange={(event) => onChange({ ...value, max_value: event.target.value })} /></label>
    <label><input type="checkbox" checked={value.inclusive_min} onChange={(event) => onChange({ ...value, inclusive_min: event.target.checked })} /> 최소 포함</label>
    <label><input type="checkbox" checked={value.inclusive_max} onChange={(event) => onChange({ ...value, inclusive_max: event.target.checked })} /> 최대 포함</label>
  </div>
}

function templateBindings(template: QualityCommonRuleTemplate, selections: QualityFieldSelection[]) {
  return selections.flatMap((selection) => {
    const usedKinds = new Set<string>()
    return template.rules.flatMap((rule, index) => {
      if (usedKinds.has(rule.kind) || !selection.supported_rule_kinds.includes(rule.kind)) return []
      if (rule.kind === 'RANGE' && rangeType(selection.logical_type) !== rule.parameters.value_type) return []
      usedKinds.add(rule.kind)
      return [{
        selection,
        rule,
        binding: {
          template_rule_ordinal: index + 1,
          field_identifier: selection.field_identifier,
        } satisfies QualityTemplateFieldBindingRequest,
      }]
    })
  })
}

function groupTemplateTargets(
  bindings: ReturnType<typeof templateBindings>,
  parameters: Record<string, RangeParameters>,
) {
  const grouped = new Map<string, QualityTemplateFieldBindingRequest[]>()
  for (const { selection, binding, rule } of bindings) {
    const resolved = rule.kind === 'RANGE'
      ? { ...binding, parameters_override: parameters[bindingKey(selection, binding.template_rule_ordinal)] }
      : binding
    grouped.set(selection.asset_id, [...(grouped.get(selection.asset_id) ?? []), resolved])
  }
  return [...grouped].map(([asset_id, targetBindings]) => ({ asset_id, bindings: targetBindings }))
}

function groupNewTargets(
  selections: QualityFieldSelection[],
  kind: 'NOT_NULL' | 'RANGE',
  severity: QualityRuleSeverity,
  parameters: Record<string, RangeParameters>,
) {
  const grouped = new Map<string, QualityRuleDraftRequest[]>()
  for (const selection of selections) {
    const rule: QualityRuleDraftRequest = {
      field_identifier: selection.field_identifier,
      kind,
      severity,
      parameters: kind === 'RANGE'
        ? { ...(parameters[selectionKey(selection)] ?? {}) }
        : {},
    }
    grouped.set(selection.asset_id, [...(grouped.get(selection.asset_id) ?? []), rule])
  }
  return [...grouped].map(([asset_id, rules]) => ({ asset_id, rules }))
}

function templateRangeParameters(
  template: QualityCommonRuleTemplate | undefined,
  entry: { selection: QualityFieldSelection; key: string },
): Partial<RangeParameters> | undefined {
  if (!template) return undefined
  const ordinal = Number(entry.key.split(':').at(-1))
  const parameters = template.rules[ordinal - 1]?.parameters
  return parameters
}

function defaultRange(valueType: RangeType, source?: Partial<RangeParameters>): RangeParameters {
  return {
    value_type: valueType,
    min_value: typeof source?.min_value === 'string' ? source.min_value : '',
    max_value: typeof source?.max_value === 'string' ? source.max_value : '',
    inclusive_min: typeof source?.inclusive_min === 'boolean' ? source.inclusive_min : true,
    inclusive_max: typeof source?.inclusive_max === 'boolean' ? source.inclusive_max : true,
  }
}

function validRange(value: RangeParameters | undefined): boolean {
  return Boolean(value && value.min_value.trim() && value.max_value.trim())
}

function rangeType(type: QualityFieldSelection['logical_type']): RangeType | undefined {
  if (type === 'DECIMAL' || type === 'DATE' || type === 'TIMESTAMP') return type
  if (type === 'INTEGER') return 'DECIMAL'
  return undefined
}

function selectionKey(selection: QualityFieldSelection): string {
  return `${selection.asset_id}:${selection.field_identifier}`
}

function bindingKey(selection: QualityFieldSelection, ordinal: number): string {
  return `${selectionKey(selection)}:${ordinal}`
}

function stableSubmissionKey(
  identity: { current: { signature: string; key: string } | undefined },
  prefix: string,
  payload: unknown,
): string {
  const signature = `${prefix}:${JSON.stringify(payload)}`
  if (identity.current?.signature !== signature) {
    identity.current = { signature, key: `${prefix}-${crypto.randomUUID()}` }
  }
  return identity.current.key
}
