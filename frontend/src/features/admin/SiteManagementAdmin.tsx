import { useCallback, useEffect, useRef, useState } from 'react'
import type { SiteBrandingAsset, SiteBrandingBadge } from '../../api/types'
import { useSiteBranding } from '../../components/layout/SiteBranding'
import type { AdminApi, VersionedSiteBranding } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'

type UploadDraft = { mime_type: string; data_base64: string; data_url: string; byte_size: number }
type AssetDraft = SiteBrandingAsset | UploadDraft | null
type BadgeDraft = Omit<SiteBrandingBadge, 'badge_id' | 'logo' | 'order'> & {
  badge_id?: string
  logo: AssetDraft
}

const maximumLogoBytes = 512 * 1024
const maximumFaviconBytes = 128 * 1024

function base64(bytes: Uint8Array) {
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192))
  }
  return window.btoa(binary)
}

function canonicalMime(file: File, kind: 'logo' | 'favicon') {
  if (file.type === 'image/png') return 'image/png'
  if (kind === 'logo' && file.type === 'image/jpeg') return 'image/jpeg'
  if (kind === 'favicon' && ['image/x-icon', 'image/vnd.microsoft.icon'].includes(file.type)) return 'image/x-icon'
  throw new Error(kind === 'logo'
    ? '로고는 PNG 또는 JPEG 래스터 파일만 사용할 수 있습니다.'
    : '파비콘은 PNG 또는 ICO 파일만 사용할 수 있습니다.')
}

async function uploadDraft(file: File, kind: 'logo' | 'favicon'): Promise<UploadDraft> {
  const maximum = kind === 'logo' ? maximumLogoBytes : maximumFaviconBytes
  if (file.size < 1 || file.size > maximum) {
    throw new Error(`${kind === 'logo' ? '로고' : '파비콘'} 파일 크기 제한을 확인하세요.`)
  }
  const mimeType = canonicalMime(file, kind)
  const dataBase64 = base64(new Uint8Array(await file.arrayBuffer()))
  return {
    mime_type: mimeType,
    data_base64: dataBase64,
    data_url: `data:${mimeType};base64,${dataBase64}`,
    byte_size: file.size,
  }
}

function requestAsset(asset: AssetDraft) {
  if (!asset) return null
  return 'asset_id' in asset
    ? { asset_id: asset.asset_id }
    : { mime_type: asset.mime_type, data_base64: asset.data_base64 }
}

export interface SiteManagementAdminProps {
  api: AdminApi
  requestConfirmation: (pending: PendingAdminMutation) => void
  reportError: (error: unknown) => void
  keyFor: (intent: string, prefix: string) => string
  clearKey: (intent: string) => void
}

export function SiteManagementAdmin({
  api, requestConfirmation, reportError, keyFor, clearKey,
}: SiteManagementAdminProps) {
  const { publish } = useSiteBranding()
  const [current, setCurrent] = useState<VersionedSiteBranding>()
  const [siteName, setSiteName] = useState('DataRiver')
  const [logo, setLogo] = useState<AssetDraft>(null)
  const [favicon, setFavicon] = useState<AssetDraft>(null)
  const [badges, setBadges] = useState<BadgeDraft[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const generation = useRef(0)

  const load = useCallback(async (signal?: AbortSignal) => {
    const requestGeneration = ++generation.current
    setLoading(true)
    setMessage('')
    try {
      const next = await api.getSiteBranding(signal)
      if (signal?.aborted || requestGeneration !== generation.current) return
      setCurrent(next)
      setSiteName(next.site_name)
      setLogo(next.logo)
      setFavicon(next.favicon)
      setBadges((next.custom_badges ?? []).map(({ badge_id, name, url, logo, enabled }) => ({
        badge_id, name, url, logo, enabled,
      })))
      publish(next)
    } catch (error) {
      if (signal?.aborted || requestGeneration !== generation.current) return
      reportError(error)
    } finally {
      if (requestGeneration === generation.current) setLoading(false)
    }
  }, [api, publish, reportError])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const chooseAsset = async (file: File | undefined, kind: 'logo' | 'favicon') => {
    if (!file) return
    try {
      const next = await uploadDraft(file, kind)
      if (kind === 'logo') setLogo(next)
      else setFavicon(next)
      setMessage('')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '이미지 파일을 읽지 못했습니다.')
    }
  }

  const save = (event: React.FormEvent) => {
    event.preventDefault()
    const name = siteName.trim()
    if (!current || !name || name.length > 80) return
    const idempotencyKey = keyFor('save-site-branding', 'branding-')
    requestConfirmation({
      title: '사이트 관리 설정 저장',
      summary: [`사이트 이름: ${name}`, `로고: ${logo ? '설정' : '기본값'}`, `파비콘: ${favicon ? '설정' : '기본값'}`],
      execute: async () => {
        const updated = await api.updateSiteBranding({
          site_name: name,
          logo: requestAsset(logo),
          favicon: requestAsset(favicon),
          custom_badges: badges.map((badge, order) => ({
            ...(badge.badge_id ? { badge_id: badge.badge_id } : {}),
            name: badge.name.trim(),
            url: badge.url.trim(),
            logo: requestAsset(badge.logo),
            enabled: badge.enabled,
            order,
          })),
          restore_default: false,
        }, current.etag, idempotencyKey)
        publish(updated)
        clearKey('save-site-branding')
        await load()
      },
    })
  }

  const restore = () => {
    if (!current) return
    const idempotencyKey = keyFor('restore-site-branding', 'branding-default-')
    requestConfirmation({
      title: '사이트 관리 기본값 복원',
      summary: ['사이트 이름, 상단 로고, 파비콘을 제품 기본값으로 복원하고 등록한 상단 바로가기를 모두 제거합니다.'],
      execute: async () => {
        const updated = await api.updateSiteBranding({
          site_name: null, logo: null, favicon: null, custom_badges: null, restore_default: true,
        }, current.etag, idempotencyKey)
        publish(updated)
        clearKey('restore-site-branding')
        await load()
      },
    })
  }

  const updateBadge = (index: number, patch: Partial<BadgeDraft>) => {
    setBadges((currentBadges) => currentBadges.map((badge, badgeIndex) => (
      badgeIndex === index ? { ...badge, ...patch } : badge
    )))
  }

  const chooseBadgeLogo = async (index: number, file: File | undefined) => {
    if (!file) return
    try {
      updateBadge(index, { logo: await uploadDraft(file, 'logo') })
      setMessage('')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '바로가기 로고 파일을 읽지 못했습니다.')
    }
  }

  const moveBadge = (index: number, direction: -1 | 1) => {
    const target = index + direction
    if (target < 0 || target >= badges.length) return
    setBadges((currentBadges) => {
      const next = [...currentBadges]
      const currentBadge = next[index]
      const targetBadge = next[target]
      if (!currentBadge || !targetBadge) return currentBadges
      next[index] = targetBadge
      next[target] = currentBadge
      return next
    })
  }

  const badgesValid = badges.every((badge) => badge.name.trim()
    && badge.name.trim().length <= 40 && /^https?:\/\//i.test(badge.url.trim()))

  if (loading && !current) return <section className="panel site-management"><p>사이트 설정을 불러오는 중입니다.</p></section>

  return <section className="panel site-management" aria-label="사이트 관리">
    <header className="section-heading">
      <div><p className="eyebrow">Site branding</p><h3>사이트 관리</h3></div>
      {current && <span className="badge">ETag {current.etag}</span>}
    </header>
    <div className="site-branding-workspace">
      <form className="site-branding-form" onSubmit={save}>
        <label>사이트 이름<input value={siteName} maxLength={80} required onChange={(event) => setSiteName(event.target.value)} /></label>
        <label>홈/상단 로고<input type="file" accept="image/png,image/jpeg" onChange={(event) => void chooseAsset(event.target.files?.[0], 'logo')} /><small>PNG/JPEG, 최대 512 KiB. SVG는 허용하지 않습니다.</small></label>
        <button className="button button-secondary" type="button" onClick={() => setLogo(null)}>로고 기본값 사용</button>
        <label>파비콘/브라우저 심볼<input type="file" accept="image/png,image/x-icon,.ico" onChange={(event) => void chooseAsset(event.target.files?.[0], 'favicon')} /><small>PNG/ICO, 최대 128 KiB.</small></label>
        <button className="button button-secondary" type="button" onClick={() => setFavicon(null)}>파비콘 기본값 사용</button>
        <fieldset className="site-custom-badges">
          <legend>상단 바로가기 <small>{badges.length}/5</small></legend>
          {badges.length === 0 && <p>등록된 바로가기가 없습니다.</p>}
          {badges.map((badge, index) => <section className="site-custom-badge-editor" key={badge.badge_id ?? `new-${index}`} aria-label={`바로가기 ${index + 1}`}>
            <label>이름<input value={badge.name} maxLength={40} required onChange={(event) => updateBadge(index, { name: event.target.value })} /></label>
            <label>URL<input type="url" inputMode="url" value={badge.url} maxLength={2048} required placeholder="https://" onChange={(event) => updateBadge(index, { url: event.target.value })} /></label>
            <label>로고<input aria-label={`바로가기 ${index + 1} 로고`} type="file" accept="image/png,image/jpeg" onChange={(event) => void chooseBadgeLogo(index, event.target.files?.[0])} /></label>
            <label className="site-custom-badge-enabled"><input type="checkbox" checked={badge.enabled} onChange={(event) => updateBadge(index, { enabled: event.target.checked })} />표시</label>
            <div className="site-custom-badge-actions">
              {badge.logo && <button className="button button-secondary" type="button" onClick={() => updateBadge(index, { logo: null })}>로고 제거</button>}
              <button className="button button-secondary" type="button" disabled={index === 0} onClick={() => moveBadge(index, -1)}>위로</button>
              <button className="button button-secondary" type="button" disabled={index === badges.length - 1} onClick={() => moveBadge(index, 1)}>아래로</button>
              <button className="button button-secondary" type="button" onClick={() => setBadges((currentBadges) => currentBadges.filter((_, badgeIndex) => badgeIndex !== index))}>삭제</button>
            </div>
          </section>)}
          <button className="button button-secondary" type="button" disabled={badges.length >= 5} onClick={() => setBadges((currentBadges) => [...currentBadges, { name: '', url: '', logo: null, enabled: true }])}>바로가기 추가</button>
        </fieldset>
        {message && <p className="notice notice-error" role="alert">{message}</p>}
        <div className="action-row">
          <button className="button button-primary" type="submit" disabled={!current || !siteName.trim() || !badgesValid}>저장</button>
          <button className="button button-secondary" type="button" disabled={!current} onClick={restore}>기본값 복원</button>
        </div>
      </form>
      <section className="site-branding-preview" aria-label="현재 미리보기">
        <p className="eyebrow">Current preview</p>
        <div className="site-branding-preview-header">
          <span>{logo ? <img src={logo.data_url} alt="현재 상단 로고 미리보기" /> : <strong>DR</strong>}</span>
          <strong>{siteName.trim() || 'DataRiver'}</strong>
        </div>
        <div className="site-branding-preview-browser">
          <span>{favicon ? <img src={favicon.data_url} alt="현재 파비콘 미리보기" /> : 'DR'}</span>
          <span>{siteName.trim() || 'DataRiver'}</span>
        </div>
      </section>
    </div>
  </section>
}
