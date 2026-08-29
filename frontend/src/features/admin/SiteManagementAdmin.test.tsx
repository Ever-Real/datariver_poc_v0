import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AdminApi } from './adminApi'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { SiteManagementAdmin } from './SiteManagementAdmin'

function fixture() {
  const getSiteBranding = vi.fn().mockResolvedValue({
    site_name: 'Generic Portal', logo: null, favicon: null, etag: '"2"',
  })
  const updateSiteBranding = vi.fn().mockResolvedValue({
    site_name: 'Updated Portal', logo: null, favicon: null,
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
      site_name: 'Updated Portal', logo: null, favicon: null, restore_default: false,
    }, '"2"', 'generic-save-site-branding')
  })

  it('restores every branding field through the same confirmed CAS boundary', async () => {
    const { updateSiteBranding, pending } = fixture()
    expect(await screen.findByRole('region', { name: '현재 미리보기' })).toHaveTextContent('Generic Portal')
    fireEvent.click(screen.getByRole('button', { name: '기본값 복원' }))
    expect(pending()?.title).toBe('사이트 관리 기본값 복원')
    await pending()?.execute()
    expect(updateSiteBranding).toHaveBeenCalledWith({
      site_name: null, logo: null, favicon: null, restore_default: true,
    }, '"2"', 'generic-restore-site-branding')
    await waitFor(() => expect(screen.getByLabelText('사이트 이름')).toHaveValue('Generic Portal'))
  })
})
