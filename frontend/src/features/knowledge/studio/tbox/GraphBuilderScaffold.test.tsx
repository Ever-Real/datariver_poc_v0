import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GraphBuilderScaffold } from './GraphBuilderScaffold'

describe('GraphBuilderScaffold', () => {
  it('starts with no fabricated schema and keeps manual nodes local', () => {
    render(<GraphBuilderScaffold busy={false} onContinue={vi.fn()} />)

    expect(screen.getByText('Accepted schema가 없습니다.')).toBeInTheDocument()
    expect(screen.getByText('Accepted T-Box · 0개')).toBeInTheDocument()
    expect(screen.getByText(/서버에 저장되지 않습니다/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '로컬 노드 추가' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '선택 노드 삭제' })).toBeDisabled()
  })

  it('adds a user-named node and deletes only the explicitly selected node', () => {
    render(<GraphBuilderScaffold busy={false} onContinue={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('로컬 테스트 노드 이름'), {
      target: { value: 'Employee' },
    })
    fireEvent.click(screen.getByRole('button', { name: '로컬 노드 추가' }))

    const canvas = screen.getByLabelText('T-Box 로컬 테스트 캔버스')
    expect(within(canvas).getByText('Employee')).toBeInTheDocument()
    expect(screen.queryByText('Accepted schema가 없습니다.')).not.toBeInTheDocument()
    expect(screen.getByText('로컬 노드').nextElementSibling).toHaveTextContent('1개')

    fireEvent.click(within(canvas).getByLabelText('Employee, 로컬 테스트 노드'))
    const deleteButton = screen.getByRole('button', { name: '선택 노드 삭제' })
    expect(deleteButton).toBeEnabled()
    fireEvent.click(deleteButton)

    expect(within(canvas).queryByText('Employee')).not.toBeInTheDocument()
    expect(screen.getByText('Accepted schema가 없습니다.')).toBeInTheDocument()
  })

  it('locks every scaffold mutation outside DRAFT', () => {
    const onContinue = vi.fn()
    render(
      <GraphBuilderScaffold
        busy={false}
        lifecycleState="REVIEW"
        onContinue={onContinue}
      />,
    )

    expect(screen.getByLabelText('로컬 테스트 노드 이름')).toBeDisabled()
    expect(screen.getByRole('button', { name: '로컬 노드 추가' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '서버 Accepted T-Box 확인' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('REVIEW')
  })
})
