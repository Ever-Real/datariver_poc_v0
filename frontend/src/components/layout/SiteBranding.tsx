import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { SiteBranding } from '../../api/types'

export const defaultSiteBranding: SiteBranding = {
  site_name: 'DataRiver',
  logo: null,
  favicon: null,
  custom_badges: [],
}

interface SiteBrandingContextValue {
  branding: SiteBranding
  publish: (branding: SiteBranding) => void
}

const SiteBrandingContext = createContext<SiteBrandingContextValue>({
  branding: defaultSiteBranding,
  publish: () => undefined,
})

function isBrandingAsset(value: unknown, kind: 'logo' | 'favicon'): boolean {
  if (!value || typeof value !== 'object') return value === null
  const asset = value as Record<string, unknown>
  const mimeTypes = kind === 'logo' ? ['image/png', 'image/jpeg'] : ['image/png', 'image/x-icon']
  const maximumBytes = kind === 'logo' ? 512 * 1024 : 128 * 1024
  return typeof asset.asset_id === 'string'
    && mimeTypes.includes(String(asset.mime_type))
    && Number.isSafeInteger(asset.byte_size) && Number(asset.byte_size) > 0 && Number(asset.byte_size) <= maximumBytes
    && typeof asset.data_url === 'string'
    && asset.data_url.length <= Math.ceil(maximumBytes / 3) * 4 + 40
    && asset.data_url.startsWith(`data:${String(asset.mime_type)};base64,`)
}

function isSafeBadgeUrl(value: unknown) {
  if (typeof value !== 'string' || value.length > 2048) return false
  try {
    const parsed = new URL(value)
    return ['http:', 'https:'].includes(parsed.protocol)
      && Boolean(parsed.hostname) && parsed.username === '' && parsed.password === ''
  } catch {
    return false
  }
}

function safeCustomBadges(value: unknown) {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > 5) return undefined
  const orders = new Set<number>()
  const badges = value.map((candidate) => {
    if (!candidate || typeof candidate !== 'object') return undefined
    const badge = candidate as Record<string, unknown>
    if (typeof badge.badge_id !== 'string' || typeof badge.name !== 'string' || !badge.name.trim()
      || badge.name.length > 40 || !isSafeBadgeUrl(badge.url) || typeof badge.enabled !== 'boolean'
      || !Number.isSafeInteger(badge.order) || Number(badge.order) < 0 || Number(badge.order) >= value.length
      || orders.has(Number(badge.order)) || !isBrandingAsset(badge.logo, 'logo')) return undefined
    orders.add(Number(badge.order))
    return badge
  })
  if (badges.some((badge) => !badge)) return undefined
  return badges.sort((left, right) => Number(left?.order) - Number(right?.order))
}

function safeBranding(value: unknown): SiteBranding | undefined {
  if (!value || typeof value !== 'object') return undefined
  const branding = value as Record<string, unknown>
  const customBadges = safeCustomBadges(branding.custom_badges)
  if (typeof branding.site_name !== 'string' || !branding.site_name.trim()
    || branding.site_name.length > 80 || !isBrandingAsset(branding.logo, 'logo')
    || !isBrandingAsset(branding.favicon, 'favicon') || !customBadges) {
    return undefined
  }
  return { ...branding, custom_badges: customBadges } as unknown as SiteBranding
}

export function SiteBrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState(defaultSiteBranding)
  const defaultFavicon = useRef<string | undefined>(undefined)
  const publish = useCallback((next: SiteBranding) => setBranding(safeBranding(next) ?? defaultSiteBranding), [])

  useEffect(() => {
    const controller = new AbortController()
    void fetch('/api/v1/site-branding', { cache: 'no-store', signal: controller.signal })
      .then(async (response) => response.ok ? response.json() as Promise<unknown> : undefined)
      .then((value) => { if (!controller.signal.aborted && value) publish(value as SiteBranding) })
      .catch(() => undefined)
    return () => controller.abort()
  }, [publish])

  useEffect(() => {
    document.title = branding.site_name
    const favicon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')
    if (favicon) {
      defaultFavicon.current ??= favicon.href
      favicon.href = branding.favicon?.data_url ?? defaultFavicon.current
    }
  }, [branding])

  const value = useMemo(() => ({ branding, publish }), [branding, publish])
  return <SiteBrandingContext.Provider value={value}>{children}</SiteBrandingContext.Provider>
}

export function useSiteBranding() {
  return useContext(SiteBrandingContext)
}
