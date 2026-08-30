import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TopNavigation } from './TopNavigation'
import { SiteBrandingProvider } from './SiteBranding'

const pngDataUrl = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='

afterEach(() => {
  vi.unstubAllGlobals()
  document.head.querySelectorAll('link[rel~="icon"]').forEach((node) => node.remove())
  document.title = ''
})

describe('SiteBrandingProvider', () => {
  it('applies validated public branding to title, top logo and favicon without inline styles', async () => {
    const favicon = document.createElement('link')
    favicon.rel = 'icon'
    favicon.href = 'data:image/png;base64,default'
    document.head.append(favicon)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      site_name: 'Generic Portal',
      logo: { asset_id: 'generic-logo', mime_type: 'image/png', byte_size: 68, data_url: pngDataUrl },
      favicon: { asset_id: 'generic-icon', mime_type: 'image/png', byte_size: 68, data_url: pngDataUrl },
      custom_badges: [{
        badge_id: 'generic-badge', name: 'Generic Docs', url: 'https://docs.example.test/path',
        logo: null, enabled: true, order: 0,
      }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

    render(<SiteBrandingProvider><TopNavigation
      page="dashboard"
      workspace="generic"
      deploymentTier="SINGLE_NODE_PILOT"
      displayName="Generic User"
      adminMenuItems={[]}
      externalSystemLinks={[]}
      onNavigate={vi.fn()}
      onNavigateAdmin={vi.fn()}
      onSearch={vi.fn()}
      onWorkspaceChange={vi.fn()}
    /></SiteBrandingProvider>)

    const brand = await screen.findByRole('button', { name: 'Generic Portal 홈' })
    const logo = brand.querySelector('img')
    await waitFor(() => expect(document.title).toBe('Generic Portal'))
    expect(logo).toHaveAttribute('src', pngDataUrl)
    expect(logo).not.toHaveAttribute('style')
    expect(favicon.href).toBe(pngDataUrl)
    expect(favicon).not.toHaveAttribute('style')
    expect(screen.getByRole('link', { name: 'Generic Docs 새 창에서 열기' })).toHaveAttribute(
      'href', 'https://docs.example.test/path',
    )
    expect(screen.getByRole('link', { name: 'Generic Docs 새 창에서 열기' })).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('keeps a legacy response compatible and rejects an unsafe custom badge projection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      site_name: 'Unsafe Portal', logo: null, favicon: null,
      custom_badges: [{
        badge_id: 'unsafe-badge', name: 'Unsafe Link', url: 'javascript:alert(1)',
        logo: null, enabled: true, order: 0,
      }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    render(<SiteBrandingProvider><TopNavigation
      page="dashboard"
      workspace="generic"
      deploymentTier="SINGLE_NODE_PILOT"
      displayName="Generic User"
      adminMenuItems={[]}
      externalSystemLinks={[]}
      onNavigate={vi.fn()}
      onNavigateAdmin={vi.fn()}
      onSearch={vi.fn()}
      onWorkspaceChange={vi.fn()}
    /></SiteBrandingProvider>)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('link', { name: /Unsafe Link/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'DataRiver 홈' })).toBeInTheDocument()
  })
})
