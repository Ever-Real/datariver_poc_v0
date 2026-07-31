import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ExternalLink,
  Monitor,
  Plus,
  RefreshCw,
  Settings2,
  Trash2,
} from 'lucide-react'
import type { ApiClient } from '../../api/client'
import type {
  CapabilitiesResponse,
  MonitoringConfiguration,
  MonitoringDashboard,
} from '../../api/types'
import { ErrorNotice } from '../../components/ErrorNotice'
import { Dialog } from '../../components/common/Dialog'
import { useRovingTabs } from '../../components/common/useRovingTabs'
import { PageTitle } from '../../components/layout/PageTitle'

interface MonitoringDashboardDraft {
  id: string
  label: string
  url: string
  height_px: number
}

export function MonitoringPage({
  client,
  canManageTabs = false,
  canUpdateTabs = false,
  onRequestAdminAssurance,
}: {
  client: ApiClient
  canManageTabs?: boolean
  canUpdateTabs?: boolean
  onRequestAdminAssurance?: () => Promise<void>
}) {
  const [configuration, setConfiguration] = useState<MonitoringConfiguration>({
    items: [],
    version: 0,
  })
  const [activeId, setActiveId] = useState<string>()
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(true)
  const [editorOpen, setEditorOpen] = useState(false)
  const [drafts, setDrafts] = useState<MonitoringDashboardDraft[]>([])
  const [saving, setSaving] = useState(false)

  const refresh = useCallback(async () => {
    setError(undefined)
    setLoading(true)
    try {
      const response = await client.request<CapabilitiesResponse>('/capabilities', {
        cache: 'no-store',
      })
      setConfiguration(response.monitoring_configuration)
      setActiveId((current) => (
        current && response.monitoring_configuration.items.some((item) => item.id === current)
          ? current
          : response.monitoring_configuration.items[0]?.id
      ))
    } catch (next) {
      setError(next)
    } finally {
      setLoading(false)
    }
  }, [client])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    setActiveId((current) => (
      current && configuration.items.some((item) => item.id === current)
        ? current
        : configuration.items[0]?.id
    ))
  }, [configuration.items])

  const dashboardIds = useMemo(
    () => configuration.items.map((item) => item.id),
    [configuration.items],
  )
  const tabs = useRovingTabs({
    ids: dashboardIds,
    activeId,
    idPrefix: 'monitoring',
    onSelect: setActiveId,
  })
  const activeDashboard = configuration.items.find((item) => item.id === activeId)

  const openEditor = () => {
    setDrafts(configuration.items.map((item) => ({
      id: item.id,
      label: item.label,
      url: item.url,
      height_px: item.height_px,
    })))
    setError(undefined)
    setEditorOpen(true)
  }

  const addDraft = () => {
    if (drafts.length >= 8) return
    setDrafts((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        label: `Dashboard ${current.length + 1}`,
        url: '',
        height_px: 900,
      },
    ])
  }

  const updateDraft = (
    id: string,
    field: 'label' | 'url' | 'height_px',
    value: string | number,
  ) => {
    setDrafts((current) => current.map((item) => (
      item.id === id ? { ...item, [field]: value } : item
    )))
  }

  const moveDraft = (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction
    if (nextIndex < 0 || nextIndex >= drafts.length) return
    setDrafts((current) => {
      const next = [...current]
      const item = next[index]
      const target = next[nextIndex]
      if (!item || !target) return current
      next[index] = target
      next[nextIndex] = item
      return next
    })
  }

  const saveDrafts = async () => {
    if (!canUpdateTabs || saving) return
    if (drafts.some((item) => !item.label.trim() || !item.url.trim())) {
      setError(new Error('각 탭의 이름과 Dashboard Link를 입력하세요.'))
      return
    }
    setSaving(true)
    setError(undefined)
    try {
      const next = await client.request<MonitoringConfiguration>(
        '/admin/monitoring-configuration',
        {
          method: 'PUT',
          ifMatch: `"${configuration.version}"`,
          body: JSON.stringify({
            items: drafts.map((item) => ({
              id: item.id,
              label: item.label.trim(),
              url: item.url.trim(),
              height_px: item.height_px,
            })),
          }),
        },
      )
      setConfiguration(next)
      setEditorOpen(false)
    } catch (next) {
      setError(next)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="monitoring-page">
      <PageTitle
        icon="MO"
        eyebrow="Infrastructure monitoring"
        title="Infrastructure Monitoring"
        description="서버가 검증한 Monitoring Dashboard 탭과 관측성 링크를 표시합니다."
      />
      <ErrorNotice error={error} />
      <div className="monitoring-tabs-shell">
        <div className="monitoring-tabs" role="tablist" aria-label="Monitoring dashboards">
          {configuration.items.map((dashboard) => (
            <button
              {...tabs.tabProps(dashboard.id)}
              className={dashboard.id === activeId ? 'active' : ''}
              key={dashboard.id}
              onClick={() => setActiveId(dashboard.id)}
              type="button"
            >
              {dashboard.label}
            </button>
          ))}
          {!loading && configuration.items.length === 0 && (
            <span className="monitoring-tabs-empty">등록된 Dashboard 없음</span>
          )}
        </div>
        <div className="monitoring-tab-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RefreshCw size={14} />
            새로고침
          </button>
          {canManageTabs && (
            <button className="button" type="button" onClick={openEditor}>
              <Settings2 size={14} />
              탭 수정
            </button>
          )}
        </div>
      </div>
      <div
        {...(activeDashboard ? tabs.panelProps(activeDashboard.id) : {})}
        className="monitoring-frame"
        aria-busy={loading}
      >
        {loading ? (
          <div className="monitoring-frame-state">
            <span className="loader" />
            <p>Monitoring Dashboard를 조회하고 있습니다.</p>
          </div>
        ) : activeDashboard ? (
          <MonitoringDashboardPanel dashboard={activeDashboard} />
        ) : (
          <div className="monitoring-frame-state">
            <Monitor size={38} aria-hidden="true" />
            <div>
              <h2>Monitoring Dashboard가 없습니다.</h2>
              <p>
                관리자는 탭 수정에서 HTTP(S) Dashboard Link를 등록할 수 있습니다.
              </p>
            </div>
          </div>
        )}
      </div>
      <Dialog
        open={editorOpen}
        title="Monitoring 탭 수정"
        description="탭별 Dashboard Link와 페이지 높이를 설정합니다. iframe 승인이 없는 외부 링크는 새 창에서 열립니다."
        size="large"
        onRequestClose={() => {
          if (!saving) setEditorOpen(false)
        }}
        footer={(
          <>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => setEditorOpen(false)}
              disabled={saving}
            >
              취소
            </button>
            {canUpdateTabs ? (
              <button className="button" type="button" onClick={() => void saveDrafts()} disabled={saving}>
                {saving ? '저장 중…' : '저장'}
              </button>
            ) : (
              <button
                className="button"
                type="button"
                onClick={() => void onRequestAdminAssurance?.()}
              >
                관리자 재인증
              </button>
            )}
          </>
        )}
      >
        {!canUpdateTabs && (
          <p className="notice">
            탭을 변경하려면 최근 관리자 인증이 필요합니다. 재인증 후 변경 내용은 자동
            저장되지 않습니다.
          </p>
        )}
        <div className="monitoring-editor-list">
          {drafts.map((draft, index) => (
            <section className="monitoring-editor-item" key={draft.id}>
              <div className="monitoring-editor-order">
                <strong>{index + 1}</strong>
                <button
                  type="button"
                  aria-label={`${draft.label} 위로 이동`}
                  onClick={() => moveDraft(index, -1)}
                  disabled={!canUpdateTabs || index === 0}
                >
                  <ArrowUp size={14} />
                </button>
                <button
                  type="button"
                  aria-label={`${draft.label} 아래로 이동`}
                  onClick={() => moveDraft(index, 1)}
                  disabled={!canUpdateTabs || index === drafts.length - 1}
                >
                  <ArrowDown size={14} />
                </button>
              </div>
              <div className="monitoring-editor-fields">
                <label>
                  탭 이름
                  <input
                    value={draft.label}
                    maxLength={80}
                    disabled={!canUpdateTabs}
                    onChange={(event) => updateDraft(draft.id, 'label', event.target.value)}
                  />
                </label>
                <label>
                  Dashboard Link
                  <input
                    value={draft.url}
                    type="url"
                    maxLength={2000}
                    placeholder="https://monitoring.example/dashboard"
                    disabled={!canUpdateTabs}
                    onChange={(event) => updateDraft(draft.id, 'url', event.target.value)}
                  />
                </label>
                <label>
                  페이지 높이 (px)
                  <input
                    value={draft.height_px}
                    type="number"
                    min={480}
                    max={2000}
                    step={20}
                    disabled={!canUpdateTabs}
                    onChange={(event) => updateDraft(
                      draft.id,
                      'height_px',
                      Number(event.target.value),
                    )}
                  />
                </label>
              </div>
              <button
                className="button button-secondary monitoring-editor-remove"
                type="button"
                aria-label={`${draft.label} 탭 삭제`}
                disabled={!canUpdateTabs}
                onClick={() => setDrafts((current) => (
                  current.filter((item) => item.id !== draft.id)
                ))}
              >
                <Trash2 size={14} />
                삭제
              </button>
            </section>
          ))}
          {drafts.length === 0 && (
            <p className="monitoring-editor-empty">등록된 Dashboard 탭이 없습니다.</p>
          )}
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={addDraft}
          disabled={!canUpdateTabs || drafts.length >= 8}
        >
          <Plus size={14} />
          탭 추가
        </button>
      </Dialog>
    </section>
  )
}

function MonitoringDashboardPanel({ dashboard }: { dashboard: MonitoringDashboard }) {
  if (dashboard.embed_state === 'AVAILABLE' && dashboard.embed_url) {
    return (
      <div
        className="monitoring-approved-embed"
        style={{ minHeight: dashboard.height_px + 43 }}
      >
        <div className="monitoring-embed-notice">
          <span>
            <Monitor size={20} aria-hidden="true" />
          </span>
          <p>
            서버가 iframe 표시를 승인한 <strong>{dashboard.label}</strong> Dashboard입니다.
          </p>
          <a
            className="button button-secondary"
            href={dashboard.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink size={14} />
            새 창으로 열기
          </a>
        </div>
        <iframe
          className="monitoring-grafana-frame"
          loading="lazy"
          referrerPolicy="no-referrer"
          sandbox="allow-forms allow-same-origin allow-scripts"
          src={dashboard.embed_url}
          style={{ height: dashboard.height_px }}
          title={`${dashboard.label} Monitoring Dashboard`}
        />
      </div>
    )
  }
  return (
    <div className="monitoring-approved-link">
      <span>
        <Monitor size={35} aria-hidden="true" />
      </span>
      <div>
        <p className="eyebrow">Approved external observability</p>
        <h2>{dashboard.label}</h2>
        <p>
          이 Dashboard는 서버가 검증한 링크입니다. 현재 배포에서 iframe 표시가 승인되지
          않아 새 창에서 엽니다.
        </p>
        <a
          className="button"
          href={dashboard.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          <ExternalLink size={14} />
          {dashboard.label} 열기
        </a>
      </div>
    </div>
  )
}
