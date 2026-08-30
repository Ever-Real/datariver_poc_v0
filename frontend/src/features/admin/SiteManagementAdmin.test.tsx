import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { SiteManagementAdmin } from './SiteManagementAdmin'

function fixture() {
  const getSiteBranding = vi.fn().mockResolvedValue({
    site_name: 'Generic Portal', logo: null, favicon: null, custom_badges: [], etag: '"2"',
  })
  const updateSiteBranding = vi.fn<AdminApi['updateSiteBranding']>().mockResolvedValue({
    site_name: 'Updated Portal', logo: null, favicon: null, custom_badges: [],
  })
  let pending: PendingAdminMutation | undefined
  const view = render(<SiteManagementAdmin
    api={{ getSiteBranding, updateSiteBranding } as unknown as AdminApi}
    requestConfirmation={(next) => { pending = next }}
    reportError={vi.fn()}
    keyFor={(intent) => `generic-${intent}`}
    clearKey={vi.fn()}
  />)
  return { ...view, getSiteBranding, updateSiteBranding, pending: () => pending }
}

describe('SiteManagementAdmin', () => {
  it('previews the current setting and submits an exact CAS/idempotent save', async () => {
    const { updateSiteBranding, pending } = fixture()
    expect(await screen.findByRole('region', { name: '현재 미리보기' })).toHaveTextContent('Generic Portal')
    fireEvent.change(screen.getByLabelText('사이트 이름'), { target: { value: 'Updated Portal' } })
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    expect(pending()?.title).toBe('사이트 관리 설정 저장')
    await pending()?.execute()
    expect(updateSiteBranding).toHaveBeenCalledWith({
      site_name: 'Updated Portal', logo: null, favicon: null, custom_badges: [], restore_default: false,
    }, '"2"', 'generic-save-site-branding')
  })

  it('restores every branding field through the same confirmed CAS boundary', async () => {
    const { updateSiteBranding, pending } = fixture()
    expect(await screen.findByRole('region', { name: '현재 미리보기' })).toHaveTextContent('Generic Portal')
    fireEvent.click(screen.getByRole('button', { name: '기본값 복원' }))
    expect(pending()?.title).toBe('사이트 관리 기본값 복원')
    await pending()?.execute()
    expect(updateSiteBranding).toHaveBeenCalledWith({
      site_name: null, logo: null, favicon: null, custom_badges: null, restore_default: true,
    }, '"2"', 'generic-restore-site-branding')
    await waitFor(() => expect(screen.getByLabelText('사이트 이름')).toHaveValue('Generic Portal'))
  })

  it('adds, orders and removes at most five custom header badges in the confirmed save payload', async () => {
    const { updateSiteBranding, pending } = fixture()
    await screen.findByRole('region', { name: '현재 미리보기' })
    for (let index = 0; index < 5; index += 1) {
      fireEvent.click(screen.getByRole('button', { name: '바로가기 추가' }))
      const regions = screen.getAllByRole('region', { name: /바로가기 \d/ })
      const region = regions[index]
      if (!region) throw new Error('Expected custom badge editor')
      fireEvent.change(region.querySelectorAll('input')[0]!, { target: { value: `Generic ${index + 1}` } })
      fireEvent.change(region.querySelectorAll('input')[1]!, { target: { value: `https://example.test/${index + 1}` } })
    }
    expect(screen.getByRole('button', { name: '바로가기 추가' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    await pending()?.execute()
    const payload = updateSiteBranding.mock.calls[0]?.[0]
    expect(payload?.custom_badges).toHaveLength(5)
    expect(payload?.custom_badges?.[0]).toMatchObject({ name: 'Generic 1', url: 'https://example.test/1', order: 0 })
    expect(payload?.custom_badges?.[4]).toMatchObject({ name: 'Generic 5', url: 'https://example.test/5', order: 4 })
    expect(updateSiteBranding.mock.calls[0]?.slice(1)).toEqual(['"2"', 'generic-save-site-branding'])
  })
})
