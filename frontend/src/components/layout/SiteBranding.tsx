import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { SiteBranding } from '../../api/types'

export const defaultSiteBranding: SiteBranding = {
  site_name: 'DataRiver',
  logo: null,
  favicon: null,
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

function safeBranding(value: unknown): SiteBranding | undefined {
  if (!value || typeof value !== 'object') return undefined
  const branding = value as Record<string, unknown>
  if (typeof branding.site_name !== 'string' || !branding.site_name.trim()
    || branding.site_name.length > 80 || !isBrandingAsset(branding.logo, 'logo') || !isBrandingAsset(branding.favicon, 'favicon')) {
    return undefined
  }
  return branding as unknown as SiteBranding
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
