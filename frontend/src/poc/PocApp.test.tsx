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

function navigation() {
  return screen.getByRole('navigation', { name: '주 메뉴' })
}

describe('POC compatibility application', () => {
  beforeEach(() => {
    resetPocMemory()
    window.history.replaceState({}, '', '/poc.html?page=dashboard')
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('POC must not use fetch'))))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the original dashboard layout under the permanent POC boundary banner', async () => {
    renderPoc()

    expect(screen.getByTestId('poc-banner')).toHaveTextContent(
      /POC\s*\/\s*NO AUTH\s*\/\s*SAMPLE DATA\s*\/\s*NOT FOR PRODUCTION/,
    )
    expect(await screen.findByRole('heading', { name: 'Governance Dashboard' })).toBeVisible()
    expect(screen.getByRole('navigation', { name: 'Governance shortcuts' })).toBeVisible()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('keeps the original catalog search, results and detail interaction', async () => {
    renderPoc()
    fireEvent.click(within(navigation()).getByRole('button', { name: '검색' }))

    expect(await screen.findByRole('heading', { name: '데이터 카탈로그 검색' })).toBeVisible()
    expect((await screen.findAllByText('wafer_inspection_events'))[0]).toBeVisible()
    const query = screen.getByRole('combobox', { name: '데이터셋 이름이나 설명 검색' })
    fireEvent.change(query, { target: { value: 'yield' } })
    fireEvent.submit(screen.getByRole('search', { name: '카탈로그 상세 검색' }))

    const results = screen.getByRole('region', { name: '카탈로그 검색 결과' })
    expect((await within(results).findAllByText('yield_summary_daily'))[0]).toBeVisible()
    expect(within(results).queryByText('lot_genealogy')).not.toBeInTheDocument()
    fireEvent.click(within(results).getByTitle('yield_summary_daily'))
    expect(await screen.findByText('Table details')).toBeVisible()
    expect(screen.getByText('Column metadata')).toBeVisible()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('preserves every original primary page and removes login-specific menu actions', async () => {
    renderPoc()
    const pages = [
      ['등록관리', '데이터 등록'],
      ['변경관리', '변경 요청과 승인'],
      ['품질관리', '품질관리'],
      ['지식관리', '지식관리'],
      ['모니터링', 'Infrastructure Monitoring'],
      ['거버넌스', '거버넌스'],
      ['Chat', '카탈로그 Chat'],
    ] as const

    for (const [menuName, heading] of pages) {
      fireEvent.click(within(navigation()).getByRole('button', { name: new RegExp(menuName) }))
      expect(await screen.findByRole('heading', { name: heading })).toBeVisible()
      expect(screen.getByTestId('poc-banner')).toBeVisible()
    }

    fireEvent.click(screen.getByRole('button', { name: 'POC Sample User 사용자 메뉴' }))
    expect(screen.getByRole('menu', { name: '사용자 작업' })).toBeVisible()
    expect(screen.queryByRole('menuitem', { name: '나가기' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: '내 프로필' })).not.toBeInTheDocument()
    expect(screen.queryByText(/WebAuthn 보안키 등록/)).not.toBeInTheDocument()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('updates chat history only through the browser-memory adapter', async () => {
    renderPoc()
    fireEvent.click(within(navigation()).getByRole('button', { name: /Chat/ }))
    await screen.findByRole('heading', { name: '카탈로그 Chat' })
    fireEvent.click(await screen.findByRole('button', { name: 'Wafer inspection 품질 상태 열기' }))
    expect(await screen.findByText(/98\.75%/)).toBeVisible()

    const input = screen.getByRole('textbox', { name: '카탈로그 질문' })
    fireEvent.change(input, { target: { value: 'wafer 품질 근거를 다시 알려줘' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() => expect(screen.getAllByText(/98\.75%/).length).toBeGreaterThan(1))
    expect(screen.getByText(/개발 검증 세션/)).toBeVisible()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('shows the bounded POC user and system settings administration surfaces', async () => {
    window.history.replaceState({}, '', '/poc.html?page=admin&adminSection=memberships')
    renderPoc()

    await waitFor(() => expect(window.location.search).toContain('page=admin'))
    expect(await screen.findByRole('heading', { name: /관리자 및 데이터 거버넌스|Administration and data governance/ })).toBeVisible()
    expect(screen.getByRole('heading', { name: '계정/권한' })).toBeVisible()
    expect(screen.getByRole('button', { name: '사용자 등록' })).toBeEnabled()

    fireEvent.click(screen.getByRole('tab', { name: /시스템 설정|System settings/ }))
    expect(await screen.findByRole('heading', { name: '시스템 설정' })).toBeVisible()
    expect(screen.getAllByText('DataHub GMS').length).toBeGreaterThan(0)
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})
