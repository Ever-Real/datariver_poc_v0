import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PocApp } from './PocApp'
import { resetPocMemory } from './pocApi'

vi.mock('../auth/AuthProvider', () => import('./pocAuthCompat'))
vi.mock('../api/useStableApiClient', () => import('./pocApi'))
vi.mock('../api/client', () => import('./pocClientCompat'))
vi.mock('../runtimeConfig', () => import('./pocRuntimeConfig'))

function renderPoc() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <PocApp />
    </QueryClientProvider>,
  )
}

const localProfile = {
  subject: '00000000-0000-4000-8000-000000000111',
  display_name: 'POC User',
  email: 'poc.user@local',
  roles: ['admin'],
  authentication_assurance: 'PASSWORD',
  default_workspace_id: '00000000-0000-4000-8000-000000000061',
  workspace_selection_enabled: false,
  hardware_webauthn_enabled: false,
  password_change_supported: false,
  authorization: {
    policy_version: 'POC_PROFILE_CAPABILITIES_V1',
    role: 'admin',
    capabilities: [
      'catalog.read', 'catalog.execute', 'catalog.manage', 'chat.query', 'change.read',
      'change.execute', 'change.manage',
      'quality.read', 'quality.execute', 'quality.manage', 'knowledge.read',
      'knowledge.manage', 'knowledge.review', 'monitoring.read', 'admin.manage',
    ],
    system_scope: 'GLOBAL',
    system_ids: [],
  },
}
let activeProfile = localProfile

function requestPath(input: RequestInfo | URL) {
  return input instanceof Request
    ? new URL(input.url).pathname
    : new URL(String(input), 'https://poc.invalid').pathname
}

function providerRequestPaths() {
  return vi.mocked(globalThis.fetch).mock.calls
    .map(([input]) => requestPath(input))
    .filter((path) => !path.startsWith('/auth/'))
}

function navigation() {
  return screen.findByRole('navigation', { name: '주 메뉴' })
}

describe('POC compatibility application', () => {
  beforeEach(() => {
    resetPocMemory()
    activeProfile = localProfile
    window.history.replaceState({}, '', '/poc.html?page=dashboard')
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => (
      requestPath(input) === '/auth/me'
        ? Promise.resolve(new Response(JSON.stringify(activeProfile), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }))
        : Promise.reject(new Error('POC provider request is not configured'))
    )))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the original dashboard layout with only the compact navigation POC badge', async () => {
    renderPoc()

    expect(screen.queryByTestId('poc-banner')).not.toBeInTheDocument()
    expect(await screen.findByLabelText('POC mode')).toHaveTextContent('[poc]')
    expect(await screen.findByRole('heading', { name: 'Governance Dashboard' })).toBeVisible()
    expect(screen.getByRole('navigation', { name: 'Governance shortcuts' })).toBeVisible()
    expect(providerRequestPaths()).toEqual([])
  })

  it('uses the viewer projection for menus and rejects a forged direct Admin URL', async () => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) },
      removeItem: (key: string) => { storage.delete(key) },
      clear: () => { storage.clear() },
    })
    window.localStorage.setItem('roles', '["admin"]')
    activeProfile = {
      ...localProfile,
      roles: ['viewer'],
      authorization: {
        policy_version: 'POC_PROFILE_CAPABILITIES_V1' as const,
        role: 'viewer' as const,
        capabilities: [
          'catalog.read', 'chat.query', 'change.read', 'quality.read',
          'knowledge.read', 'monitoring.read',
        ],
        system_scope: 'GLOBAL' as const,
        system_ids: [],
      },
    }
    window.history.replaceState({}, '', '/poc.html?page=admin&adminSection=memberships')

    renderPoc()

    await waitFor(() => expect(new URL(window.location.href).searchParams.get('page')).toBe('dashboard'))
    const menu = within(await navigation())
    expect(menu.getByRole('button', { name: '검색' })).toBeVisible()
    expect(menu.getByRole('button', { name: /품질관리/ })).toBeVisible()
    expect(menu.queryByRole('button', { name: '등록관리' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'POC User 사용자 메뉴' }))
    expect(screen.queryByRole('menuitem', { name: '관리자메뉴' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '등록관리' })).not.toBeInTheDocument()
  })

  it('keeps the original catalog workspace without showing fixture metadata', async () => {
    renderPoc()
    fireEvent.click(within(await navigation()).getByRole('button', { name: '검색' }))

    expect(await screen.findByRole('heading', { name: '데이터 카탈로그 검색' })).toBeVisible()
    expect(await screen.findByText('현재 권한 범위에서 표시할 자산이 없습니다.')).toBeVisible()
    const query = screen.getByRole('combobox', { name: '데이터셋 이름이나 설명 검색' })
    fireEvent.change(query, { target: { value: 'yield' } })
    fireEvent.submit(screen.getByRole('search', { name: '카탈로그 상세 검색' }))

    const results = screen.getByRole('region', { name: '카탈로그 검색 결과' })
    expect(await within(results).findByText('검색 조건에 맞는 허용 자산이 없습니다.')).toBeVisible()
    expect(providerRequestPaths()).toEqual([])
  })

  it('preserves primary pages and moves admin-oriented pages under the authenticated POC user', async () => {
    renderPoc()
    const pages = [
      ['변경관리', '변경 요청과 승인'],
      ['모니터링', 'Infrastructure Monitoring'],
      ['거버넌스', '거버넌스'],
      ['Chat', '카탈로그 Chat'],
    ] as const

    for (const [menuName, heading] of pages) {
      fireEvent.click(within(await navigation()).getByRole('button', { name: new RegExp(menuName) }))
      expect(await screen.findByRole('heading', { name: heading })).toBeVisible()
      expect(screen.getByLabelText('POC mode')).toHaveTextContent('[poc]')
    }

    fireEvent.click(screen.getByRole('button', { name: 'POC User 사용자 메뉴' }))
    expect(screen.getByRole('menu', { name: '사용자 작업' })).toBeVisible()
    expect(screen.getByText('POC USER')).toBeVisible()
    expect(screen.getByRole('menuitem', { name: '등록관리' })).toBeVisible()
    expect(screen.getByRole('menuitem', { name: '품질관리' })).toBeVisible()
    expect(screen.getByRole('menuitem', { name: '지식관리' })).toBeVisible()
    expect(screen.getByRole('menuitem', { name: '용어사전' })).toBeVisible()
    expect(await screen.findByRole('menuitem', { name: '관리자메뉴' })).toBeVisible()
    expect(screen.queryByRole('menuitem', { name: '계정/권한' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '기능별 권한' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '시스템 설정' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '보존·파기 거버넌스' })).not.toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '나가기' })).toBeVisible()
    expect(screen.queryByRole('menuitem', { name: '내 프로필' })).not.toBeInTheDocument()
    expect(screen.queryByText(/WebAuthn 보안키 등록/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: '지식관리' }))
    expect(await screen.findByRole('heading', { name: '지식관리' })).toBeVisible()
    const requestedPaths = providerRequestPaths()
    expect(requestedPaths.length).toBeGreaterThan(0)
    expect(requestedPaths.every((path) => path.startsWith('/api/v1/change-history/'))).toBe(true)
  })

  it('fails Chat closed when LLM Chat is not configured', async () => {
    renderPoc()
    fireEvent.click(within(await navigation()).getByRole('button', { name: /Chat/ }))
    await screen.findByRole('heading', { name: '카탈로그 Chat' })
    const input = screen.getByRole('textbox', { name: '카탈로그 질문' })
    fireEvent.change(input, { target: { value: 'wafer 품질 근거를 다시 알려줘' } })
    fireEvent.submit(input.closest('form')!)

    expect(await screen.findByText(/검증 불가: LLM Chat 연결을 설정해야 합니다/)).toBeVisible()
    expect(screen.queryByText(/98\.75%/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Synthetic catalog/)).not.toBeInTheDocument()
    expect(providerRequestPaths()).toEqual([])
  })

  it('shows the bounded POC user and system settings administration surfaces', async () => {
    window.history.replaceState({}, '', '/poc.html?page=admin&adminSection=memberships')
    renderPoc()

    await waitFor(() => expect(window.location.search).toContain('page=admin'))
    expect(await screen.findByRole('heading', { name: /관리자 및 데이터 거버넌스|Administration and data governance/ })).toBeVisible()
    expect(screen.queryByText('WebAuthn 보안키 인증이 필요합니다.')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '계정/권한' })).toBeVisible()
    expect(screen.getByRole('button', { name: '사용자 생성' })).toBeEnabled()

    fireEvent.click(screen.getByRole('tab', { name: /시스템 설정|System settings/ }))
    expect(await screen.findByRole('heading', { name: '시스템 설정' })).toBeVisible()
    expect(screen.getAllByText('DataHub GMS').length).toBeGreaterThan(0)
    expect(screen.getByRole('tab', { name: /기능별 권한|Feature access/ })).toBeVisible()
    expect(screen.queryByRole('table', { name: 'POC 기능별 권한 현황' })).not.toBeInTheDocument()
    expect(screen.queryByText('OPEN')).not.toBeInTheDocument()
    expect(providerRequestPaths()).toEqual(['/api/v1/admin/users'])
  })

  it('opens the existing redacted security-policy view from the administrator menu', async () => {
    window.history.replaceState(
      {},
      '',
      '/poc.html?page=admin&adminSection=memberships&adminView=policies&adminDetail=classification',
    )
    renderPoc()

    expect(await screen.findByRole('tab', { name: '보안정책' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(await screen.findByRole('table', { name: '현재 유효 분류 정책 요약' })).toBeVisible()
    expect(screen.getByRole('row', { name: /PUBLIC ABAC INTERNAL_APPROVED_ONLY/ })).toBeVisible()
    expect(screen.getByRole('row', { name: /RESTRICTED.*DENY DENY/ })).toBeVisible()
    expect(screen.getByText(/정적 최소 접근 기준/)).toBeVisible()
    expect(providerRequestPaths()).toEqual([])
  })
})
