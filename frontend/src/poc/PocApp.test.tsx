import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PocApp } from './PocApp'

describe('static POC application', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/poc.html#/overview')
    window.scrollTo = vi.fn()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps the no-auth sample-data banner visible while navigating', async () => {
    render(<PocApp />)

    expect(screen.getByTestId('poc-banner')).toHaveTextContent(
      /POC\s*\/\s*NO AUTH\s*\/\s*SAMPLE DATA\s*\/\s*NOT FOR PRODUCTION/,
    )
    const navigation = screen.getByRole('navigation', { name: '주 메뉴' })
    fireEvent.click(within(navigation).getByRole('button', { name: '검색' }))

    expect(await screen.findByRole('heading', { name: 'Find trusted data faster' })).toBeVisible()
    expect(screen.getByTestId('poc-banner')).toBeVisible()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('searches deterministic fixture assets and opens column details', async () => {
    render(<PocApp />)
    const navigation = screen.getByRole('navigation', { name: '주 메뉴' })
    fireEvent.click(within(navigation).getByRole('button', { name: '검색' }))
    const search = await screen.findByRole('textbox', { name: 'Search sample assets' })

    fireEvent.change(search, { target: { value: 'equipment' } })

    expect(screen.getAllByText('equipment_alarm_history').length).toBeGreaterThan(0)
    expect(screen.queryByText('lot_genealogy')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Columns/ }))
    expect(screen.getByText('alarm_code')).toBeVisible()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('advances registration only in memory and resets after remount', async () => {
    const firstRender = render(<PocApp />)
    const navigation = screen.getByRole('navigation', { name: '주 메뉴' })
    fireEvent.click(within(navigation).getByRole('button', { name: '등록관리' }))
    await screen.findByRole('heading', { name: 'Move an intake request forward' })

    fireEvent.click(screen.getByRole('button', { name: /다음 단계/ }))
    expect(screen.getAllByText('검증 완료').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: /다음 단계/ }))
    expect(screen.getAllByText('등록 완료').length).toBeGreaterThan(0)

    firstRender.unmount()
    render(<PocApp />)

    await waitFor(() => expect(screen.getAllByText('요청 접수').length).toBeGreaterThan(0))
    expect(screen.getByRole('button', { name: /다음 단계/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /시연 완료/ })).not.toBeInTheDocument()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('steps a Quality Run through sanitized deterministic results', async () => {
    render(<PocApp />)
    const shortcuts = screen.getByRole('navigation', { name: 'POC walkthrough shortcuts' })
    fireEvent.click(within(shortcuts).getByRole('link', { name: /Quality Run/ }))
    await screen.findByRole('heading', { name: 'Follow a quality execution' })

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '14')
    fireEvent.click(screen.getByRole('button', { name: /실행 시작/ }))
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '62')
    fireEvent.click(screen.getByRole('button', { name: /결과 완료/ }))

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    expect(screen.getByText('0', { selector: '.run-results strong' })).toBeVisible()
    expect(screen.getByText('raw rows')).toBeVisible()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})
