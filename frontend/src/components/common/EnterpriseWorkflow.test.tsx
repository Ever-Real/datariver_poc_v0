import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FlowCanvas } from './FlowCanvas'
import { WorkflowStepper } from './WorkflowStepper'

describe('enterprise workflow primitives', () => {
  it('marks the canonical current step and prevents future-stage inspection by default', () => {
    const onSelect = vi.fn()
    render(
      <WorkflowStepper
        currentIndex={1}
        onSelect={onSelect}
        steps={[
          { id: 'request', label: '요청 상세' },
          { id: 'review', label: '검토 및 영향도' },
          { id: 'test', label: '테스트 및 결과' },
          { id: 'approval', label: '최종 승인' },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: /검토 및 영향도/ })).toHaveAttribute('aria-current', 'step')
    expect(screen.queryByRole('button', { name: /테스트 및 결과/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /요청 상세/ }))
    expect(onSelect).toHaveBeenCalledWith(0)
  })

  it('keeps an accessible, non-zero graph surface when authorized graph data is empty', () => {
    render(
      <FlowCanvas
        ariaLabel="영향도 그래프"
        nodes={[]}
        edges={[]}
        emptyTitle="인가된 계보가 없습니다."
        emptyDescription="대상을 선택하세요."
      />,
    )

    const canvas = screen.getByRole('region', { name: '영향도 그래프' })
    expect(canvas).toHaveStyle({ height: '420px' })
    expect(screen.getByLabelText('인가된 계보가 없습니다., 대상을 선택하세요.')).toBeInTheDocument()
  })
})
