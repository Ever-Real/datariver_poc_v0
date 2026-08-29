import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../../api/client'
import type {
  PocFeature,
  PocFeatureSecurityCell,
  PocFeatureSecurityPolicy,
  PocRole,
  TableSecurityGrade,
} from '../../api/types'
import type { PendingAdminMutation } from './AdminMutationConfirmDialog'
import { AdminApi } from './adminApi'
import { PocFeaturePermissionAdmin } from './PocFeaturePermissionAdmin'

function json(data: unknown, etag?: string, status = 200): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (etag) headers.set('ETag', etag)
  return new Response(JSON.stringify(data), { headers, status })
}

const features: PocFeature[] = ['catalog', 'registration', 'change', 'quality', 'knowledge', 'governance', 'chat', 'monitoring']
const roles: PocRole[] = ['viewer', 'developer', 'data_steward', 'manager', 'admin']
const grades: TableSecurityGrade[] = ['normal', 'credential', 'restricted']

const cells: PocFeatureSecurityCell[] = []
for (const feature of features) {
  for (const role of roles) {
    for (const grade of grades) {
      const available = !['registration', 'knowledge', 'quality'].includes(feature)
        || (feature === 'registration' ? role === 'data_steward' : ['data_steward', 'manager', 'admin'].includes(role))
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

function api() {
  return new AdminApi(new ApiClient('/api/v1', () => 'token', () => 'w1'))
}

function renderAdmin(overrides: Partial<React.ComponentProps<typeof PocFeaturePermissionAdmin>> = {}) {
  return render(<PocFeaturePermissionAdmin
    api={api()}
    requestConfirmation={vi.fn()}
    reportError={vi.fn()}
    keyFor={() => 'feature-policy-idempotency-key'}
    clearKey={vi.fn()}
    {...overrides}
  />)
}

afterEach(() => vi.unstubAllGlobals())

describe('PocFeaturePermissionAdmin', () => {
  it('renders every fixed policy cell in a sortable TanStack table with source versions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(defaultPolicy, '"0"')))
    renderAdmin()

    expect(screen.getByText('데이터를 불러오는 중입니다.')).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: '기능 권한 정책 cell' })
    await waitFor(() => expect(within(table).getAllByRole('checkbox')).toHaveLength(120))

    expect(within(table).getAllByRole('row')).toHaveLength(121)
    expect(screen.getByText('기능 권한 정책 (v0)')).toBeInTheDocument()
    expect(within(table).getAllByText('v0 / schema v1')).toHaveLength(120)
    expect(within(table).getByRole('button', { name: '역할 정렬: 없음' })).toBeInTheDocument()
    expect(screen.getByText('전체 120개 중 120개 cell')).toBeInTheDocument()
  })

  it('searches and filters actual feature, role, grade, and permission fields, then sorts rows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(defaultPolicy, '"0"')))
    renderAdmin()
    const table = await screen.findByRole('table', { name: '기능 권한 정책 cell' })
    await waitFor(() => expect(within(table).getAllByRole('checkbox')).toHaveLength(120))

    fireEvent.change(screen.getByRole('searchbox', { name: '검색' }), { target: { value: 'registration' } })
    expect(within(table).getAllByRole('checkbox')).toHaveLength(15)
    fireEvent.change(screen.getByRole('combobox', { name: '역할' }), { target: { value: 'viewer' } })
    expect(within(table).getAllByRole('checkbox')).toHaveLength(3)
    fireEvent.change(screen.getByRole('combobox', { name: '보안 등급' }), { target: { value: 'restricted' } })
    expect(within(table).getAllByRole('checkbox')).toHaveLength(1)
    expect(screen.getByText('전체 120개 중 1개 cell')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '필터 초기화' }))
    fireEvent.change(screen.getByRole('combobox', { name: '권한 상태' }), { target: { value: 'ALLOW' } })
    expect(within(table).getAllByRole('checkbox')).toHaveLength(49)

    fireEvent.click(screen.getByRole('button', { name: '필터 초기화' }))
    fireEvent.click(within(table).getByRole('button', { name: '역할 정렬: 없음' }))
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Admin')
  })

  it('preserves all 120 cells and the original ETag in the confirmed CAS update payload', async () => {
    const updatedPolicy = { ...defaultPolicy, version: 1 }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(defaultPolicy, '"0"'))
      .mockResolvedValueOnce(json(updatedPolicy, '"1"'))
      .mockResolvedValueOnce(json(updatedPolicy, '"1"'))
    vi.stubGlobal('fetch', fetchMock)
    let pending: PendingAdminMutation | undefined
    const clearKey = vi.fn()
    renderAdmin({ requestConfirmation: (mutation) => { pending = mutation }, clearKey })

    const checkbox = await screen.findByRole('checkbox', { name: '검색 검색·상세·계보·Resource Tree - 극비 - Viewer' })
    fireEvent.click(checkbox)
    fireEvent.change(screen.getByRole('searchbox', { name: '검색' }), { target: { value: 'catalog' } })
    fireEvent.change(screen.getByRole('combobox', { name: '역할' }), { target: { value: 'viewer' } })
    fireEvent.change(screen.getByRole('combobox', { name: '보안 등급' }), { target: { value: 'restricted' } })
    expect(screen.getByText('전체 120개 중 1개 cell')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('변경 사유'), { target: { value: 'Testing exact CAS payload' } })
    fireEvent.click(screen.getByRole('button', { name: '저장' }))

    expect(pending).toBeDefined()
    expect(pending?.summary).toContain('고정 정책 cell 120개')
    await pending?.execute()

    const [, updateOptions] = fetchMock.mock.calls[1] as [string, RequestInit & { ifMatch?: string; idempotencyKey?: string }]
    expect(typeof updateOptions.body).toBe('string')
    if (typeof updateOptions.body !== 'string') throw new Error('Expected JSON request body')
    const body = JSON.parse(updateOptions.body) as { cells: PocFeatureSecurityCell[]; reason: string }
    expect(updateOptions).toEqual(expect.objectContaining({
      method: 'PUT',
      ifMatch: '"0"',
      idempotencyKey: 'feature-policy-idempotency-key',
    }))
    expect(body.cells).toHaveLength(120)
    expect(body.cells).toEqual(cells.map((cell) => (
      cell.feature === 'catalog' && cell.role === 'viewer' && cell.grade === 'restricted'
        ? { ...cell, allow: true }
        : cell
    )))
    expect(body.reason).toBe('Testing exact CAS payload')
    expect(clearKey).toHaveBeenCalledWith('save-feature-policy')
  })

  it('surfaces a stale CAS rejection without retrying or changing the submitted ETag', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(defaultPolicy, '"0"'))
      .mockResolvedValueOnce(json({ code: 'FEATURE_SECURITY_POLICY_VERSION_STALE', message: 'stale' }, undefined, 409))
    vi.stubGlobal('fetch', fetchMock)
    let pending: PendingAdminMutation | undefined
    const clearKey = vi.fn()
    renderAdmin({ requestConfirmation: (mutation) => { pending = mutation }, clearKey })

    fireEvent.click(await screen.findByRole('checkbox', { name: '검색 검색·상세·계보·Resource Tree - 극비 - Viewer' }))
    fireEvent.change(screen.getByLabelText('변경 사유'), { target: { value: 'Testing stale policy response' } })
    fireEvent.click(screen.getByRole('button', { name: '저장' }))

    await expect(pending?.execute()).rejects.toBeDefined()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ method: 'PUT', ifMatch: '"0"' }))
    expect(clearKey).not.toHaveBeenCalled()
  })

  it('keeps admin and role-ineligible assurance cells immutable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(defaultPolicy, '"0"')))
    renderAdmin()

    const table = await screen.findByRole('table', { name: '기능 권한 정책 cell' })
    await waitFor(() => expect(within(table).getAllByRole('checkbox')).toHaveLength(120))
    const adminCheckboxes = within(table).getAllByRole('checkbox', { name: /Admin/i })
    expect(adminCheckboxes).toHaveLength(24)
    adminCheckboxes.forEach((checkbox) => {
      expect(checkbox).toBeDisabled()
      expect(checkbox).toBeChecked()
    })
    expect(screen.getByRole('checkbox', { name: '등록관리 수동 등록·메타데이터 변경 요청 - 일반 - Viewer' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: '등록관리 수동 등록·메타데이터 변경 요청 - 일반 - Manager' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: '등록관리 수동 등록·메타데이터 변경 요청 - 일반 - Data Steward' })).toBeEnabled()
  })

  it('renders an honest empty policy state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ ...defaultPolicy, cells: [] }, '"0"')))
    renderAdmin()

    expect(await screen.findByText('서버가 반환한 정책 cell이 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('전체 0개 중 0개 cell')).toBeInTheDocument()
  })

  it('reports invalid or stale read versions in-page and supports retry', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ ...defaultPolicy, version: 1 }, '"0"'))
      .mockResolvedValueOnce(json(defaultPolicy, '"0"'))
    vi.stubGlobal('fetch', fetchMock)
    const reportError = vi.fn()
    renderAdmin({ reportError })

    expect(await screen.findByRole('alert')).toHaveTextContent('보안 정책 버전 ETag를 검증하지 못했습니다.')
    expect(reportError).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText('기능 권한 정책 (v0)')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
