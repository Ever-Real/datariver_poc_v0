import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import { AdminApi } from './adminApi'
import { PocFeaturePermissionAdmin } from './PocFeaturePermissionAdmin'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import type { PocFeatureSecurityPolicy, PocFeatureSecurityCell, PocFeature, PocRole, TableSecurityGrade } from '../../api/types'

function json(data: unknown, etag?: string): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (etag) headers.set('ETag', etag)
  return new Response(JSON.stringify(data), { headers })
}

const features: PocFeature[] = ['catalog', 'registration', 'change', 'quality', 'knowledge', 'governance', 'chat', 'monitoring']
const roles: PocRole[] = ['viewer', 'developer', 'data_steward', 'manager', 'admin']
const grades: TableSecurityGrade[] = ['normal', 'credential', 'restricted']

const cells: PocFeatureSecurityCell[] = []
for (const feature of features) {
  for (const role of roles) {
    for (const grade of grades) {
      const available = !['registration', 'knowledge', 'quality'].includes(feature)
        || ['data_steward', 'manager', 'admin'].includes(role)
      cells.push({
        feature,
        role,
        grade,
        allow: role === 'admin' || (available && grade === 'normal'),
      })
    }
  }
}

const defaultPolicy: PocFeatureSecurityPolicy = {
  version: 0,
  schema_version: 1,
  updated_at: null,
  updated_by: null,
  reason: 'APPROVED_PRODUCT_DEFAULT',
  cells,
}

describe('PocFeaturePermissionAdmin', () => {
  it('loads and displays the security policy matrix', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(defaultPolicy, '"0"')))
    const api = new AdminApi(new ApiClient('/api/v1', () => 'token', () => 'w1'))
    const reportError = vi.fn()

    render(<PocFeaturePermissionAdmin
      api={api}
      requestConfirmation={vi.fn()}
      reportError={reportError}
      keyFor={(i) => i}
      clearKey={vi.fn()}
    />)

    await waitFor(() => {
      expect(screen.getByText('기능 권한 정책 (v0)')).toBeInTheDocument()
    })
    
    // Check checkboxes
    const viewerCheckboxes = screen.getAllByRole('checkbox', { name: /Viewer/i })
    expect(viewerCheckboxes.length).toBe(24) // 8 features * 3 grades
    expect(screen.getAllByText('대외비')).toHaveLength(8)
    expect(screen.getAllByText('극비')).toHaveLength(8)
    expect(screen.getByRole('checkbox', { name: '등록관리 수동 등록·메타데이터 변경 요청 - 일반 - Viewer' })).toBeDisabled()
  })

  it('allows saving modifications', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(defaultPolicy, '"0"'))
      .mockResolvedValueOnce(json({ ...defaultPolicy, version: 1 }, '"1"'))
      .mockResolvedValueOnce(json({ ...defaultPolicy, version: 1 }, '"1"'))

    vi.stubGlobal('fetch', fetchMock)
    
    const api = new AdminApi(new ApiClient('/api/v1', () => 'token', () => 'w1'))
    const requestConfirmation = vi.fn((pending: PendingAdminMutation) => {
      void pending.execute()
    })
    
    render(<PocFeaturePermissionAdmin
      api={api}
      requestConfirmation={requestConfirmation}
      reportError={vi.fn()}
      keyFor={(i) => i}
      clearKey={vi.fn()}
    />)

    await waitFor(() => {
      expect(screen.getByText('기능 권한 정책 (v0)')).toBeInTheDocument()
    })

    // Modify a value
    const catalogRestrictedViewer = screen.getByRole('checkbox', { name: '검색 검색·상세·계보·Resource Tree - 극비 - Viewer' })
    fireEvent.click(catalogRestrictedViewer)

    const reasonInput = screen.getByLabelText('변경 사유')
    fireEvent.change(reasonInput, { target: { value: 'Testing changes' } })

    const saveButton = screen.getByRole('button', { name: '저장' })
    fireEvent.click(saveButton)

    await waitFor(() => {
      expect(requestConfirmation).toHaveBeenCalled()
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/admin/feature-security-policy'),
        expect.objectContaining({ method: 'PUT', ifMatch: '"0"' })
      )
    })
  })

  it('makes admin cells read-only and checked', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(defaultPolicy, '"0"')))
    const api = new AdminApi(new ApiClient('/api/v1', () => 'token', () => 'w1'))
    
    render(<PocFeaturePermissionAdmin
      api={api}
      requestConfirmation={vi.fn()}
      reportError={vi.fn()}
      keyFor={(i) => i}
      clearKey={vi.fn()}
    />)

    await waitFor(() => {
      expect(screen.getByText('기능 권한 정책 (v0)')).toBeInTheDocument()
    })

    const adminCheckboxes = screen.getAllByRole('checkbox', { name: /Admin/i })
    expect(adminCheckboxes.length).toBe(24) // 8 features * 3 grades
    adminCheckboxes.forEach(cb => {
      expect(cb).toBeDisabled()
      expect(cb).toBeChecked()
    })
  })
})
