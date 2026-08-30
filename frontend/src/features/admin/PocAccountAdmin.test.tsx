import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PocAccountAdmin } from './PocAccountAdmin'
import { getAdminMessages } from './messages'

function renderAccounts() {
  const api = {
    listPocAdminUsers: vi.fn(() => Promise.resolve({ version: 1, items: [], systems: [] })),
  }
  render(<PocAccountAdmin
    api={api as never}
    messages={getAdminMessages('ko')}
    requestConfirmation={vi.fn()}
    keyFor={() => 'test-key'}
    clearKey={vi.fn()}
    reportError={vi.fn()}
    onStepUp={vi.fn(() => Promise.resolve())}
    onPasswordReauth={vi.fn(() => Promise.resolve())}
    onEnroll={vi.fn(() => Promise.resolve())}
  />)
  return api
}

async function openCreateDialog() {
  await screen.findByRole('table', { name: 'DataRiver local human 계정' })
  fireEvent.click(screen.getByRole('button', { name: '사용자 생성' }))
  return screen.findByRole('dialog', { name: 'Local human 사용자 생성' })
}

describe('PocAccountAdmin local human creation', () => {
  it('keeps dirty input and the creation dialog open when discard is rejected', async () => {
    renderAccounts()
    const dialog = await openCreateDialog()
    const username = within(dialog).getByRole('textbox', { name: 'Username' })
    fireEvent.change(username, { target: { value: 'local.human' } })

    fireEvent.click(within(dialog).getByRole('button', { name: '취소' }))
    const confirmation = await screen.findByRole('dialog', { name: '사용자 작성 취소' })
    fireEvent.click(within(confirmation).getByRole('button', { name: '계속 작성' }))

    expect(screen.queryByRole('dialog', { name: '사용자 작성 취소' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Local human 사용자 생성' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Username' })).toHaveValue('local.human')
  })

  it('discards dirty input only after confirmation and closes clean forms immediately', async () => {
    renderAccounts()
    const dialog = await openCreateDialog()
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Username' }), { target: { value: 'local.human' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '취소' }))
    fireEvent.click(within(await screen.findByRole('dialog', { name: '사용자 작성 취소' })).getByRole('button', { name: '작성 취소' }))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Local human 사용자 생성' })).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '사용자 생성' }))
    const reopenedDialog = await screen.findByRole('dialog', { name: 'Local human 사용자 생성' })
    expect(within(reopenedDialog).getByRole('textbox', { name: 'Username' })).toHaveValue('')
    fireEvent.click(within(reopenedDialog).getByRole('button', { name: '취소' }))

    expect(screen.queryByRole('dialog', { name: '사용자 작성 취소' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Local human 사용자 생성' })).not.toBeInTheDocument()
  })

  it('does not request discard for Escape or backdrop clicks', async () => {
    renderAccounts()
    const dialog = await openCreateDialog()
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Username' }), { target: { value: 'local.human' } })

    fireEvent.keyDown(dialog, { key: 'Escape' })
    fireEvent.click(dialog)

    expect(screen.queryByRole('dialog', { name: '사용자 작성 취소' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Local human 사용자 생성' })).toBeInTheDocument()
  })
})
